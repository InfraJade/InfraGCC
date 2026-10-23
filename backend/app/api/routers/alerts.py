"""Alerts: list and detail for everyone; acknowledge, comment and resolve for NOC operators and up.

Every action writes an `alert_activity` row (who, when, from/to state, note) and an audit entry, then
publishes an `AlertMessage` so other open pages update.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.api.deps import PageDep, SessionDep, publish_alert
from app.core import audit
from app.core.enums import AlertState, Severity
from app.core.pagination import paginate
from app.core.problems import Problem
from app.core.security import OperatorUser, Principal, ViewerUser, not_found
from app.models import Alert, AlertActivity, AlertRule
from app.schemas.alerts import AckIn, AlertDetail, AlertPage, CommentIn, ResolveIn
from app.services.query import alerts as queries
from app.services.query.common import now_utc

router = APIRouter(tags=["alerts"])


@router.get("/alerts", response_model=AlertPage, summary="Alerts with filters (newest first)")
async def list_alerts(
    principal: ViewerUser,
    session: SessionDep,
    page: PageDep,
    state: Annotated[list[AlertState] | None, Query(description="Repeatable")] = None,
    severity: Annotated[list[Severity] | None, Query(description="Repeatable")] = None,
    site_id: Annotated[int | None, Query()] = None,
    server_id: Annotated[int | None, Query()] = None,
    rule_id: Annotated[int | None, Query()] = None,
    muted: Annotated[bool | None, Query()] = None,
    opened_from: Annotated[datetime | None, Query(alias="from", description="Opened at or after")] = None,
    opened_to: Annotated[datetime | None, Query(alias="to", description="Opened before")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> AlertPage:
    filters = queries.AlertFilters(
        states=state or [],
        severities=severity or [],
        site_id=site_id,
        server_id=server_id,
        rule_id=rule_id,
        muted=muted,
        opened_from=opened_from,
        opened_to=opened_to,
        q=q,
    )
    stmt, keys = queries.alerts_list_select(principal, filters)
    rows, next_cursor = await paginate(session, stmt, keys, page, "alerts")
    return AlertPage(items=queries.alerts_from_rows(rows), next_cursor=next_cursor)


@router.get("/alerts/{alert_id}", response_model=AlertDetail, summary="One alert with its activity")
async def get_alert(alert_id: int, principal: ViewerUser, session: SessionDep) -> AlertDetail:
    return await queries.alert_detail(session, principal, alert_id)


async def _locked_alert(session: SessionDep, principal: Principal, alert_id: int) -> Alert:
    alert = (
        await session.execute(select(Alert).where(Alert.id == alert_id).with_for_update())
    ).scalar_one_or_none()
    if alert is None or not principal.can_see_site(alert.site_id):
        raise not_found("Alert")
    return alert


def _activity(
    alert: Alert, principal: Principal, action: str, to_state: str | None, note: str | None
) -> AlertActivity:
    return AlertActivity(
        alert_id=alert.id,
        actor=principal.display_name,
        actor_sub=principal.sub,
        action=action,
        from_state=alert.state if to_state else None,
        to_state=to_state,
        note=note,
        details={},
    )


@router.post("/alerts/{alert_id}/ack", response_model=AlertDetail, summary="Acknowledge an open alert")
async def acknowledge(
    alert_id: int, principal: OperatorUser, session: SessionDep, request: Request, body: AckIn | None = None
) -> AlertDetail:
    note = body.note if body else None
    alert = await _locked_alert(session, principal, alert_id)
    if alert.state != AlertState.OPEN.value:
        raise Problem(409, f"The alert is already {alert.state}.", state=alert.state)
    session.add(_activity(alert, principal, "acknowledged", AlertState.ACKNOWLEDGED.value, note))
    before = {"state": alert.state}
    alert.state = AlertState.ACKNOWLEDGED.value
    alert.acked_at = now_utc()
    alert.acked_by = principal.display_name
    audit.record(
        session,
        principal=principal,
        action="alert.ack",
        object_type="alert",
        object_id=alert.id,
        before=before,
        after={"state": alert.state, "note": note},
        request=request,
    )
    await session.commit()
    await publish_alert(alert, "acknowledged")
    return await queries.alert_detail(session, principal, alert.id)


@router.post("/alerts/{alert_id}/comments", response_model=AlertDetail, summary="Comment on an alert")
async def comment(
    alert_id: int, body: CommentIn, principal: OperatorUser, session: SessionDep, request: Request
) -> AlertDetail:
    alert = await _locked_alert(session, principal, alert_id)
    session.add(_activity(alert, principal, "comment", None, body.note))
    audit.record(
        session,
        principal=principal,
        action="alert.comment",
        object_type="alert",
        object_id=alert.id,
        after={"note": body.note},
        request=request,
    )
    await session.commit()
    await publish_alert(alert, "updated")
    return await queries.alert_detail(session, principal, alert.id)


@router.post(
    "/alerts/{alert_id}/resolve",
    response_model=AlertDetail,
    summary="Resolve an event or compliance alert by hand (others resolve when readings recover)",
)
async def resolve(
    alert_id: int,
    principal: OperatorUser,
    session: SessionDep,
    request: Request,
    body: ResolveIn | None = None,
) -> AlertDetail:
    note = body.note if body else None
    alert = await _locked_alert(session, principal, alert_id)
    rule = await session.get(AlertRule, alert.rule_id)
    if alert.state == AlertState.RESOLVED.value:
        raise Problem(409, "The alert is already resolved.", state=alert.state)
    if rule is None or rule.rule_type not in queries.MANUALLY_RESOLVABLE:
        raise Problem(
            409,
            "Only event and compliance alerts can be resolved by hand; "
            "this one resolves when the readings recover.",
        )
    session.add(_activity(alert, principal, "resolved", AlertState.RESOLVED.value, note))
    before = {"state": alert.state}
    alert.state = AlertState.RESOLVED.value
    alert.resolved_at = now_utc()
    alert.resolved_by = principal.display_name
    audit.record(
        session,
        principal=principal,
        action="alert.resolve",
        object_type="alert",
        object_id=alert.id,
        before=before,
        after={"state": alert.state, "note": note},
        request=request,
    )
    await session.commit()
    await publish_alert(alert, "resolved")
    return await queries.alert_detail(session, principal, alert.id)
