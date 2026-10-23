"""Audit log writer: who changed what, from where, in which request.

Logged (DESIGN "Security" → Audit): sign-ins, asset changes (sites, rooms, racks, servers, collectors,
baselines, maintenance windows), threshold and rule changes, routing changes and alert actions. The row is
added to the caller's session so it commits (or rolls back) together with the change it describes.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from fastapi import Request
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog

if TYPE_CHECKING:
    from app.core.security import Principal

# Columns never copied into audit snapshots.
_REDACTED = {"target_encrypted"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(v) for v in value]
    return value


def snapshot(obj: object, *, exclude: set[str] | None = None) -> dict[str, Any]:
    """Column values of an ORM object as a JSON-safe dict (secrets left out)."""
    state = inspect(obj)
    assert state is not None
    # Expired attributes (e.g. server-side `updated_at` after a flush) are skipped rather than reloaded.
    skip = _REDACTED | (exclude or set()) | set(state.unloaded)
    return {
        attr.key: _jsonable(getattr(obj, attr.key))
        for attr in state.mapper.column_attrs
        if attr.key not in skip
    }


def changed(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Only the keys whose values differ (ignoring bookkeeping timestamps)."""
    keys = {k for k in before.keys() | after.keys() if k not in {"updated_at"}}
    diff = {k for k in keys if before.get(k) != after.get(k)}
    return {k: before.get(k) for k in diff}, {k: after.get(k) for k in diff}


def client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def request_id(request: Request | None) -> str | None:
    if request is None:
        return None
    rid = getattr(request.state, "request_id", None)
    return str(rid) if rid else None


def record(
    session: AsyncSession,
    *,
    principal: Principal | None,
    action: str,
    object_type: str,
    object_id: str | int | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request: Request | None = None,
) -> AuditLog:
    """Add one audit row to `session` (the caller commits)."""
    entry = AuditLog(
        user_sub=principal.sub if principal else None,
        user_name=principal.display_name if principal else "system",
        action=action,
        object_type=object_type,
        object_id=None if object_id is None else str(object_id),
        before=_jsonable(before) if before is not None else None,
        after=_jsonable(after) if after is not None else None,
        ip=client_ip(request),
        request_id=request_id(request),
    )
    session.add(entry)
    return entry
