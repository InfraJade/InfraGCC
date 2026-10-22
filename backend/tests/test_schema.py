"""Phase 1: schema, TimescaleDB objects, reference data, grants and seed."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app import seed
from tests.conftest import run_alembic

DESIGN_TABLES = {
    "sites",
    "rooms",
    "racks",
    "servers",
    "components",
    "collectors",
    "metric_definitions",
    "thresholds",
    "readings",
    "latest_readings",
    "health_status",
    "events",
    "alert_rules",
    "alerts",
    "maintenance_windows",
    "firmware_inventory",
    "firmware_baselines",
    "audit_log",
}


async def scalar(engine: AsyncEngine, sql: str) -> object:
    async with engine.connect() as conn:
        return (await conn.execute(text(sql))).scalar_one()


async def test_every_design_table_exists(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        rows = await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        tables = {r[0] for r in rows}
    assert tables >= DESIGN_TABLES


async def test_readings_is_a_one_day_hypertable_with_compression_and_retention(engine: AsyncEngine) -> None:
    interval = await scalar(
        engine,
        "SELECT time_interval FROM timescaledb_information.dimensions WHERE hypertable_name = 'readings'",
    )
    assert str(interval) == "1 day, 0:00:00"
    assert await scalar(
        engine,
        "SELECT compression_enabled FROM timescaledb_information.hypertables WHERE hypertable_name='readings'",
    )
    compress_after = await scalar(
        engine,
        "SELECT config->>'compress_after' FROM timescaledb_information.jobs "
        "WHERE proc_name = 'policy_compression' AND hypertable_name = 'readings'",
    )
    assert compress_after == "7 days"
    drop_after = await scalar(
        engine,
        "SELECT config->>'drop_after' FROM timescaledb_information.jobs "
        "WHERE proc_name = 'policy_retention' AND hypertable_name = 'readings'",
    )
    assert drop_after == "30 days"
    index = await scalar(
        engine, "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_readings_server_metric_time'"
    )
    assert '(server_id, metric_code, "time" DESC)' in str(index)


async def test_rollups_have_refresh_and_retention_policies(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text(
                """
                SELECT ca.view_name, j.proc_name, j.schedule_interval, j.config
                FROM timescaledb_information.continuous_aggregates ca
                JOIN timescaledb_information.jobs j ON j.hypertable_name = ca.materialization_hypertable_name
                """
            )
        )
        jobs = [(r.view_name, r.proc_name, str(r.schedule_interval), r.config) for r in rows]
    by_view: dict[str, dict[str, tuple[str, dict[str, str]]]] = {}
    for view, proc, schedule, config in jobs:
        by_view.setdefault(view, {})[proc] = (schedule, config)
    assert by_view["readings_5m"]["policy_refresh_continuous_aggregate"][0] == "0:05:00"
    assert by_view["readings_5m"]["policy_retention"][1]["drop_after"] == "395 days"
    assert by_view["readings_1h"]["policy_refresh_continuous_aggregate"][0] == "0:30:00"
    assert by_view["readings_1h"]["policy_retention"][1]["drop_after"] == "1095 days"


async def test_rollups_aggregate_avg_min_max(session: AsyncSession, engine: AsyncEngine) -> None:
    await seed.seed_topology(session)
    await session.execute(
        text(
            "INSERT INTO servers (site_id, bmc_host) VALUES ((SELECT id FROM sites WHERE code='PNQ1'), 'bmc-x')"
        )
    )
    await session.execute(
        text(
            """
            INSERT INTO readings (time, server_id, metric_code, component, value, status)
            SELECT '2026-01-01 10:00:00+00'::timestamptz + make_interval(mins => g), s.id, 1, '', 20 + g, 'OK'
            FROM generate_series(0, 9) g, servers s WHERE s.bmc_host = 'bmc-x'
            """
        )
    )
    await session.commit()
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("CALL refresh_continuous_aggregate('readings_5m', NULL, NULL)"))
        await conn.execute(text("CALL refresh_continuous_aggregate('readings_1h', NULL, NULL)"))
        five = (
            await conn.execute(
                text("SELECT avg_value, min_value, max_value, samples FROM readings_5m ORDER BY bucket")
            )
        ).all()
        hour = (
            await conn.execute(text("SELECT avg_value, min_value, max_value, samples FROM readings_1h"))
        ).one()
    assert [tuple(r) for r in five] == [(22.0, 20.0, 24.0, 5), (27.0, 25.0, 29.0, 5)]
    assert tuple(hour) == (24.5, 20.0, 29.0, 10)


async def test_reference_data_covers_all_twenty_parameters(engine: AsyncEngine) -> None:
    params = await scalar(
        engine, "SELECT array_agg(DISTINCT parameter_no ORDER BY parameter_no) FROM metric_definitions"
    )
    assert params == list(range(1, 21))
    # Every parameter that can alert has at least one built-in rule.
    uncovered = await scalar(
        engine,
        """
        SELECT count(DISTINCT md.parameter_no) FROM metric_definitions md
        WHERE NOT EXISTS (SELECT 1 FROM alert_rules r JOIN metric_definitions m2 ON m2.id = r.metric_code
                          WHERE m2.parameter_no = md.parameter_no)
        """,
    )
    assert uncovered == 0
    inlet = await scalar(
        engine,
        "SELECT warning || '/' || critical FROM thresholds t JOIN metric_definitions m ON m.id = t.metric_code "
        "WHERE m.code = 'inlet_temp_c' AND t.scope = 'global'",
    )
    assert inlet == "27/35"


async def _denied_as(engine: AsyncEngine, role: str, sql: str) -> bool:
    async with engine.connect() as conn:
        await conn.execute(text(f"SET ROLE {role}"))
        try:
            await conn.execute(text(sql))
        except DBAPIError as exc:
            return "permission denied" in str(exc)
        finally:
            await conn.rollback()
    return False


async def test_superset_role_reads_views_but_not_tables(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SET ROLE gcc_superset_ro"))
        for view in (
            "v_readings_5m",
            "v_readings_1h",
            "v_server_health",
            "v_alerts",
            "v_inventory",
            "v_firmware_compliance",
        ):
            await conn.execute(text(f"SELECT * FROM reporting.{view} LIMIT 1"))
        await conn.rollback()
    assert await _denied_as(engine, "gcc_superset_ro", "SELECT * FROM public.readings LIMIT 1")
    assert await _denied_as(engine, "gcc_superset_ro", "SELECT * FROM public.servers LIMIT 1")


async def test_ingest_role_may_only_touch_telemetry(engine: AsyncEngine) -> None:
    assert await _denied_as(engine, "gcc_ingest", "UPDATE servers SET rack_id = NULL")
    assert await _denied_as(engine, "gcc_ingest", "DELETE FROM readings")
    assert await _denied_as(engine, "gcc_ingest", "UPDATE alert_rules SET enabled = false")
    assert not await _denied_as(engine, "gcc_ingest", "UPDATE servers SET last_seen_at = now() WHERE false")


async def test_dev_seed_is_idempotent(session: AsyncSession, engine: AsyncEngine) -> None:
    await seed.seed_dev()
    await seed.seed_dev()
    counts = await scalar(
        engine,
        "SELECT (SELECT count(*) FROM sites) || '/' || (SELECT count(*) FROM rooms) || '/' || "
        "(SELECT count(*) FROM racks) || '/' || (SELECT count(*) FROM collectors)",
    )
    assert counts == "2/4/12/3"
    servers = await scalar(engine, "SELECT count(*) FROM servers")
    assert servers == 39
    # Every onboarded server sits inside its rack and has a collector at its own site.
    misplaced = await scalar(
        engine,
        """
        SELECT count(*) FROM servers s JOIN racks r ON r.id = s.rack_id JOIN rooms rm ON rm.id = r.room_id
        JOIN collectors c ON c.id = s.collector_id
        WHERE s.position_u + s.height_u - 1 > r.height_u OR rm.site_id <> s.site_id OR c.site_id <> s.site_id
        """,
    )
    assert misplaced == 0


async def test_migrations_downgrade_and_upgrade_cleanly(database_url: str, engine: AsyncEngine) -> None:
    await engine.dispose()
    await run_alembic(database_url, "downgrade", "base")
    tables = await scalar(
        engine,
        "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'",
    )
    assert tables == 0
    await run_alembic(database_url, "upgrade", "head")
    assert await scalar(engine, "SELECT count(*) FROM metric_definitions") == 27
