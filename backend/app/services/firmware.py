"""Firmware compliance (parameter 20, DECISIONS.md D17).

Installed firmware (`firmware_inventory`, matched by `component_key`) is compared with the approved
`firmware_baselines` for the server's vendor and model. One compliance alert per server and component key
is open while any installed instance differs from the baseline; it resolves when the daily check finds the
firmware back on baseline (or the baseline is removed). Components without a baseline are not judged.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertState, RuleType, ServerStatus
from app.models import Alert, FirmwareBaseline, FirmwareInventory, Server
from app.services.alerts.effects import Effects
from app.services.alerts.maintenance import muted_server_ids
from app.services.alerts.rules import load_rules
from app.services.alerts.store import AlertStore, Firing, server_key


@dataclass(frozen=True)
class Deviation:
    server_id: int
    component_key: str
    approved: str
    installed: dict[str, str]  # instance name -> version, only the ones that differ


@dataclass
class ComplianceResult:
    checked_servers: int = 0
    deviations: list[Deviation] = field(default_factory=list)
    opened_or_updated: int = 0
    resolved: int = 0


async def find_deviations(session: AsyncSession) -> tuple[int, list[Deviation]]:
    rows = await session.execute(
        select(
            Server.id,
            FirmwareInventory.component,
            FirmwareInventory.component_key,
            FirmwareInventory.version,
            FirmwareBaseline.version,
        )
        .join(FirmwareInventory, FirmwareInventory.server_id == Server.id)
        .join(
            FirmwareBaseline,
            (FirmwareBaseline.vendor == Server.vendor)
            & (FirmwareBaseline.model == Server.model)
            & (FirmwareBaseline.component == FirmwareInventory.component_key),
        )
        .where(Server.status != ServerStatus.DECOMMISSIONED.value)
        .order_by(Server.id, FirmwareInventory.component_key, FirmwareInventory.component)
    )
    servers: set[int] = set()
    grouped: dict[tuple[int, str], tuple[str, dict[str, str]]] = {}
    for sid, component, key, installed, approved in rows:
        servers.add(sid)
        entry = grouped.setdefault((sid, key), (approved, {}))
        if installed != approved:
            entry[1][component] = installed
    deviations = [
        Deviation(sid, key, approved, diff) for (sid, key), (approved, diff) in grouped.items() if diff
    ]
    return len(servers), deviations


async def run_compliance(session: AsyncSession, now: datetime, effects: Effects) -> ComplianceResult:
    result = ComplianceResult()
    rules = [r for r in await load_rules(session, RuleType.COMPLIANCE) if r.metric is not None]
    result.checked_servers, result.deviations = await find_deviations(session)
    if not rules:
        return result
    rule = rules[0]
    assert rule.metric is not None
    active = {
        a.dedupe_key: a
        for a in (
            await session.execute(
                select(Alert).where(Alert.rule_id == rule.id, Alert.state != AlertState.RESOLVED.value)
            )
        ).scalars()
    }
    names: dict[int, tuple[str, int]] = {
        s.id: (s.display_name, s.site_id)
        for s in (
            await session.execute(
                select(Server).where(Server.id.in_({d.server_id for d in result.deviations}))
            )
        ).scalars()
    }
    muted = await muted_server_ids(session, now)
    store = AlertStore(session, now, effects)
    wanted: set[str] = set()
    by_server: dict[int, list[Deviation]] = defaultdict(list)
    for dev in result.deviations:
        by_server[dev.server_id].append(dev)
    for sid, devs in by_server.items():
        name, site_id = names[sid]
        for dev in devs:
            key = server_key(sid, rule.metric.id, dev.component_key)
            wanted.add(key)
            installed = ", ".join(f"{c} {v}" for c, v in sorted(dev.installed.items()))
            await store.fire(
                Firing(
                    rule=rule.rule,
                    key=key,
                    severity=rule.severity,
                    title=f"{rule.rule.name}: {name} ({dev.component_key})",
                    message=f"{dev.component_key} on {name}: installed {installed}; approved {dev.approved}.",
                    site_id=site_id,
                    server_id=sid,
                    metric_code=rule.metric.id,
                    component=dev.component_key,
                    muted=sid in muted,
                ),
                active.get(key),
            )
            result.opened_or_updated += 1
    for key, alert in active.items():
        if key not in wanted:
            await store.resolve(alert, "Firmware matches the approved baseline.")
            result.resolved += 1
    return result
