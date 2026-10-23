"""Per-user fixed-window rate limit in Redis.

One counter per user per clock minute (`gcc:rl:<sub>:<minute>`). Over the limit → 429 problem with
`Retry-After` set to the seconds left in the window. If Redis is down or slow the request is allowed
(fail open): rate limiting protects the API, it must never take it down.
"""

from __future__ import annotations

import asyncio
import logging
import time

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.problems import Problem
from app.core.redis import get_redis

log = logging.getLogger("gcc.ratelimit")

WINDOW_S = 60
_REDIS_TIMEOUT_S = 0.5


async def check_rate_limit(key: str, limit: int, *, redis: Redis | None = None) -> None:
    """Count one request for `key`; raise a 429 problem when it is over `limit` in this window."""
    if limit <= 0:
        return
    now = time.time()
    window = int(now // WINDOW_S)
    retry_after = max(1, WINDOW_S - int(now % WINDOW_S))
    rkey = f"gcc:rl:{key}:{window}"
    client = redis or get_redis()
    try:
        count = await asyncio.wait_for(_incr(client, rkey), timeout=_REDIS_TIMEOUT_S)
    except (RedisError, OSError, TimeoutError) as exc:
        log.warning("rate limit check skipped, Redis unavailable: %s", exc)
        return
    if count > limit:
        raise Problem(
            429,
            f"Rate limit of {limit} requests per minute exceeded. Try again in {retry_after} s.",
            headers={"Retry-After": str(retry_after)},
            limit=limit,
            retry_after=retry_after,
        )


async def _incr(client: Redis, key: str) -> int:
    async with client.pipeline(transaction=False) as pipe:
        pipe.incr(key)
        pipe.expire(key, WINDOW_S + 1)
        results = await pipe.execute()
    return int(results[0])
