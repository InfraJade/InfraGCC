"""Alert rule scenarios from PLAN.md Phase 4 Verify, run against TimescaleDB as the gcc_app role."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.models import Alert
from app.services.alerts.effects import Effects
from app.services.alerts.escalation import escalate_due
from app.services.alerts.evaluate import resolve_stale_events
from app.services.alerts.missing import check_collectors, check_servers
from app.services.alerts.store import AlertStore
from app.services.firmware import run_compliance
from tests.alerts.helpers import activity, alerts, changes, evaluate, in_app_tx, kinds
from tests.ingest.fixtures import World, add_readings, metric_id

pytestmark = pytest.mark.db


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def every_minute(start: int, stop: int, value: float) -> list[tuple[float, float | None]]:
    """Samples at `now - s` for s from `start` down to `stop` seconds ago, every 60 s (negative = future)."""
    return [(s, value) for s in range(start, stop - 1, -60)]


# ------------------------------------------------------------------------------------------- threshold


async def test_threshold_fires_only_after_duration(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    await add_readings(
        session, sid, "inlet_temp_c", every_minute(300, 240, 24.0) + every_minute(180, 0, 36.0), now
    )
    # Bad for 3 minutes, but the sample in effect when the window opened was good: not yet.
    assert not kinds(await evaluate(app_engine, sid, now - timedelta(seconds=60)))
    assert not kinds(await evaluate(app_engine, sid, now))
    assert await alerts(session) == []

    await add_readings(session, sid, "inlet_temp_c", [(-60, 36.5)], now)
    effects = await evaluate(app_engine, sid, now + timedelta(seconds=60))
    [alert] = await alerts(session)
    assert (alert.rule, alert.state, alert.severity) == ("Inlet temperature high", "open", "Critical")
    assert alert.value == 36.5 and alert.threshold == 35.0 and alert.dedupe_key.startswith(f"srv:{sid}:m1:")
    assert "srv-01" in alert.title and "above the critical limit 35" in alert.message
    assert kinds(effects) == [("opened", 0)] and changes(effects) == ["opened"]
    assert await activity(session, alert.id) == ["opened"]


async def test_mixed_windows_do_not_flap_and_resolve_needs_full_duration(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    await add_readings(session, sid, "inlet_temp_c", every_minute(240, 0, 30.0), now)
    await evaluate(app_engine, sid, now)
    [alert] = await alerts(session)
    assert alert.severity == "Warning"

    # Flapping values: never resolves, never re-opens.
    for k, value in enumerate([22.0, 30.0, 22.0, 30.0], start=1):
        await add_readings(session, sid, "inlet_temp_c", [(-60 * k, value)], now)
        await evaluate(app_engine, sid, now + timedelta(seconds=60 * k))
    [same] = await alerts(session)
    assert same.id == alert.id and same.state == "open"
    assert await activity(session, alert.id) == ["opened"]

    # Good for the whole window (plus the look-back sample): resolves.
    await add_readings(session, sid, "inlet_temp_c", [(-60 * k, 22.0) for k in range(5, 10)], now)
    assert not changes(await evaluate(app_engine, sid, now + timedelta(seconds=60 * 7)))
    effects = await evaluate(app_engine, sid, now + timedelta(seconds=60 * 9))
    [done] = await alerts(session)
    assert done.state == "resolved"
    assert changes(effects) == ["resolved"]
    assert kinds(effects) == []  # never notified, so no resolution notice
    assert await activity(session, alert.id) == ["opened", "resolved"]


async def test_severity_escalates_warning_to_critical(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    await add_readings(session, sid, "inlet_temp_c", every_minute(240, 0, 30.0), now)
    await evaluate(app_engine, sid, now)
    await add_readings(session, sid, "inlet_temp_c", every_minute(-60, -300, 36.0), now)
    mid = await evaluate(
        app_engine, sid, now + timedelta(seconds=120)
    )  # mixed Warning/Critical: stays Warning
    assert kinds(mid) == []
    effects = await evaluate(app_engine, sid, now + timedelta(seconds=300))
    [alert] = await alerts(session)
    assert alert.severity == "Critical" and alert.threshold == 35.0
    assert kinds(effects) == [("severity", 0)]
    assert await activity(session, alert.id) == ["opened", "severity_raised"]


async def test_dedupe_counts_occurrences_and_recurrence_opens_new_alert(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    await add_readings(session, sid, "inlet_temp_c", every_minute(240, 0, 30.0), now)
    await evaluate(app_engine, sid, now)
    await evaluate(app_engine, sid, now)  # same samples: no new occurrence
    [alert] = await alerts(session)
    assert alert.occurrences == 1
    await add_readings(session, sid, "inlet_temp_c", [(-60, 30.0)], now)
    effects = await evaluate(app_engine, sid, now + timedelta(seconds=60))
    [alert] = await alerts(session)
    assert alert.occurrences == 2 and changes(effects) == ["updated"] and kinds(effects) == []

    await add_readings(session, sid, "inlet_temp_c", every_minute(-120, -360, 22.0), now)
    await evaluate(app_engine, sid, now + timedelta(seconds=360))
    await add_readings(session, sid, "inlet_temp_c", every_minute(-420, -660, 31.0), now)
    await evaluate(app_engine, sid, now + timedelta(seconds=660))
    rows = await alerts(session)
    assert [(r.state, r.dedupe_key == alert.dedupe_key) for r in rows] == [("resolved", True), ("open", True)]


async def test_bmc_limits_and_admin_override_precedence(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    cpu = await metric_id(session, "cpu_temp_c")
    await session.execute(
        text(
            "INSERT INTO bmc_thresholds (server_id, metric_code, component, upper_warning, upper_critical) "
            "VALUES (:s, :m, 'CPU1', 85, 95), (:s, :m, 'CPU2', 85, 95)"
        ),
        {"s": sid, "m": cpu},
    )
    await session.commit()
    await add_readings(session, sid, "cpu_temp_c", every_minute(240, 0, 90.0), now, component="CPU1")
    await add_readings(session, sid, "cpu_temp_c", every_minute(240, 0, 75.0), now, component="CPU2")
    await evaluate(app_engine, sid, now)
    [alert] = await alerts(session)
    assert (alert.component, alert.severity, alert.threshold) == ("CPU1", "Warning", 85.0)
    assert "(BMC)" in alert.message

    # A server-level admin threshold beats the BMC's limits for every CPU.
    await session.execute(
        text(
            "INSERT INTO thresholds (metric_code, scope, server_id, direction, warning, critical) "
            "VALUES (:m, 'server', :s, 'above', 70, 80)"
        ),
        {"s": sid, "m": cpu},
    )
    await session.commit()
    await evaluate(app_engine, sid, now)
    rows = {r.component: (r.severity, r.threshold) for r in await alerts(session)}
    assert rows == {"CPU1": ("Critical", 80.0), "CPU2": ("Warning", 70.0)}


async def test_power_draw_percent_of_capacity(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    cap = await metric_id(session, "power_capacity_w")
    await session.execute(
        text(
            "INSERT INTO latest_readings (server_id, metric_code, component, value, time) VALUES (:s, :m, '', 1000, :t)"
        ),
        {"s": sid, "m": cap, "t": now},
    )
    await session.commit()
    await add_readings(session, sid, "power_w", every_minute(360, 0, 950.0), now)
    await evaluate(app_engine, sid, now)
    [alert] = await alerts(session)
    assert (alert.rule, alert.severity, alert.threshold) == ("Power draw near capacity", "Warning", 90.0)
    assert "95 % of 1000 W capacity" in alert.message


# ------------------------------------------------------------------------------------------- state


async def test_state_rules_health_value_expected_links_and_consecutive(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    await add_readings(session, sid, "psu_health", [(0, 1.0)], now, component="PSU 2", status="Warning")
    await session.execute(
        text(
            "INSERT INTO components (server_id, type, name, expected_link_up) "
            "VALUES (:s, 'nic', 'NIC 1', true), (:s, 'nic', 'NIC 2', false)"
        ),
        {"s": sid},
    )
    await session.commit()
    await add_readings(session, sid, "nic_link", [(0, 0.0)], now, component="NIC 1", status="Down")
    await add_readings(session, sid, "nic_link", [(0, 0.0)], now, component="NIC 2", status="Down")
    await add_readings(session, sid, "bmc_reachable", [(120, 0.0), (60, 0.0)], now)
    await evaluate(app_engine, sid, now)
    got = {(r.rule, r.component): r.severity for r in await alerts(session)}
    assert got == {("Power supply unhealthy", "PSU 2"): "Warning", ("NIC link down", "NIC 1"): "Warning"}

    # PSU goes Critical: same alert, raised; third failed poll in a row: BMC unreachable.
    await add_readings(session, sid, "psu_health", [(-60, 2.0)], now, component="PSU 2", status="Critical")
    await add_readings(session, sid, "bmc_reachable", [(-60, 0.0)], now)
    effects = await evaluate(app_engine, sid, now + timedelta(seconds=60))
    got = {(r.rule, r.component): r.severity for r in await alerts(session)}
    assert got[("Power supply unhealthy", "PSU 2")] == "Critical"
    assert got[("BMC unreachable", "")] == "Critical"
    assert sorted(kinds(effects)) == [("opened", 0), ("severity", 0)]

    # One good poll resolves the BMC alert.
    await add_readings(session, sid, "bmc_reachable", [(-120, 1.0)], now)
    await evaluate(app_engine, sid, now + timedelta(seconds=120))
    states = {r.rule: r.state for r in await alerts(session)}
    assert states["BMC unreachable"] == "resolved"


async def test_system_health_unknown_status_keeps_state(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    await add_readings(
        session, sid, "system_health", [(s, 1.0) for s in (240, 180, 120, 60, 0)], now, status="Warning"
    )
    await evaluate(app_engine, sid, now)
    [alert] = await alerts(session)
    assert alert.rule == "System health degraded"
    await add_readings(
        session, sid, "system_health", [(s, None) for s in (-60, -120, -180, -240)], now, status="Unknown"
    )
    await evaluate(app_engine, sid, now + timedelta(seconds=240))
    [same] = await alerts(session)
    assert same.state == "open"


async def test_disabled_rule_does_not_fire(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    await session.execute(
        text("UPDATE alert_rules SET enabled = false WHERE name = 'Inlet temperature high'")
    )
    await session.commit()
    try:
        await add_readings(session, sid, "inlet_temp_c", every_minute(240, 0, 40.0), now)
        await evaluate(app_engine, sid, now)
        assert await alerts(session) == []
    finally:
        await session.execute(
            text("UPDATE alert_rules SET enabled = true WHERE name = 'Inlet temperature high'")
        )
        await session.commit()


# ------------------------------------------------------------------------------------------- maintenance


async def test_maintenance_mutes_and_suppresses_power_off(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    quiet, loud = world.server(0), world.server(8)  # PNQ1 rack in maintenance; HYD1 server not
    await session.execute(
        text(
            "INSERT INTO maintenance_windows (scope, rack_id, starts_at, ends_at, reason) "
            "VALUES ('rack', :r, :a, :b, 'test')"
        ),
        {"r": quiet.rack_id, "a": now - timedelta(hours=1), "b": now + timedelta(hours=1)},
    )
    await session.commit()
    for srv in (quiet, loud):
        await add_readings(session, srv.id, "inlet_temp_c", every_minute(240, 0, 30.0), now)
        await add_readings(session, srv.id, "power_state", every_minute(240, 0, 0.0), now, status="Off")
    quiet_fx = await evaluate(app_engine, quiet.id, now)
    loud_fx = await evaluate(app_engine, loud.id, now)

    by_server = {(r.server_id, r.rule): r for r in await alerts(session)}
    assert by_server[(quiet.id, "Inlet temperature high")].muted is True
    assert (quiet.id, "Server powered off") not in by_server  # D16: does not fire at all in a window
    assert kinds(quiet_fx) == []  # recorded but never notified
    assert by_server[(loud.id, "Server powered off")].severity == "Critical"
    assert by_server[(loud.id, "Inlet temperature high")].muted is False
    assert len(kinds(loud_fx)) == 2

    # The window ends while the problem continues: the alert is unmuted and notified then.
    await session.execute(text("DELETE FROM maintenance_windows"))
    await session.commit()
    await add_readings(session, quiet.id, "inlet_temp_c", [(-60, 30.0)], now)
    effects = await evaluate(app_engine, quiet.id, now + timedelta(seconds=60))
    inlet = next(
        r for r in await alerts(session) if r.server_id == quiet.id and r.rule == "Inlet temperature high"
    )
    assert inlet.muted is False
    assert ("opened", 0) in kinds(effects)
    assert await activity(session, inlet.id) == ["opened", "unmuted"]


# ------------------------------------------------------------------------------------------- missing data


async def test_server_missing_data_opens_and_resolves(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    await session.execute(text("UPDATE servers SET last_seen_at = :t"), {"t": now})
    await session.execute(
        text("UPDATE servers SET last_seen_at = :t WHERE id = :s"),
        {"t": now - timedelta(minutes=10), "s": sid},
    )
    await session.commit()
    _, effects = await in_app_tx(app_engine, lambda s, e: check_servers(s, now, e, 90))
    [alert] = await alerts(session)
    assert (alert.rule, alert.server_id, alert.severity) == ("Server not reporting", sid, "Critical")
    assert "10 min" in alert.message and kinds(effects) == [("opened", 0)]

    await session.execute(text("UPDATE servers SET last_seen_at = :t WHERE id = :s"), {"t": now, "s": sid})
    await session.commit()
    (_, resolved), _ = await in_app_tx(
        app_engine, lambda s, e: check_servers(s, now + timedelta(seconds=30), e, 90)
    )
    assert resolved == 1 and (await alerts(session))[0].state == "resolved"


async def test_server_missing_data_suppressed_when_site_has_no_live_collector(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    await session.execute(text("UPDATE servers SET last_seen_at = :t"), {"t": now - timedelta(minutes=10)})
    await session.execute(
        text("UPDATE collectors SET last_heartbeat = :t WHERE name LIKE 'pnq1-%'"),
        {"t": now - timedelta(minutes=10)},
    )
    await session.commit()
    await in_app_tx(app_engine, lambda s, e: check_servers(s, now, e, 90))
    rows = await alerts(session)
    assert {r.server_id for r in rows} == {world.server(8).id, world.server(9).id}  # HYD1 only

    await in_app_tx(app_engine, lambda s, e: check_collectors(s, now, e))
    collectors = await alerts(session, "a.collector_id IS NOT NULL")
    assert sorted(r.collector_id for r in collectors) == sorted(
        [world.collectors["pnq1-col-a"].id, world.collectors["pnq1-col-b"].id]
    )


async def test_collector_heartbeat_missing(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    cid = world.collectors["hyd1-col-a"].id
    await session.execute(text("UPDATE collectors SET last_heartbeat = :t"), {"t": now})
    await session.execute(
        text("UPDATE collectors SET last_heartbeat = :t WHERE id = :c"),
        {"t": now - timedelta(minutes=5), "c": cid},
    )
    await session.commit()
    _, effects = await in_app_tx(app_engine, lambda s, e: check_collectors(s, now, e))
    [alert] = await alerts(session)
    assert (alert.rule, alert.collector_id, alert.server_id) == ("Collector heartbeat missing", cid, None)
    assert "hyd1-col-a" in alert.title and kinds(effects) == [("opened", 0)]

    await session.execute(
        text("UPDATE collectors SET last_heartbeat = :t WHERE id = :c"), {"t": now, "c": cid}
    )
    await session.commit()
    await in_app_tx(app_engine, lambda s, e: check_collectors(s, now + timedelta(seconds=30), e))
    assert (await alerts(session))[0].state == "resolved"


# ------------------------------------------------------------------------------------------- events


async def _event(
    session: AsyncSession, sid: int, entry: str, t: datetime, created: datetime, msg_id: str = "PSU0003"
) -> None:
    await session.execute(
        text(
            "INSERT INTO events (server_id, time, severity, message, message_id, entry_id, created_at) "
            "VALUES (:s, :t, 'Critical', 'PSU 2 lost input.', :m, :e, :c)"
        ),
        {"s": sid, "t": t, "m": msg_id, "e": entry, "c": created},
    )
    await session.commit()


async def test_critical_events_dedupe_count_and_auto_resolve(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    await _event(session, sid, "Sel/1", now - timedelta(hours=23), now - timedelta(hours=23))
    await session.execute(
        text(
            "INSERT INTO events (server_id, time, severity, message, entry_id) "
            "VALUES (:s, :t, 'Warning', 'Fan slow', 'Sel/0'), (:s, :old, 'Critical', 'ancient', 'Sel/-1')"
        ),
        {"s": sid, "t": now, "old": now - timedelta(days=30)},
    )
    await session.commit()
    effects = await evaluate(app_engine, sid, now)
    [alert] = await alerts(session)
    assert (alert.rule, alert.component, alert.occurrences, alert.severity) == (
        "Critical system event",
        "PSU0003",
        1,
        "Critical",
    )
    assert kinds(effects) == [("opened", 0)]

    await _event(session, sid, "Sel/2", now - timedelta(hours=22), now - timedelta(hours=22))
    await evaluate(app_engine, sid, now)
    [alert] = await alerts(session)
    assert alert.occurrences == 2 and "2 occurrences" in alert.message

    # 24 h after the last occurrence it resolves itself, and the same entries do not reopen it.
    later = now + timedelta(hours=3)
    count, _ = await in_app_tx(app_engine, lambda s, e: resolve_stale_events(s, later, e))
    assert count == 1
    await evaluate(app_engine, sid, now)
    [alert] = await alerts(session)
    assert alert.state == "resolved"

    # A new occurrence afterwards opens a new alert.
    await _event(session, sid, "Sel/3", now, later + timedelta(seconds=1))
    await evaluate(app_engine, sid, now)
    rows = await alerts(session)
    assert [(r.state, r.occurrences) for r in rows] == [("resolved", 2), ("open", 1)]


# ------------------------------------------------------------------------------------------- compliance


async def test_firmware_compliance_opens_and_resolves(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    await session.execute(
        text("UPDATE servers SET vendor = 'Dell', model = 'PowerEdge R750' WHERE id = :s"), {"s": sid}
    )
    await session.execute(
        text(
            "INSERT INTO firmware_baselines (vendor, model, component, version) VALUES "
            "('Dell', 'PowerEdge R750', 'BIOS', '1.15.2'), ('Dell', 'PowerEdge R750', 'BMC', '7.10.70.00')"
        )
    )
    await session.execute(
        text(
            "INSERT INTO firmware_inventory (server_id, component, component_key, component_type, version, collected_at) "
            "VALUES (:s, 'BIOS', 'BIOS', 'bios', '1.13.2', :t), (:s, 'iDRAC', 'BMC', 'bmc', '7.10.70.00', :t), "
            "(:s, 'NIC 1', 'NIC', 'nic', '22.1', :t)"
        ),
        {"s": sid, "t": now},
    )
    await session.commit()
    result, effects = await in_app_tx(app_engine, lambda s, e: run_compliance(s, now, e))
    assert result.checked_servers == 1 and len(result.deviations) == 1
    [alert] = await alerts(session)
    assert (alert.rule, alert.component) == ("Firmware off baseline", "BIOS")
    assert "installed BIOS 1.13.2; approved 1.15.2" in alert.message
    assert kinds(effects) == [("opened", 0)]

    await in_app_tx(app_engine, lambda s, e: run_compliance(s, now, e))  # still off: no duplicate
    assert len(await alerts(session)) == 1

    await session.execute(text("UPDATE firmware_inventory SET version = '1.15.2' WHERE component = 'BIOS'"))
    await session.commit()
    result, _ = await in_app_tx(app_engine, lambda s, e: run_compliance(s, now, e))
    assert result.resolved == 1 and (await alerts(session))[0].state == "resolved"


# ------------------------------------------------------------------------------------------- escalation


async def test_critical_escalation_after_15_minutes_once(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid, other = world.server(0).id, world.server(1).id
    for s in (sid, other):
        await add_readings(session, s, "bmc_reachable", [(120, 0.0), (60, 0.0), (0, 0.0)], now)
        await evaluate(app_engine, s, now)
    acked = next(r for r in await alerts(session) if r.server_id == other)
    await session.execute(text("UPDATE alerts SET state = 'acknowledged' WHERE id = :a"), {"a": acked.id})
    await session.commit()

    count, _ = await in_app_tx(app_engine, lambda s, e: escalate_due(s, now + timedelta(minutes=14), e, 900))
    assert count == 0
    count, effects = await in_app_tx(
        app_engine, lambda s, e: escalate_due(s, now + timedelta(minutes=16), e, 900)
    )
    assert count == 1 and kinds(effects) == [("escalated", 1)] and changes(effects) == ["escalated"]
    [escalated] = await alerts(session, "a.escalated_at IS NOT NULL")
    assert escalated.server_id == sid
    count, _ = await in_app_tx(app_engine, lambda s, e: escalate_due(s, now + timedelta(minutes=30), e, 900))
    assert count == 0


async def test_escalation_counts_from_when_alert_became_critical(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    await add_readings(session, sid, "psu_health", [(0, 1.0)], now, component="PSU 1", status="Warning")
    await evaluate(app_engine, sid, now)
    later = now + timedelta(minutes=20)
    await add_readings(session, sid, "psu_health", [(-1200, 2.0)], now, component="PSU 1", status="Critical")
    await evaluate(app_engine, sid, later)
    count, _ = await in_app_tx(app_engine, lambda s, e: escalate_due(s, later + timedelta(minutes=5), e, 900))
    assert count == 0
    count, _ = await in_app_tx(
        app_engine, lambda s, e: escalate_due(s, later + timedelta(minutes=16), e, 900)
    )
    assert count == 1


async def test_store_resolve_logs_and_notifies_only_if_notified(
    world: World, session: AsyncSession, app_engine: AsyncEngine, now: datetime
) -> None:
    sid = world.server(0).id
    await add_readings(session, sid, "bmc_reachable", [(120, 0.0), (60, 0.0), (0, 0.0)], now)
    await evaluate(app_engine, sid, now)
    [alert] = await alerts(session)
    await session.execute(text("UPDATE alerts SET notified_at = now() WHERE id = :a"), {"a": alert.id})
    await session.commit()

    async def resolve(s: AsyncSession, e: Effects) -> None:
        row = await s.get(Alert, alert.id)
        assert row is not None
        await AlertStore(s, now, e).resolve(row, "test")

    _, effects = await in_app_tx(app_engine, resolve)
    assert kinds(effects) == [("resolved", 0)]
