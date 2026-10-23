"""Users (read-only, D22) and the audit log (platform admins without a site limit, D21)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import String, cast, or_, select
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY

from app.api.deps import PageDep, SessionDep
from app.core.enums import Role
from app.core.pagination import SortKey, paginate
from app.core.problems import Problem
from app.core.security import AdminUser
from app.models import AuditLog, User
from app.schemas.admin import AuditOut, AuditPage, UserOut, UserPage
from app.services.query.common import like_pattern

router = APIRouter(tags=["admin"])


@router.get(
    "/users",
    response_model=UserPage,
    summary="People who have signed in, with roles and sites (from the IdP)",
)
async def list_users(
    principal: AdminUser,
    session: SessionDep,
    page: PageDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    role: Annotated[Role | None, Query()] = None,
) -> UserPage:
    stmt = select(User)
    if principal.site_codes is not None:
        # A site-limited admin sees the people of their own sites only.
        stmt = stmt.where(cast(User.sites, PG_ARRAY(String)).overlap(sorted(principal.site_codes)))
    if q:
        pattern = like_pattern(q.strip())
        stmt = stmt.where(or_(User.name.ilike(pattern), User.email.ilike(pattern), User.sub.ilike(pattern)))
    if role is not None:
        stmt = stmt.where(cast(User.roles, PG_ARRAY(String)).contains([role.value]))
    rows, next_cursor = await paginate(session, stmt, [SortKey(User.name), SortKey(User.id)], page, "users")
    return UserPage(items=[UserOut.model_validate(r[0]) for r in rows], next_cursor=next_cursor)


@router.get("/audit", response_model=AuditPage, summary="Audit log: who changed what and when (newest first)")
async def list_audit(
    principal: AdminUser,
    session: SessionDep,
    page: PageDep,
    user: Annotated[str | None, Query(max_length=128, description="User sub or name (substring)")] = None,
    action: Annotated[
        str | None, Query(max_length=64, description="Exact action, or a prefix ending in '.'")
    ] = None,
    object_type: Annotated[str | None, Query(max_length=48)] = None,
    object_id: Annotated[str | None, Query(max_length=64)] = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
) -> AuditPage:
    if principal.restricted:
        raise Problem(
            403, "The audit log covers every site; it is available to platform admins without a site limit."
        )
    stmt = select(AuditLog)
    if user:
        pattern = like_pattern(user.strip())
        stmt = stmt.where(or_(AuditLog.user_sub == user, AuditLog.user_name.ilike(pattern)))
    if action:
        stmt = stmt.where(
            AuditLog.action.startswith(action) if action.endswith(".") else AuditLog.action == action
        )
    if object_type:
        stmt = stmt.where(AuditLog.object_type == object_type)
    if object_id:
        stmt = stmt.where(AuditLog.object_id == object_id)
    if start is not None:
        stmt = stmt.where(AuditLog.time >= start)
    if end is not None:
        stmt = stmt.where(AuditLog.time < end)
    rows, next_cursor = await paginate(
        session, stmt, [SortKey(AuditLog.time, True), SortKey(AuditLog.id, True)], page, "audit"
    )
    return AuditPage(items=[AuditOut.model_validate(r[0]) for r in rows], next_cursor=next_cursor)
