"""Superset embedding: dashboard lookup and guest tokens with row-level security by site.

The app API signs in to Superset as the embed service account (`SUPERSET_ADMIN_USERNAME`, the `gcc_embed`
user), finds the six dashboards by slug and their embedded UUIDs, and asks for 5-minute guest tokens.
A site-limited user's token carries the RLS clause `site_id IN (...)`, which Superset applies to every
dataset of the dashboard (all reporting views have `site_id`). Unrestricted users get no RLS clause.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from app.core.config import Settings, get_settings
from app.core.problems import Problem
from app.core.security import Principal
from app.schemas.misc import DashboardOut, GuestTokenOut

log = logging.getLogger("gcc.superset")

# Slug → refresh interval in seconds (DESIGN "Dashboards"), used when the dashboard sets none itself.
DASHBOARDS: dict[str, int] = {
    "dc-overview": 300,
    "thermal": 300,
    "power-capacity": 900,
    "hardware-health": 900,
    "alerts": 900,
    "inventory-firmware": 86400,
}
GUEST_TOKEN_TTL_S = 300
_DASHBOARD_CACHE_S = 300
_TOKEN_REFRESH_MARGIN_S = 60


class SupersetUnavailable(Exception):
    """Superset could not be reached or refused the service account."""


class SupersetClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base_url = settings.superset_url.rstrip("/")
        self.public_url = settings.superset_public_url.rstrip("/")
        self._username = settings.superset_admin_username
        self._password = settings.superset_admin_password.get_secret_value()
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None
        self._token_expires = 0.0
        self._csrf: str | None = None
        self._lock = asyncio.Lock()
        self._dashboards: list[DashboardOut] | None = None
        self._dashboards_expire = 0.0

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url, timeout=httpx.Timeout(10.0), transport=self._transport
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None

    async def _login(self) -> None:
        client = self._http()
        try:
            resp = await client.post(
                "/api/v1/security/login",
                json={
                    "username": self._username,
                    "password": self._password,
                    "provider": "db",
                    "refresh": False,
                },
            )
        except httpx.HTTPError as exc:
            raise SupersetUnavailable(f"cannot reach Superset: {exc}") from exc
        if resp.status_code != 200:
            raise SupersetUnavailable(f"Superset login failed with HTTP {resp.status_code}")
        token = str(resp.json()["access_token"])
        self._access_token = token
        try:
            exp = float(jwt.decode(token, options={"verify_signature": False}).get("exp", 0))
        except jwt.PyJWTError:
            exp = 0.0
        self._token_expires = exp if exp else time.time() + 600
        # Superset protects POST endpoints with CSRF unless they are exempt; fetch a token either way.
        self._csrf = None
        try:
            csrf = await client.get(
                "/api/v1/security/csrf_token/", headers={"Authorization": f"Bearer {token}"}
            )
            if csrf.status_code == 200:
                self._csrf = str(csrf.json().get("result") or "") or None
        except httpx.HTTPError as exc:
            log.warning("could not fetch Superset CSRF token: %s", exc)

    async def _ensure_login(self, force: bool = False) -> None:
        async with self._lock:
            if (
                force
                or self._access_token is None
                or time.time() > self._token_expires - _TOKEN_REFRESH_MARGIN_S
            ):
                await self._login()

    async def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> httpx.Response:
        await self._ensure_login()
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self._access_token}", "Referer": self.base_url}
            if self._csrf:
                headers["X-CSRFToken"] = self._csrf
            try:
                resp = await self._http().request(method, path, json=body, headers=headers)
            except httpx.HTTPError as exc:
                raise SupersetUnavailable(f"cannot reach Superset: {exc}") from exc
            if resp.status_code == 401 and attempt == 1:
                await self._ensure_login(force=True)
                continue
            if resp.status_code >= 500:
                raise SupersetUnavailable(f"Superset returned HTTP {resp.status_code} for {path}")
            return resp
        raise SupersetUnavailable("Superset rejected the service account")

    async def dashboards(self) -> list[DashboardOut]:
        if self._dashboards is not None and time.monotonic() < self._dashboards_expire:
            return self._dashboards
        found: list[DashboardOut] = []
        for slug, default_refresh in DASHBOARDS.items():
            resp = await self._request("GET", f"/api/v1/dashboard/{slug}")
            if resp.status_code == 404:
                log.warning("Superset dashboard %s not found", slug)
                continue
            if resp.status_code != 200:
                raise SupersetUnavailable(f"Superset returned HTTP {resp.status_code} for dashboard {slug}")
            result = resp.json()["result"]
            embedded = await self._request("GET", f"/api/v1/dashboard/{result['id']}/embedded")
            if embedded.status_code != 200:
                log.warning("Superset dashboard %s has no embedded configuration", slug)
                continue
            found.append(
                DashboardOut(
                    slug=slug,
                    title=str(result.get("dashboard_title") or slug),
                    embedded_uuid=str(embedded.json()["result"]["uuid"]),
                    refresh_s=_refresh(result.get("json_metadata"), default_refresh),
                )
            )
        self._dashboards = found
        self._dashboards_expire = time.monotonic() + _DASHBOARD_CACHE_S
        return found

    async def guest_token(self, embedded_uuid: str, principal: Principal) -> GuestTokenOut:
        known = {d.embedded_uuid for d in await self.dashboards()}
        if embedded_uuid not in known:
            raise Problem(404, "No embedded dashboard has that id.")
        body = {
            "user": {
                "username": principal.username,
                "first_name": principal.display_name,
                "last_name": "",
            },
            "resources": [{"type": "dashboard", "id": embedded_uuid}],
            "rls": rls_rules(principal),
        }
        resp = await self._request("POST", "/api/v1/security/guest_token/", body)
        if resp.status_code != 200:
            raise SupersetUnavailable(f"Superset refused the guest token request (HTTP {resp.status_code})")
        token = str(resp.json()["token"])
        return GuestTokenOut(token=token, expires_at=_token_expiry(token), superset_url=self.public_url)


def rls_rules(principal: Principal) -> list[dict[str, str]]:
    """Row-level security for the user's sites; none for users who see every site."""
    if principal.site_ids is None:
        return []
    if not principal.site_ids:
        return [{"clause": "1 = 0"}]
    ids = ", ".join(str(int(s)) for s in sorted(principal.site_ids))
    return [{"clause": f"site_id IN ({ids})"}]


def _refresh(json_metadata: Any, default: int) -> int:
    try:
        meta = json.loads(json_metadata) if isinstance(json_metadata, str) else (json_metadata or {})
        value = int(meta.get("refresh_frequency") or 0)
    except (ValueError, TypeError, AttributeError):
        value = 0
    return value or default


def _token_expiry(token: str) -> datetime:
    try:
        exp = jwt.decode(token, options={"verify_signature": False}).get("exp")
        if exp:
            return datetime.fromtimestamp(float(exp), UTC)
    except jwt.PyJWTError:
        pass
    return datetime.now(UTC) + timedelta(seconds=GUEST_TOKEN_TTL_S)


_client: SupersetClient | None = None


def get_superset() -> SupersetClient:
    global _client
    if _client is None:
        _client = SupersetClient(get_settings())
    return _client


def set_superset(client: SupersetClient | None) -> None:
    global _client
    _client = client


async def close_superset() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def unavailable_problem(exc: SupersetUnavailable) -> Problem:
    log.error("Superset unavailable: %s", exc)
    return Problem(503, "Analytics (Superset) is unavailable right now. Try again shortly.")
