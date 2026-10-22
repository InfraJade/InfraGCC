"""Idempotent seed data.

    python -m app.seed dev                     # 2 sites, 4 rooms, 12 racks, collectors, servers, routes
    python -m app.seed loadtest --servers 500  # onboard N simulated servers for the load test

Servers are onboarded the way an engineer would (BMC address, rack, position, collector). Vendor, model,
serial and parts are filled in by the collector from the hardware itself.

The simulated fleet layout mirrors mockups/src/gcc_redfish_sim/catalog.py (FLEET): BMC i (1-based) listens on
SIM_BASE_PORT + i and runs model SIM_MODELS[(i - 1) % len(SIM_MODELS)].
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt, mask_target
from app.core.db import dispose_engine, session_scope
from app.models import (
    AlertRoute,
    Collector,
    FirmwareBaseline,
    MaintenanceWindow,
    Rack,
    Room,
    Server,
    Site,
)

log = logging.getLogger("gcc.seed")


@dataclass(frozen=True)
class SimModel:
    vendor: str
    model: str
    height_u: int
    bios: str
    bmc: str


# Keep in sync with mockups/src/gcc_redfish_sim/catalog.py (approved firmware = the catalog's current).
SIM_MODELS: list[SimModel] = [
    SimModel("Dell", "PowerEdge R750", 2, "1.15.2", "7.10.70.00"),
    SimModel("HPE", "ProLiant DL380 Gen10", 2, "U30 v2.96 (06/24/2024)", "3.08"),
    SimModel("Lenovo", "ThinkSystem SR650 V3", 2, "ESE124B-3.10", "ESX320R-3.30"),
    SimModel("Dell", "PowerEdge R650", 1, "1.15.2", "7.10.70.00"),
    SimModel("HPE", "ProLiant DL360 Gen10", 1, "U32 v2.96 (06/24/2024)", "3.08"),
    SimModel("Lenovo", "ThinkSystem SR630 V3", 1, "ESE124B-3.10", "ESX320R-3.30"),
]

SITES = [
    # code, name, city, country, timezone, rooms → racks
    (
        "PNQ1",
        "Pune DC1",
        "Pune",
        "India",
        "Asia/Kolkata",
        {"Hall A": ["A01", "A02", "A03"], "Hall B": ["B01", "B02", "B03"]},
    ),
    (
        "HYD1",
        "Hyderabad DC2",
        "Hyderabad",
        "India",
        "Asia/Kolkata",
        {"Hall 1": ["C01", "C02", "C03"], "Hall 2": ["D01", "D02", "D03"]},
    ),
]

COLLECTORS = [("pnq1-col-a", "PNQ1"), ("pnq1-col-b", "PNQ1"), ("hyd1-col-a", "HYD1")]

# Reference BMCs served unchanged by the DMTF Redfish Mockup Server containers.
REFERENCE_BMCS = ["http://redfish-dell:8000", "http://redfish-hpe:8000", "http://redfish-lenovo:8000"]


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


async def _get_or_create_site(
    session: AsyncSession, code: str, name: str, city: str, country: str, tz: str
) -> Site:
    site = (await session.execute(select(Site).where(Site.code == code))).scalar_one_or_none()
    if site is None:
        site = Site(code=code, name=name, city=city, country=country, timezone=tz)
        session.add(site)
        await session.flush()
    return site


async def seed_topology(session: AsyncSession) -> dict[str, list[Rack]]:
    """2 sites, 4 rooms, 12 racks, 3 collectors. Returns racks per site code."""
    racks_by_site: dict[str, list[Rack]] = {}
    for code, name, city, country, tz, rooms in SITES:
        site = await _get_or_create_site(session, code, name, city, country, tz)
        racks_by_site[code] = []
        for room_name, rack_names in rooms.items():
            room = (
                await session.execute(select(Room).where(Room.site_id == site.id, Room.name == room_name))
            ).scalar_one_or_none()
            if room is None:
                room = Room(site_id=site.id, name=room_name, floor="Ground")
                session.add(room)
                await session.flush()
            for rack_name in rack_names:
                rack = (
                    await session.execute(select(Rack).where(Rack.room_id == room.id, Rack.name == rack_name))
                ).scalar_one_or_none()
                if rack is None:
                    rack = Rack(
                        room_id=room.id, name=rack_name, row=rack_name[0], height_u=42, power_capacity_w=8000
                    )
                    session.add(rack)
                    await session.flush()
                racks_by_site[code].append(rack)
    for name, site_code in COLLECTORS:
        exists = (await session.execute(select(Collector).where(Collector.name == name))).scalar_one_or_none()
        if exists is None:
            site = (await session.execute(select(Site).where(Site.code == site_code))).scalar_one()
            session.add(Collector(site_id=site.id, name=name))
    await session.flush()
    return racks_by_site


async def _collectors_for(session: AsyncSession, site_id: int) -> list[Collector]:
    rows = await session.execute(
        select(Collector).where(Collector.site_id == site_id).order_by(Collector.name)
    )
    return list(rows.scalars())


async def onboard_simulated(
    session: AsyncSession,
    racks_by_site: dict[str, list[Rack]],
    count: int,
    host: str,
    base_port: int,
    per_rack: int,
    first_u: int,
    spacing_u: int,
) -> int:
    """Onboard simulated BMCs 1..count, spreading them over the given racks."""
    all_racks = [r for code in sorted(racks_by_site) for r in racks_by_site[code]]
    existing = {h for (h,) in (await session.execute(select(Server.bmc_host))).all()}
    site_by_rack: dict[int, int] = {}
    for rack in all_racks:
        room = await session.get(Room, rack.room_id)
        assert room is not None
        site_by_rack[rack.id] = room.site_id
    collectors_by_site: dict[int, list[Collector]] = {}
    added = 0
    for i in range(1, count + 1):
        bmc_host = f"http://{host}:{base_port + i}"
        if bmc_host in existing:
            continue
        rack = all_racks[((i - 1) // per_rack) % len(all_racks)]
        slot = (i - 1) % per_rack
        site_id = site_by_rack[rack.id]
        if site_id not in collectors_by_site:
            collectors_by_site[site_id] = await _collectors_for(session, site_id)
        collectors = collectors_by_site[site_id]
        model = SIM_MODELS[(i - 1) % len(SIM_MODELS)]
        session.add(
            Server(
                site_id=site_id,
                rack_id=rack.id,
                position_u=first_u + slot * spacing_u,
                height_u=model.height_u,
                bmc_host=bmc_host,
                collector_id=collectors[i % len(collectors)].id if collectors else None,
                asset_tag=f"GCC-{i:05d}",
            )
        )
        added += 1
    await session.flush()
    return added


async def onboard_reference(session: AsyncSession, racks_by_site: dict[str, list[Rack]]) -> None:
    rack = racks_by_site["PNQ1"][0]
    room = await session.get(Room, rack.room_id)
    assert room is not None
    collectors = await _collectors_for(session, room.site_id)
    for idx, host in enumerate(REFERENCE_BMCS):
        exists = (await session.execute(select(Server).where(Server.bmc_host == host))).scalar_one_or_none()
        if exists is None:
            session.add(
                Server(
                    site_id=room.site_id,
                    rack_id=rack.id,
                    position_u=32 + idx * 3,
                    height_u=2,
                    bmc_host=host,
                    collector_id=collectors[0].id,
                    asset_tag=f"GCC-REF-{idx + 1}",
                )
            )
    await session.flush()


async def seed_routes(session: AsyncSession) -> None:
    if (await session.execute(select(func.count()).select_from(AlertRoute))).scalar_one():
        return
    sites = {s.code: s for s in (await session.execute(select(Site))).scalars()}
    sink = os.environ.get("SEED_TEAMS_SINK_URL", "http://bmc-simulator:9100/webhooks/teams")
    routes = [
        ("NOC on-call (all sites, Critical)", "*", None, "Critical", 0, "email", "noc-oncall@gcc.example"),
        (
            "Facilities team (Warning and up)",
            "facilities",
            None,
            "Warning",
            0,
            "email",
            "facilities@gcc.example",
        ),
        ("Platform team", "platform", None, "Warning", 0, "email", "platform-team@gcc.example"),
        ("Pune DC1 Teams channel", "*", "PNQ1", "Warning", 0, "teams", f"{sink}/pnq1"),
        ("Hyderabad DC2 Teams channel", "*", "HYD1", "Warning", 0, "teams", f"{sink}/hyd1"),
        ("Escalation: NOC duty manager", "*", None, "Critical", 1, "email", "noc-manager@gcc.example"),
    ]
    for name, route, site_code, sev, level, channel, target in routes:
        session.add(
            AlertRoute(
                name=name,
                route=route,
                site_id=sites[site_code].id if site_code else None,
                min_severity=sev,
                escalation_level=level,
                channel=channel,
                target_encrypted=encrypt(target),
                target_hint=mask_target(channel, target),
            )
        )
    await session.flush()


async def seed_baselines(session: AsyncSession) -> None:
    for m in SIM_MODELS:
        for component, version in (("BIOS", m.bios), ("BMC", m.bmc)):
            exists = (
                await session.execute(
                    select(FirmwareBaseline).where(
                        FirmwareBaseline.vendor == m.vendor,
                        FirmwareBaseline.model == m.model,
                        FirmwareBaseline.component == component,
                    )
                )
            ).scalar_one_or_none()
            if exists is None:
                session.add(
                    FirmwareBaseline(
                        vendor=m.vendor,
                        model=m.model,
                        component=component,
                        version=version,
                        notes="Approved Q3 baseline",
                        updated_by="seed",
                    )
                )
    await session.flush()


async def seed_maintenance(session: AsyncSession, racks_by_site: dict[str, list[Rack]]) -> None:
    if (await session.execute(select(func.count()).select_from(MaintenanceWindow))).scalar_one():
        return
    rack = racks_by_site["HYD1"][-1]
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=3)
    session.add(
        MaintenanceWindow(
            scope="rack",
            rack_id=rack.id,
            starts_at=start,
            ends_at=start + timedelta(hours=4),
            reason="Planned PDU replacement",
            created_by="seed",
        )
    )
    await session.flush()


async def seed_dev() -> None:
    async with session_scope() as session:
        racks = await seed_topology(session)
        added = await onboard_simulated(
            session,
            racks,
            count=_env_int("SEED_SIM_SERVERS", 36),
            host=os.environ.get("SEED_SIM_HOST", "bmc-simulator"),
            base_port=_env_int("SEED_SIM_BASE_PORT", 20000),
            per_rack=3,
            first_u=6,
            spacing_u=4,
        )
        if os.environ.get("SEED_REFERENCE_BMCS", "1") == "1":
            await onboard_reference(session, racks)
        await seed_routes(session)
        await seed_baselines(session)
        await seed_maintenance(session, racks)
    log.info("dev seed complete (%d simulated servers added)", added)


async def seed_loadtest(servers: int) -> None:
    """Add a load-test hall per site with enough racks for `servers` 1U/2U servers (13 per 42U rack)."""
    async with session_scope() as session:
        await seed_topology(session)
        per_rack = 13
        racks_needed = -(-servers // per_rack)
        racks_by_site: dict[str, list[Rack]] = {"PNQ1": [], "HYD1": []}
        for idx in range(racks_needed):
            code = "PNQ1" if idx % 2 == 0 else "HYD1"
            site = (await session.execute(select(Site).where(Site.code == code))).scalar_one()
            room = (
                await session.execute(
                    select(Room).where(Room.site_id == site.id, Room.name == "Load Test Hall")
                )
            ).scalar_one_or_none()
            if room is None:
                room = Room(site_id=site.id, name="Load Test Hall", floor="1")
                session.add(room)
                await session.flush()
            name = f"LT{idx + 1:02d}"
            rack = (
                await session.execute(select(Rack).where(Rack.room_id == room.id, Rack.name == name))
            ).scalar_one_or_none()
            if rack is None:
                rack = Rack(room_id=room.id, name=name, row="LT", height_u=42, power_capacity_w=12000)
                session.add(rack)
                await session.flush()
            racks_by_site[code].append(rack)
        added = await onboard_simulated(
            session,
            racks_by_site,
            count=servers,
            host=os.environ.get("SEED_SIM_HOST", "bmc-simulator"),
            base_port=_env_int("SEED_SIM_BASE_PORT", 20000),
            per_rack=per_rack,
            first_u=2,
            spacing_u=3,
        )
        await seed_baselines(session)
    log.info("load-test seed complete (%d servers added)", added)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("dev", help="seed the local development data set")
    lt = sub.add_parser("loadtest", help="onboard N simulated servers")
    lt.add_argument("--servers", type=int, default=500)
    args = parser.parse_args()

    async def run() -> None:
        try:
            if args.command == "dev":
                await seed_dev()
            else:
                await seed_loadtest(args.servers)
        finally:
            await dispose_engine()

    asyncio.run(run())


if __name__ == "__main__":
    main()
