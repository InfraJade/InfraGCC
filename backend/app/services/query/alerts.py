"""Alert list and detail queries."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AlertState, RuleType, Severity
from app.core.pagination import AnyRow, AnySelect, SortKey
from app.core.security import Principal, not_found
from app.models import Alert, AlertActivity, AlertRule, Collector, MetricDefinition, Server, Site
from app.schemas.alerts import AlertActivityOut, AlertDetail, AlertOut, AlertRuleRef, CollectorBrief
from app.schemas.common import ServerRef, SiteRef
from app.services.query.common import like_pattern

MANUALLY_RESOLVABLE = {RuleType.EVENT.value, RuleType.COMPLIANCE.value}


def alert_select() -> AnySelect:
    return (
        select(Alert, AlertRule, Server, Site, Collector, MetricDefinition.code)
        .join(AlertRule, AlertRule.id == Alert.rule_id)
        .outerjoin(Server, Server.id == Alert.server_id)
        .outerjoin(Site, Site.id == Alert.site_id)
        .outerjoin(Collector, Collector.id == Alert.collector_id)
        .outerjoin(MetricDefinition, MetricDefinition.id == Alert.metric_code)
    )


def alert_from_row(row: AnyRow) -> AlertOut:
    alert: Alert = row[0]
    rule: AlertRule = row[1]
    server: Server | None = row[2]
    site: Site | None = row[3]
    collector: Collector | None = row[4]
    return AlertOut(
        id=alert.id,
        rule=AlertRuleRef(id=rule.id, name=rule.name, rule_type=rule.rule_type),
        server=ServerRef(id=server.id, name=server.name or server.bmc_host, bmc_host=server.bmc_host)
        if server
        else None,
        site=SiteRef(id=site.id, code=site.code, name=site.name) if site else None,
        collector=CollectorBrief(id=collector.id, name=collector.name) if collector else None,
        metric=row[5],
        component=alert.component,
        state=alert.state,
        severity=alert.severity,
        title=alert.title,
        message=alert.message,
        value=alert.value,
        threshold=alert.threshold,
        muted=alert.muted,
        occurrences=alert.occurrences,
        opened_at=alert.opened_at,
        last_seen_at=alert.last_seen_at,
        acked_at=alert.acked_at,
        acked_by=alert.acked_by,
        resolved_at=alert.resolved_at,
        resolved_by=alert.resolved_by,
        notified_at=alert.notified_at,
        escalated_at=alert.escalated_at,
        manually_resolvable=rule.rule_type in MANUALLY_RESOLVABLE,
    )


def alerts_from_rows(rows: Sequence[AnyRow]) -> list[AlertOut]:
    return [alert_from_row(r) for r in rows]


@dataclass(frozen=True)
class AlertFilters:
    states: list[AlertState] = field(default_factory=list)
    severities: list[Severity] = field(default_factory=list)
    site_id: int | None = None
    server_id: int | None = None
    rule_id: int | None = None
    muted: bool | None = None
    opened_from: datetime | None = None
    opened_to: datetime | None = None
    q: str | None = None


def alerts_list_select(principal: Principal, f: AlertFilters) -> tuple[AnySelect, list[SortKey]]:
    stmt = alert_select().where(principal.site_filter(Alert.site_id))
    if f.states:
        stmt = stmt.where(Alert.state.in_([s.value for s in f.states]))
    if f.severities:
        stmt = stmt.where(Alert.severity.in_([s.value for s in f.severities]))
    if f.site_id is not None:
        stmt = stmt.where(Alert.site_id == f.site_id)
    if f.server_id is not None:
        stmt = stmt.where(Alert.server_id == f.server_id)
    if f.rule_id is not None:
        stmt = stmt.where(Alert.rule_id == f.rule_id)
    if f.muted is not None:
        stmt = stmt.where(Alert.muted.is_(f.muted))
    if f.opened_from is not None:
        stmt = stmt.where(Alert.opened_at >= f.opened_from)
    if f.opened_to is not None:
        stmt = stmt.where(Alert.opened_at < f.opened_to)
    if f.q:
        pattern = like_pattern(f.q.strip())
        stmt = stmt.where(
            or_(
                Alert.title.ilike(pattern),
                Alert.message.ilike(pattern),
                Alert.component.ilike(pattern),
                Server.name.ilike(pattern),
                Server.bmc_host.ilike(pattern),
            )
        )
    return stmt, [SortKey(Alert.opened_at, True), SortKey(Alert.id, True)]


async def alert_detail(session: AsyncSession, principal: Principal, alert_id: int) -> AlertDetail:
    row = (await session.execute(alert_select().where(Alert.id == alert_id))).first()
    if row is None or not principal.can_see_site(row[0].site_id):
        raise not_found("Alert")
    activity = (
        await session.execute(
            select(AlertActivity)
            .where(AlertActivity.alert_id == alert_id)
            .order_by(AlertActivity.time, AlertActivity.id)
        )
    ).scalars()
    return AlertDetail(
        **alert_from_row(row).model_dump(),
        activity=[AlertActivityOut.model_validate(a) for a in activity],
    )
