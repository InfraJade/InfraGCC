"""Collector authentication for the ingest API (DECISIONS.md D8).

- `token` mode (dev): `Authorization: Bearer <INGEST_SHARED_TOKEN>` plus `X-Collector-Name`.
- `mtls` mode (prod): nginx terminates mutual TLS and forwards the verified client certificate's fingerprint
  (and subject). Those headers are trusted only when the TCP peer is one of `INGEST_TRUSTED_PROXIES`
  (addresses or CIDR ranges); the fingerprint must match `collectors.cert_fingerprint`.

Unknown or disabled collectors get 401 either way.
"""

from __future__ import annotations

import hmac
import ipaddress
import logging
import re

from fastapi import Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.problems import Problem
from app.models import Collector

log = logging.getLogger("gcc.ingest.auth")

COLLECTOR_NAME_HEADER = "X-Collector-Name"
_NON_HEX = re.compile(r"[^0-9a-f]")


def _unauthorized(detail: str) -> Problem:
    return Problem(401, detail, headers={"WWW-Authenticate": 'Bearer realm="gcc-ingest"'})


def normalize_fingerprint(value: str) -> str:
    """`SHA256:AB:CD:…`, `ab cd …` and `abcd…` all compare equal."""
    text = value.strip().lower()
    if text.startswith(("sha256:", "sha256=")):
        text = text[7:]
    return _NON_HEX.sub("", text)


def peer_is_trusted(peer: str | None, trusted: list[str]) -> bool:
    if not peer:
        return False
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return peer in trusted
    for entry in trusted:
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False


async def _by_name(session: AsyncSession, name: str) -> Collector | None:
    return (await session.execute(select(Collector).where(Collector.name == name))).scalar_one_or_none()


async def authenticate(request: Request, session: AsyncSession, settings: Settings) -> Collector:
    if settings.ingest_auth_mode == "token":
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        expected = settings.ingest_shared_token.get_secret_value()
        if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), expected.encode()):
            raise _unauthorized("Missing or invalid ingest token.")
        name = request.headers.get(COLLECTOR_NAME_HEADER, "").strip()
        if not name:
            raise _unauthorized(f"{COLLECTOR_NAME_HEADER} header is required.")
        collector = await _by_name(session, name)
    else:
        peer = request.client.host if request.client else None
        if not peer_is_trusted(peer, settings.ingest_trusted_proxies):
            log.warning("mTLS identity headers from untrusted peer %s ignored", peer)
            raise _unauthorized("Client certificate required.")
        raw = request.headers.get(settings.ingest_mtls_fingerprint_header, "")
        fingerprint = normalize_fingerprint(raw)
        if not fingerprint:
            raise _unauthorized("Client certificate required.")
        stored = func.regexp_replace(func.lower(Collector.cert_fingerprint), "[^0-9a-f]", "", "g")
        collector = (
            await session.execute(select(Collector).where(stored == fingerprint))
        ).scalar_one_or_none()
        claimed = request.headers.get(COLLECTOR_NAME_HEADER)
        if collector is not None and claimed and claimed.strip() != collector.name:
            raise _unauthorized("Certificate does not belong to the named collector.")
        if collector is not None:
            subject = request.headers.get(settings.ingest_mtls_subject_header)
            log.debug("collector %s authenticated by certificate %s", collector.name, subject)
    if collector is None or not collector.enabled:
        raise _unauthorized("Unknown or disabled collector.")
    return collector


async def current_collector(request: Request, session: AsyncSession = Depends(get_session)) -> Collector:
    collector = await authenticate(request, session, get_settings())
    request.state.collector_name = collector.name
    return collector
