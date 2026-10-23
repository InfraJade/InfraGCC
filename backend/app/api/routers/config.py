"""Alerting configuration: alert rules, thresholds and alert routes.

Everyone may read rules and thresholds (they explain why an alert fired); only platform admins change
them. Alert routes hold contact details, so they are platform-admin only, and their targets are stored
encrypted and shown only as a masked hint.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Query, Request, Response, status
from sqlalchemy import delete, func, or_, select

from app.api.deps import PageDep, SessionDep, commit_or_409, flush_or_409
from app.core import audit
from app.core.config import get_settings
from app.core.crypto import encrypt, mask_target
from app.core.enums import MetricType, RouteChannel, RuleType, ThresholdScope
from app.core.pagination import AnySelect, SortKey, paginate
from app.core.problems import Problem
from app.core.security import AdminUser, Principal, ViewerUser, ensure_unrestricted, not_found
from app.models import Alert, AlertRoute, AlertRule, MetricDefinition, Server, Site, Threshold
from app.schemas.admin import (
    AlertRouteCreate,
    AlertRouteOut,
    AlertRoutePage,
    AlertRouteUpdate,
    AlertRuleBulkIn,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRulePage,
    AlertRuleUpdate,
    ThresholdBulkIn,
    ThresholdIn,
    ThresholdOut,
    ThresholdPage,
    ThresholdUpdate,
)
from app.services.query.common import metric_or_422
from app.services.query.limits import bmc_limits, effective_limits
from app.services.query.servers import get_visible_server

router = APIRouter(tags=["alerting config"])

# Which metric types each rule type can watch.
_RULE_METRIC_TYPES: dict[RuleType, set[str]] = {
    RuleType.THRESHOLD: {MetricType.GAUGE.value},
    RuleType.STATE: {MetricType.STATE.value},
    RuleType.EVENT: {MetricType.EVENT.value},
    RuleType.COMPLIANCE: {MetricType.VERSION.value},
}


# ---------------------------------------------------------------------------------------- alert rules


def _rule_stmt() -> AnySelect:
    return select(AlertRule, MetricDefinition.code).outerjoin(
        MetricDefinition, MetricDefinition.id == AlertRule.metric_code
    )


def _rule_out(row: Any) -> AlertRuleOut:
    rule: AlertRule = row[0]
    return AlertRuleOut(
        id=rule.id,
        name=rule.name,
        description=rule.description,
        rule_type=rule.rule_type,
        metric=row[1],
        condition=rule.condition,
        duration_s=rule.duration_s,
        severity=rule.severity,
        route=rule.route,
        enabled=rule.enabled,
        builtin=rule.builtin,
        updated_by=rule.updated_by,
        updated_at=rule.updated_at,
    )


async def _rule_by_id(session: SessionDep, rule_id: int) -> AlertRuleOut:
    row = (await session.execute(_rule_stmt().where(AlertRule.id == rule_id))).first()
    if row is None:
        raise not_found("Alert rule")
    return _rule_out(row)


@router.get("/alert-rules", response_model=AlertRulePage, summary="Alert rules")
async def list_rules(
    principal: ViewerUser,
    session: SessionDep,
    page: PageDep,
    rule_type: Annotated[RuleType | None, Query()] = None,
    metric: Annotated[str | None, Query(max_length=48)] = None,
    enabled: Annotated[bool | None, Query()] = None,
) -> AlertRulePage:
    stmt = _rule_stmt()
    if rule_type is not None:
        stmt = stmt.where(AlertRule.rule_type == rule_type.value)
    if metric:
        stmt = stmt.where(MetricDefinition.code == metric)
    if enabled is not None:
        stmt = stmt.where(AlertRule.enabled.is_(enabled))
    rows, next_cursor = await paginate(
        session, stmt, [SortKey(AlertRule.name), SortKey(AlertRule.id)], page, "rules"
    )
    return AlertRulePage(items=[_rule_out(r) for r in rows], next_cursor=next_cursor)


@router.get("/alert-rules/{rule_id}", response_model=AlertRuleOut, summary="One alert rule")
async def get_rule(rule_id: int, principal: ViewerUser, session: SessionDep) -> AlertRuleOut:
    return await _rule_by_id(session, rule_id)


@router.post(
    "/alert-rules",
    response_model=AlertRuleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a custom rule",
)
async def create_rule(
    body: AlertRuleCreate, principal: AdminUser, session: SessionDep, request: Request
) -> AlertRuleOut:
    ensure_unrestricted(principal, "An alert rule")
    metric_id: int | None = None
    if body.rule_type == RuleType.MISSING_DATA:
        if body.metric is not None:
            raise Problem(422, "Missing-data rules do not take a metric.")
    else:
        if body.metric is None:
            raise Problem(422, f"A {body.rule_type.value} rule needs a metric.")
        info = await metric_or_422(session, body.metric)
        if info.type not in _RULE_METRIC_TYPES[body.rule_type]:
            raise Problem(422, f"A {body.rule_type.value} rule cannot watch {info.code} ({info.type}).")
        metric_id = info.id
    rule = AlertRule(
        name=body.name,
        description=body.description,
        rule_type=body.rule_type.value,
        metric_code=metric_id,
        condition=body.condition,
        duration_s=body.duration_s,
        severity=body.severity.value,
        route=body.route,
        enabled=body.enabled,
        builtin=False,
        updated_by=principal.display_name,
    )
    session.add(rule)
    await flush_or_409(session, f"A rule named {body.name!r} already exists.")
    audit.record(
        session,
        principal=principal,
        action="alert_rule.create",
        object_type="alert_rule",
        object_id=rule.id,
        after=audit.snapshot(rule),
        request=request,
    )
    await session.commit()
    return await _rule_by_id(session, rule.id)


def _apply_rule(rule: AlertRule, body: AlertRuleUpdate, principal: Principal) -> None:
    for key, value in body.model_dump(exclude_unset=True, exclude={"id"}).items():
        if value is None:
            raise Problem(422, f"{key} cannot be null.")
        setattr(rule, key, value.value if hasattr(value, "value") else value)
    rule.updated_by = principal.display_name


async def _update_rule(
    session: SessionDep, principal: Principal, request: Request, rule_id: int, body: AlertRuleUpdate
) -> None:
    rule = await session.get(AlertRule, rule_id)
    if rule is None:
        raise not_found("Alert rule")
    before = audit.snapshot(rule)
    _apply_rule(rule, body, principal)
    await flush_or_409(session, "Another rule already has that name.")
    b, a = audit.changed(before, audit.snapshot(rule))
    audit.record(
        session,
        principal=principal,
        action="alert_rule.update",
        object_type="alert_rule",
        object_id=rule.id,
        before=b,
        after=a,
        request=request,
    )


@router.put("/alert-rules/{rule_id}", response_model=AlertRuleOut, summary="Change one rule")
async def update_rule(
    rule_id: int, body: AlertRuleUpdate, principal: AdminUser, session: SessionDep, request: Request
) -> AlertRuleOut:
    ensure_unrestricted(principal, "An alert rule")
    await _update_rule(session, principal, request, rule_id, body)
    await commit_or_409(session, "Another rule already has that name.")
    return await _rule_by_id(session, rule_id)


@router.put(
    "/alert-rules", response_model=AlertRulePage, summary="Change several rules at once (all or nothing)"
)
async def update_rules(
    body: AlertRuleBulkIn, principal: AdminUser, session: SessionDep, request: Request
) -> AlertRulePage:
    ensure_unrestricted(principal, "An alert rule")
    for item in body.items:
        await _update_rule(session, principal, request, item.id, item)
    await commit_or_409(session, "Another rule already has that name.")
    ids = [i.id for i in body.items]
    rows = (
        await session.execute(
            _rule_stmt().where(AlertRule.id.in_(ids)).order_by(AlertRule.name, AlertRule.id)
        )
    ).all()
    return AlertRulePage(items=[_rule_out(r) for r in rows])


@router.delete(
    "/alert-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a custom rule"
)
async def delete_rule(rule_id: int, principal: AdminUser, session: SessionDep, request: Request) -> Response:
    ensure_unrestricted(principal, "An alert rule")
    rule = await session.get(AlertRule, rule_id)
    if rule is None:
        raise not_found("Alert rule")
    if rule.builtin:
        raise Problem(409, "Built-in rules cannot be deleted; disable them instead.")
    used = (
        await session.execute(select(func.count()).select_from(Alert).where(Alert.rule_id == rule.id))
    ).scalar_one()
    if used:
        raise Problem(
            409, f"{used} alerts were raised by this rule; disable it instead to keep their history."
        )
    audit.record(
        session,
        principal=principal,
        action="alert_rule.delete",
        object_type="alert_rule",
        object_id=rule.id,
        before=audit.snapshot(rule),
        request=request,
    )
    await session.execute(delete(AlertRule).where(AlertRule.id == rule.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------------------------------- thresholds


def _threshold_stmt(principal: Principal) -> AnySelect:
    """Thresholds the user may see: global and model rows, plus site/server rows in their sites."""
    return (
        select(Threshold, MetricDefinition)
        .join(MetricDefinition, MetricDefinition.id == Threshold.metric_code)
        .outerjoin(Server, Server.id == Threshold.server_id)
        .where(
            principal.site_filter(Threshold.site_id, include_global=True),
            principal.site_filter(Server.site_id, include_global=True),
        )
    )


def _threshold_out(row: Any) -> ThresholdOut:
    t: Threshold = row[0]
    md: MetricDefinition = row[1]
    return ThresholdOut(
        id=t.id,
        metric=md.code,
        metric_name=md.name,
        unit=md.unit,
        scope=t.scope,
        site_id=t.site_id,
        server_id=t.server_id,
        vendor=t.vendor,
        model=t.model,
        direction=t.direction,
        warning=t.warning,
        critical=t.critical,
        nominal=t.nominal,
        updated_by=t.updated_by,
        updated_at=t.updated_at,
    )


@router.get(
    "/thresholds",
    response_model=ThresholdPage,
    summary="Thresholds; with server_id: those that apply to it, its BMC limits and effective limits",
)
async def list_thresholds(
    principal: ViewerUser,
    session: SessionDep,
    page: PageDep,
    metric: Annotated[str | None, Query(max_length=48)] = None,
    scope: Annotated[ThresholdScope | None, Query()] = None,
    site_id: Annotated[int | None, Query()] = None,
    server_id: Annotated[int | None, Query()] = None,
    model: Annotated[str | None, Query(max_length=128)] = None,
) -> ThresholdPage:
    stmt = _threshold_stmt(principal)
    server: Server | None = None
    if server_id is not None:
        server = await get_visible_server(session, principal, server_id)
        stmt = stmt.where(
            or_(
                Threshold.scope == ThresholdScope.GLOBAL.value,
                (Threshold.scope == ThresholdScope.SITE.value) & (Threshold.site_id == server.site_id),
                (Threshold.scope == ThresholdScope.SERVER.value) & (Threshold.server_id == server.id),
                (Threshold.scope == ThresholdScope.MODEL.value)
                & (Threshold.model == server.model)
                & (Threshold.vendor.is_(None) | (Threshold.vendor == server.vendor)),
            )
        )
    if metric:
        stmt = stmt.where(MetricDefinition.code == metric)
    if scope is not None:
        stmt = stmt.where(Threshold.scope == scope.value)
    if site_id is not None:
        stmt = stmt.where(Threshold.site_id == site_id)
    if model:
        stmt = stmt.where(Threshold.model == model)
    rows, next_cursor = await paginate(
        session,
        stmt,
        [SortKey(Threshold.metric_code), SortKey(Threshold.scope), SortKey(Threshold.id)],
        page,
        "thresholds",
    )
    result = ThresholdPage(items=[_threshold_out(r) for r in rows], next_cursor=next_cursor)
    if server is not None:
        result.bmc_limits = await bmc_limits(session, server.id)
        result.effective = await effective_limits(session, server)
    return result


async def _check_threshold_target(
    session: SessionDep, principal: Principal, scope: str, site_id: int | None, server_id: int | None
) -> None:
    if scope in (ThresholdScope.GLOBAL.value, ThresholdScope.MODEL.value):
        ensure_unrestricted(principal, f"A {scope} threshold")
    elif scope == ThresholdScope.SITE.value:
        site = await session.get(Site, site_id)
        if site is None or not principal.can_see_site(site.id):
            raise Problem(422, "Unknown site.")
    else:
        assert server_id is not None
        server = await session.get(Server, server_id)
        if server is None or not principal.can_see_site(server.site_id):
            raise Problem(422, "Unknown server.")


async def _threshold_by_id(session: SessionDep, principal: Principal, threshold_id: int) -> ThresholdOut:
    row = (await session.execute(_threshold_stmt(principal).where(Threshold.id == threshold_id))).first()
    if row is None:
        raise not_found("Threshold")
    return _threshold_out(row)


async def _upsert_threshold(
    session: SessionDep, principal: Principal, request: Request, body: ThresholdIn, *, create_only: bool
) -> Threshold:
    info = await metric_or_422(session, body.metric)
    if info.type != MetricType.GAUGE.value:
        raise Problem(422, f"{info.code} is a {info.type} metric; thresholds apply to numeric readings only.")
    await _check_threshold_target(session, principal, body.scope.value, body.site_id, body.server_id)
    existing = (
        await session.execute(
            select(Threshold).where(
                Threshold.metric_code == info.id,
                Threshold.scope == body.scope.value,
                func.coalesce(Threshold.site_id, 0) == (body.site_id or 0),
                func.coalesce(Threshold.server_id, 0) == (body.server_id or 0),
                func.coalesce(Threshold.vendor, "") == (body.vendor or ""),
                func.coalesce(Threshold.model, "") == (body.model or ""),
            )
        )
    ).scalar_one_or_none()
    if existing is not None and create_only:
        raise Problem(409, "A threshold for that metric and scope already exists.", threshold_id=existing.id)
    limits = {
        "direction": body.direction.value,
        "warning": body.warning,
        "critical": body.critical,
        "nominal": body.nominal,
    }
    if existing is None:
        threshold = Threshold(
            metric_code=info.id,
            scope=body.scope.value,
            site_id=body.site_id,
            server_id=body.server_id,
            vendor=body.vendor,
            model=body.model,
            updated_by=principal.display_name,
            **limits,
        )
        session.add(threshold)
        await flush_or_409(session, "A threshold for that metric and scope already exists.")
        audit.record(
            session,
            principal=principal,
            action="threshold.create",
            object_type="threshold",
            object_id=threshold.id,
            after=audit.snapshot(threshold),
            request=request,
        )
        return threshold
    before = audit.snapshot(existing)
    for key, value in limits.items():
        setattr(existing, key, value)
    existing.updated_by = principal.display_name
    await flush_or_409(session, "Threshold update conflicts with another row.")
    b, a = audit.changed(before, audit.snapshot(existing))
    audit.record(
        session,
        principal=principal,
        action="threshold.update",
        object_type="threshold",
        object_id=existing.id,
        before=b,
        after=a,
        request=request,
    )
    return existing


@router.post(
    "/thresholds", response_model=ThresholdOut, status_code=status.HTTP_201_CREATED, summary="Add an override"
)
async def create_threshold(
    body: ThresholdIn, principal: AdminUser, session: SessionDep, request: Request
) -> ThresholdOut:
    threshold = await _upsert_threshold(session, principal, request, body, create_only=True)
    await session.commit()
    return await _threshold_by_id(session, principal, threshold.id)


@router.put(
    "/thresholds",
    response_model=ThresholdPage,
    summary="Create or change several thresholds (all or nothing)",
)
async def upsert_thresholds(
    body: ThresholdBulkIn, principal: AdminUser, session: SessionDep, request: Request
) -> ThresholdPage:
    ids = [
        (await _upsert_threshold(session, principal, request, item, create_only=False)).id
        for item in body.items
    ]
    await session.commit()
    rows = (
        await session.execute(_threshold_stmt(principal).where(Threshold.id.in_(ids)).order_by(Threshold.id))
    ).all()
    return ThresholdPage(items=[_threshold_out(r) for r in rows])


async def _visible_threshold(session: SessionDep, principal: Principal, threshold_id: int) -> Threshold:
    row = (await session.execute(_threshold_stmt(principal).where(Threshold.id == threshold_id))).first()
    if row is None:
        raise not_found("Threshold")
    threshold: Threshold = row[0]
    await _check_threshold_target(session, principal, threshold.scope, threshold.site_id, threshold.server_id)
    return threshold


@router.put(
    "/thresholds/{threshold_id}", response_model=ThresholdOut, summary="Change one threshold's limits"
)
async def update_threshold(
    threshold_id: int, body: ThresholdUpdate, principal: AdminUser, session: SessionDep, request: Request
) -> ThresholdOut:
    threshold = await _visible_threshold(session, principal, threshold_id)
    before = audit.snapshot(threshold)
    threshold.direction = body.direction.value
    threshold.warning = body.warning
    threshold.critical = body.critical
    threshold.nominal = body.nominal
    threshold.updated_by = principal.display_name
    await flush_or_409(session, "Threshold update conflicts with another row.")
    b, a = audit.changed(before, audit.snapshot(threshold))
    audit.record(
        session,
        principal=principal,
        action="threshold.update",
        object_type="threshold",
        object_id=threshold.id,
        before=b,
        after=a,
        request=request,
    )
    await session.commit()
    return await _threshold_by_id(session, principal, threshold.id)


@router.delete(
    "/thresholds/{threshold_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an override"
)
async def delete_threshold(
    threshold_id: int, principal: AdminUser, session: SessionDep, request: Request
) -> Response:
    threshold = await _visible_threshold(session, principal, threshold_id)
    if threshold.scope == ThresholdScope.GLOBAL.value:
        raise Problem(409, "Global defaults can be changed but not deleted.")
    audit.record(
        session,
        principal=principal,
        action="threshold.delete",
        object_type="threshold",
        object_id=threshold.id,
        before=audit.snapshot(threshold),
        request=request,
    )
    await session.execute(delete(Threshold).where(Threshold.id == threshold.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------------------- alert routes


def _normalize_target(channel: RouteChannel, target: str) -> str:
    target = target.strip()
    if channel == RouteChannel.EMAIL:
        addresses = [a.strip() for a in re.split(r"[,;\s]+", target) if a.strip()]
        if not addresses:
            raise Problem(422, "Give at least one email address.")
        try:
            return ", ".join(validate_email(a, check_deliverability=False).normalized for a in addresses)
        except EmailNotValidError as exc:
            raise Problem(422, f"Invalid email address: {exc}") from exc
    allowed = ("https://",) if get_settings().app_env == "prod" else ("https://", "http://")
    if not target.startswith(allowed) or " " in target:
        raise Problem(422, "The Teams target must be an incoming-webhook URL (https://…).")
    return target


def _route_stmt(principal: Principal) -> AnySelect:
    return select(AlertRoute).where(principal.site_filter(AlertRoute.site_id, include_global=True))


async def _visible_route(session: SessionDep, principal: Principal, route_id: int) -> AlertRoute:
    route: AlertRoute | None = (
        await session.execute(_route_stmt(principal).where(AlertRoute.id == route_id))
    ).scalar_one_or_none()
    if route is None:
        raise not_found("Alert route")
    return route


async def _check_route_site(session: SessionDep, principal: Principal, site_id: int | None) -> None:
    if site_id is None:
        ensure_unrestricted(principal, "A route for all sites")
        return
    site = await session.get(Site, site_id)
    if site is None or not principal.can_see_site(site.id):
        raise Problem(422, "Unknown site.")


@router.get("/alert-routes", response_model=AlertRoutePage, summary="Where alerts are sent")
async def list_routes(
    principal: AdminUser,
    session: SessionDep,
    page: PageDep,
    site_id: Annotated[int | None, Query()] = None,
    channel: Annotated[RouteChannel | None, Query()] = None,
) -> AlertRoutePage:
    stmt = _route_stmt(principal)
    if site_id is not None:
        stmt = stmt.where(AlertRoute.site_id == site_id)
    if channel is not None:
        stmt = stmt.where(AlertRoute.channel == channel.value)
    rows, next_cursor = await paginate(
        session, stmt, [SortKey(AlertRoute.name), SortKey(AlertRoute.id)], page, "routes"
    )
    return AlertRoutePage(items=[AlertRouteOut.model_validate(r[0]) for r in rows], next_cursor=next_cursor)


@router.get("/alert-routes/{route_id}", response_model=AlertRouteOut, summary="One alert route")
async def get_route(route_id: int, principal: AdminUser, session: SessionDep) -> AlertRouteOut:
    return AlertRouteOut.model_validate(await _visible_route(session, principal, route_id))


@router.post(
    "/alert-routes", response_model=AlertRouteOut, status_code=status.HTTP_201_CREATED, summary="Add a route"
)
async def create_route(
    body: AlertRouteCreate, principal: AdminUser, session: SessionDep, request: Request
) -> AlertRouteOut:
    await _check_route_site(session, principal, body.site_id)
    target = _normalize_target(body.channel, body.target)
    route = AlertRoute(
        name=body.name,
        route=body.route,
        site_id=body.site_id,
        min_severity=body.min_severity.value,
        escalation_level=body.escalation_level,
        channel=body.channel.value,
        target_encrypted=encrypt(target),
        target_hint=mask_target(body.channel.value, target),
        enabled=body.enabled,
    )
    session.add(route)
    await flush_or_409(session, "The route conflicts with an existing one.")
    audit.record(
        session,
        principal=principal,
        action="alert_route.create",
        object_type="alert_route",
        object_id=route.id,
        after=audit.snapshot(route),
        request=request,
    )
    await session.commit()
    await session.refresh(route)
    return AlertRouteOut.model_validate(route)


@router.patch("/alert-routes/{route_id}", response_model=AlertRouteOut, summary="Change a route")
async def update_route(
    route_id: int, body: AlertRouteUpdate, principal: AdminUser, session: SessionDep, request: Request
) -> AlertRouteOut:
    route = await _visible_route(session, principal, route_id)
    await _check_route_site(session, principal, route.site_id)
    before = audit.snapshot(route)
    data = body.model_dump(exclude_unset=True)
    for key in ("name", "route", "min_severity", "escalation_level", "channel", "target", "enabled"):
        if key in data and data[key] is None:
            raise Problem(422, f"{key} cannot be null.")
    if "site_id" in data:
        await _check_route_site(session, principal, data["site_id"])
        route.site_id = data["site_id"]
    channel = RouteChannel(data.get("channel") or route.channel)
    if "channel" in data and channel.value != route.channel and "target" not in data:
        raise Problem(422, "Changing the channel needs a new target.")
    if "target" in data:
        target = _normalize_target(channel, data["target"])
        route.target_encrypted = encrypt(target)
        route.target_hint = mask_target(channel.value, target)
    route.channel = channel.value
    for key in ("name", "route", "escalation_level", "enabled"):
        if key in data:
            setattr(route, key, data[key])
    if "min_severity" in data:
        route.min_severity = data["min_severity"].value
    await flush_or_409(session, "The route conflicts with an existing one.")
    after = audit.snapshot(route)
    if "target" in data:
        after["target_changed"] = True
    b, a = audit.changed(before, after)
    audit.record(
        session,
        principal=principal,
        action="alert_route.update",
        object_type="alert_route",
        object_id=route.id,
        before=b,
        after=a,
        request=request,
    )
    await session.commit()
    await session.refresh(route)
    return AlertRouteOut.model_validate(route)


@router.delete("/alert-routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a route")
async def delete_route(
    route_id: int, principal: AdminUser, session: SessionDep, request: Request
) -> Response:
    route = await _visible_route(session, principal, route_id)
    await _check_route_site(session, principal, route.site_id)
    audit.record(
        session,
        principal=principal,
        action="alert_route.delete",
        object_type="alert_route",
        object_id=route.id,
        before=audit.snapshot(route),
        request=request,
    )
    await session.execute(delete(AlertRoute).where(AlertRoute.id == route.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
