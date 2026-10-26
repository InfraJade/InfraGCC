"""Per-server evaluation of threshold, state and event rules.

Runs in the alert worker after each ingested batch (coalesced per server). Holds a transaction-scoped
advisory lock per server so two workers never evaluate the same server at once.
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertState, Health, RuleType, ServerStatus, Severity
from app.ingest.health import derive_health
from app.models import Alert, AlertRule, Component, LatestReading, MetricDefinition, Server
from app.services.alerts.effects import Effects
from app.services.alerts.maintenance import muted_server_ids
from app.services.alerts.rules import LoadedRule, load_rules
from app.services.alerts.store import AlertStore, Firing, server_key
from app.services.alerts.windows import Sample, Verdict, evaluate_window, lookback
from app.services.thresholds import BmcMode, Level, Limit, ThresholdResolver

log = logging.getLogger("gcc.alerts.evaluate")

EVAL_LOCK_NAMESPACE = 0x47434301  # "GCC" + 1: per-server evaluation lock
EVENT_WINDOW = timedelta(hours=24)

_HEALTH_LEVEL = {Health.OK: Level.OK, Health.WARNING: Level.WARNING, Health.CRITICAL: Level.CRITICAL}


def fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.0f}" if abs(value) >= 100 or value == int(value) else f"{value:.1f}"


def max_severity(a: Severity, b: Severity) -> Severity:
    return a if a.rank >= b.rank else b


def event_message_key(message_id: str | None, message: str) -> str:
    if message_id:
        return message_id[:128]
    return "msg:" + hashlib.sha1(message.encode(), usedforsecurity=False).hexdigest()[:12]


class ServerEvaluation:
    def __init__(
        self, session: AsyncSession, server: Server, now: datetime, effects: Effects, rules: list[LoadedRule]
    ) -> None:
        self.session = session
        self.server = server
        self.now = now
        self.store = AlertStore(session, now, effects)
        self.rules = rules
        self.muted = False
        self.active: dict[str, Alert] = {}
        self.capacity: float | None = None
        self.expected_links: dict[str, bool | None] = {}

    @property
    def name(self) -> str:
        return self.server.display_name

    def title(self, rule: LoadedRule, component: str) -> str:
        return f"{rule.rule.name}: {self.name}" + (f" ({component})" if component else "")

    async def run(self) -> None:
        sid = self.server.id
        self.muted = bool(await muted_server_ids(self.session, self.now, [sid]))
        alerts = await self.session.execute(
            select(Alert).where(Alert.server_id == sid, Alert.state != AlertState.RESOLVED.value)
        )
        self.active = {a.dedupe_key: a for a in alerts.scalars()}
        metric_rules = [
            r
            for r in self.rules
            if r.type in (RuleType.THRESHOLD.value, RuleType.STATE.value) and r.metric is not None
        ]
        if metric_rules:
            await self._metric_rules(metric_rules)
        for rule in self.rules:
            if rule.type == RuleType.EVENT.value and rule.metric is not None:
                await self._event_rule(rule)

    # ------------------------------------------------------------------------------------ metric rules

    async def _metric_rules(self, rules: list[LoadedRule]) -> None:
        sid = self.server.id
        since = self.now - max(
            lookback(r.rule.duration_s, r.metric.interval_s, r.cond_int("consecutive"))
            for r in rules
            if r.metric is not None
        )
        metric_ids = sorted({r.metric.id for r in rules if r.metric is not None})
        rows = await self.session.execute(
            text(
                "SELECT metric_code, component, time, value, status FROM readings "
                "WHERE server_id = :sid AND metric_code = ANY(:mids) AND time >= :since AND time <= :now "
                "ORDER BY time"
            ),
            {"sid": sid, "mids": metric_ids, "since": since, "now": self.now},
        )
        series: dict[int, dict[str, list[tuple[datetime, float | None, str | None]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for metric_code, component, t, value, status in rows:
            series[metric_code][component].append((t, value, status))

        resolver = await ThresholdResolver.load(self.session, self.server)
        await self._load_capacity()
        nics = await self.session.execute(
            select(Component.name, Component.expected_link_up).where(
                Component.server_id == sid, Component.type == "nic", Component.removed_at.is_(None)
            )
        )
        self.expected_links = dict(nics.all())

        for rule in rules:
            assert rule.metric is not None
            by_component = series.get(rule.metric.id, {})
            prefix = server_key(sid, rule.metric.id, "")
            components = set(by_component) | {
                a.component for k, a in self.active.items() if k.startswith(prefix) and a.rule_id == rule.id
            }
            for component in sorted(components):
                await self._metric_series(rule, component, by_component.get(component, []), resolver)

    async def _load_capacity(self) -> None:
        rows = await self.session.execute(
            select(MetricDefinition.code, LatestReading.value)
            .join(MetricDefinition, MetricDefinition.id == LatestReading.metric_code)
            .where(
                LatestReading.server_id == self.server.id,
                LatestReading.component == "",
                MetricDefinition.code.in_(["power_capacity_w", "power_limit_w"]),
            )
        )
        values = [v for _, v in rows if v is not None and v > 0]
        self.capacity = min(values) if values else None

    async def _metric_series(
        self,
        rule: LoadedRule,
        component: str,
        raw: Sequence[tuple[datetime, float | None, str | None]],
        resolver: ThresholdResolver,
    ) -> None:
        metric = rule.metric
        assert metric is not None
        key = server_key(self.server.id, metric.id, component)
        existing = self.active.get(key)
        if existing is not None and existing.rule_id != rule.id:
            return  # D15: one alert per server/metric/part; the rule that opened it owns it
        duration = rule.rule.duration_s
        consecutive = 0
        limit: Limit | None = None

        if rule.type == RuleType.THRESHOLD.value:
            mode = rule.condition.get("bmc_limits")
            bmc_mode: BmcMode | None = mode if mode in ("upper", "lower") else None
            limit = resolver.effective(metric.id, component, bmc_mode)
            if limit is None:
                return
            samples = [Sample(t, v, limit.level(v, self.capacity)) for t, v, _ in raw]
        else:
            if rule.cond_bool("outside_maintenance_only") and self.muted:
                return  # D16: e.g. "powered off" does not fire at all during maintenance
            consecutive = rule.cond_int("consecutive")
            not_expected = rule.cond_bool("expected_only") and not self.expected_links.get(component)
            samples = [
                Sample(t, v, Level.OK if not_expected else self._state_level(rule, metric.code, v, s))
                for t, v, s in raw
            ]
        verdict = evaluate_window(samples, self.now, duration, metric.interval_s, consecutive)

        if verdict.kind == "bad" and verdict.level is not None and verdict.latest is not None:
            if rule.type == RuleType.STATE.value and rule.condition.get("match") == "value":
                severity = rule.severity
            else:
                severity = max_severity(rule.severity, verdict.level.severity)
            latest_status = next((s for t, _, s in reversed(raw) if t == verdict.latest.time), None)
            await self.store.fire(
                Firing(
                    rule=rule.rule,
                    key=key,
                    severity=severity,
                    title=self.title(rule, component),
                    message=self._message(rule, component, verdict, limit, latest_status),
                    site_id=self.server.site_id,
                    server_id=self.server.id,
                    metric_code=metric.id,
                    component=component,
                    value=verdict.latest.value,
                    threshold=limit.limit_for(verdict.level) if limit is not None else None,
                    muted=self.muted,
                    seen_at=verdict.latest.time,
                ),
                existing,
            )
        elif verdict.kind == "good" and existing is not None:
            held = f" for {duration // 60} min" if duration >= 60 else ""
            await self.store.resolve(existing, f"Back to normal{held}.")

    @staticmethod
    def _state_level(rule: LoadedRule, code: str, value: float | None, status: str | None) -> Level | None:
        cond = rule.condition
        if cond.get("match") == "value":
            if value is None:
                return None
            return Level.WARNING if value == cond.get("equals") else Level.OK
        health = derive_health(code, value, status, expected_link_up=True)
        if health is Health.UNKNOWN:
            return None
        levels = cond.get("levels") or [Health.WARNING.value, Health.CRITICAL.value]
        if health.value not in levels:
            return Level.OK
        return _HEALTH_LEVEL[health]

    def _message(
        self, rule: LoadedRule, component: str, verdict: Verdict, limit: Limit | None, status: str | None
    ) -> str:
        metric = rule.metric
        assert metric is not None and verdict.latest is not None and verdict.level is not None
        what = f"{metric.name}{' ' + component if component else ''}"
        where = f"on {self.name}"
        value = verdict.latest.value
        held = rule.rule.duration_s
        lasting = f" for {held // 60} min" if held >= 60 else ""
        if limit is not None:
            bound = limit.limit_for(verdict.level)
            level = verdict.level.name.lower()
            src = "BMC" if limit.source == "bmc" else f"{limit.source} threshold"
            if limit.direction == "pct_of_capacity":
                pct = limit.measure(value, self.capacity) if value is not None else None
                return (
                    f"{what} {where} is {fmt(value)} {metric.unit}, {fmt(pct)} % of {fmt(self.capacity)} "
                    f"{metric.unit} capacity{lasting} ({level} above {fmt(bound)} %, {src})."
                )
            if limit.direction == "deviation_pct":
                dev = limit.measure(value) if value is not None else None
                return (
                    f"{what} {where} is {fmt(value)} {metric.unit}, {fmt(dev)} % from nominal{lasting} "
                    f"({level} beyond {fmt(bound)} %, {src})."
                )
            word = "below" if limit.direction == "below" else "above"
            return (
                f"{what} {where} is {fmt(value)} {metric.unit}{lasting}, {word} the {level} limit "
                f"{fmt(bound)} {metric.unit} ({src})."
            ).replace("  ", " ")
        consecutive = rule.cond_int("consecutive")
        if consecutive:
            return f"{what} {where}: {status or fmt(value)} for {consecutive} polls in a row."
        return f"{what} {where} is {status or fmt(value)}{lasting}."

    # ------------------------------------------------------------------------------------ event rules

    async def _event_rule(self, rule: LoadedRule) -> None:
        metric = rule.metric
        assert metric is not None
        sid = self.server.id
        severities = rule.condition.get("severities") or [Severity.CRITICAL.value]
        rows = (
            await self.session.execute(
                text(
                    "SELECT time, severity, message, message_id, created_at FROM events "
                    "WHERE server_id = :sid AND severity = ANY(:sev) AND time > :since ORDER BY time"
                ),
                {"sid": sid, "sev": list(severities), "since": self.now - EVENT_WINDOW},
            )
        ).all()
        if not rows:
            return
        marks: dict[str, Any] = dict(
            (
                await self.session.execute(
                    text(
                        "SELECT dedupe_key, max(resolved_at) FROM alerts "
                        "WHERE server_id = :sid AND rule_id = :rid AND state = 'resolved' GROUP BY dedupe_key"
                    ),
                    {"sid": sid, "rid": rule.id},
                )
            ).all()
        )
        groups: dict[str, list[Any]] = defaultdict(list)
        for row in rows:
            groups[event_message_key(row.message_id, row.message)].append(row)
        for msg_key, events in groups.items():
            key = server_key(sid, metric.id, msg_key)
            existing = self.active.get(key)
            if existing is not None and existing.rule_id != rule.id:
                continue
            mark = marks.get(key)
            # Entries already covered by an alert someone resolved do not reopen it (D17).
            fresh = [e for e in events if mark is None or e.created_at > mark]
            if not fresh:
                continue
            last = fresh[-1]
            count = len(fresh)
            await self.store.fire(
                Firing(
                    rule=rule.rule,
                    key=key,
                    severity=rule.severity,
                    title=self.title(rule, msg_key),
                    message=f"{last.message} ({count} occurrence{'s' if count != 1 else ''} on {self.name}).",
                    site_id=self.server.site_id,
                    server_id=sid,
                    metric_code=metric.id,
                    component=msg_key,
                    muted=self.muted,
                    seen_at=last.time,
                    occurrences=count,
                ),
                existing,
            )


async def evaluate_server(session: AsyncSession, server_id: int, now: datetime, effects: Effects) -> bool:
    """Evaluate one server inside the caller's transaction. Returns False if the server is gone."""
    server = await session.get(Server, server_id)
    if server is None or server.status == ServerStatus.DECOMMISSIONED.value:
        return False
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :id)"), {"ns": EVAL_LOCK_NAMESPACE, "id": server_id}
    )
    rules = await load_rules(session, RuleType.THRESHOLD, RuleType.STATE, RuleType.EVENT)
    await ServerEvaluation(session, server, now, effects, rules).run()
    return True


async def resolve_stale_events(session: AsyncSession, now: datetime, effects: Effects) -> int:
    """D17: event alerts resolve 24 h after their last occurrence."""
    rows = await session.execute(
        select(Alert)
        .join(AlertRule, AlertRule.id == Alert.rule_id)
        .where(
            Alert.state != AlertState.RESOLVED.value,
            Alert.last_seen_at < now - EVENT_WINDOW,
            AlertRule.rule_type == RuleType.EVENT.value,
        )
    )
    store = AlertStore(session, now, effects)
    count = 0
    for alert in rows.scalars():
        await store.resolve(alert, "No new occurrence for 24 hours.")
        count += 1
    return count
