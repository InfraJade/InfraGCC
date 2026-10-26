"""Async runtime for Celery tasks: one event loop, database engine and Redis client per worker process.

Connections must not cross a fork, and asyncpg/redis connections are bound to the loop that opened them, so
everything is created in the child process (`worker_process_init`) — or lazily on first use when Celery runs
without a prefork pool (`-P solo`, eager mode).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

from app.core import db
from app.core.config import get_settings
from app.core.redis import close_redis, set_redis

log = logging.getLogger("gcc.worker.runtime")

_loop: asyncio.AbstractEventLoop | None = None


def init_process() -> None:
    global _loop
    if _loop is not None and not _loop.is_closed():
        return
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    settings = get_settings()
    # Whatever the parent process may have created belongs to another process; start fresh.
    set_redis(None)
    db.set_engine(db.make_engine(settings.database_url.get_secret_value(), pool_size=4, max_overflow=4))


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine on this process's loop (used by every task)."""
    init_process()
    assert _loop is not None
    return _loop.run_until_complete(coro)


def shutdown_process() -> None:
    global _loop
    if _loop is None or _loop.is_closed():
        return
    try:
        _loop.run_until_complete(close_redis())
        _loop.run_until_complete(db.dispose_engine())
    except Exception:
        log.warning("error while closing worker resources", exc_info=True)
    finally:
        _loop.close()
        _loop = None
