"""Transport: SMTP via aiosmtplib and Teams incoming webhooks via httpx."""

from __future__ import annotations

import re
from email.message import EmailMessage
from typing import Any

import aiosmtplib
import httpx

from app.core.config import Settings

TEAMS_TIMEOUT_S = 10.0


def split_recipients(target: str) -> list[str]:
    return [p for p in (s.strip() for s in re.split(r"[,;\s]+", target)) if p]


async def send_email(message: EmailMessage, settings: Settings) -> None:
    password = settings.smtp_password.get_secret_value() if settings.smtp_password else None
    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=password,
        start_tls=settings.smtp_starttls,
        timeout=20,
    )


async def post_teams(url: str, payload: dict[str, Any], client: httpx.AsyncClient | None = None) -> None:
    if client is None:
        async with httpx.AsyncClient(timeout=TEAMS_TIMEOUT_S) as own:
            response = await own.post(url, json=payload)
    else:
        response = await client.post(url, json=payload, timeout=TEAMS_TIMEOUT_S)
    response.raise_for_status()
