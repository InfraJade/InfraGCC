"""Shared router dependencies and helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import Depends
from redis.exceptions import RedisError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.live import AlertMessage, publish
from app.core.pagination import PageParams, page_params
from app.core.problems import Problem
from app.core.redis import get_redis
from app.models import Alert

log = logging.getLogger("gcc.api")

SessionDep = Annotated[AsyncSession, Depends(get_session)]
PageDep = Annotated[PageParams, Depends(page_params)]


async def commit_or_409(session: AsyncSession, detail: str) -> None:
    """Commit; a unique/foreign-key violation becomes a 409 problem."""
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise Problem(409, detail) from exc


async def flush_or_409(session: AsyncSession, detail: str) -> None:
    """Flush pending changes (to get ids); a unique/foreign-key violation becomes a 409 problem."""
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise Problem(409, detail) from exc


async def publish_alert(alert: Alert, change: str) -> None:
    """Tell open browsers about an alert change. Best effort: the change is already committed."""
    message = AlertMessage(
        alert_id=alert.id,
        server_id=alert.server_id,
        site_id=alert.site_id,
        state=alert.state,
        severity=alert.severity,
        title=alert.title,
        change=change,
    )
    try:
        await asyncio.wait_for(publish(get_redis(), message), timeout=1.0)
    except (RedisError, OSError, TimeoutError) as exc:
        log.warning("could not publish alert %s change: %s", alert.id, exc)
