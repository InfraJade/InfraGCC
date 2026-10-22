"""Live updates over Redis pub/sub.

The ingest API publishes new readings and health changes, the alert worker publishes alert changes; the
app API's WebSocket hub subscribes to LIVE_CHANNEL once per process and fans messages out to browsers
that subscribed to the server or site. Every message carries both `server_id` and `site_id` so the hub
can filter without a database lookup.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from redis.asyncio import Redis

LIVE_CHANNEL = "gcc:live"


class LiveReading(BaseModel):
    metric: str
    component: str
    value: float | None
    status: str | None
    time: datetime


class ReadingsMessage(BaseModel):
    type: Literal["readings"] = "readings"
    server_id: int
    site_id: int
    readings: list[LiveReading]


class HealthChange(BaseModel):
    metric: str
    component: str
    health: str
    state: str | None
    since: datetime


class HealthMessage(BaseModel):
    type: Literal["health"] = "health"
    server_id: int
    site_id: int
    changes: list[HealthChange]
    # Worst health across the server after this change, so lists can recolor without refetching.
    server_health: str


class AlertMessage(BaseModel):
    type: Literal["alert"] = "alert"
    alert_id: int
    server_id: int | None
    site_id: int | None
    state: str
    severity: str
    title: str
    # opened | updated | acknowledged | resolved | escalated
    change: str


LiveMessage = Annotated[ReadingsMessage | HealthMessage | AlertMessage, Field(discriminator="type")]


async def publish(redis: Redis, message: ReadingsMessage | HealthMessage | AlertMessage) -> None:
    await redis.publish(LIVE_CHANNEL, message.model_dump_json())
