"""One Redfish client per BMC.

Rules that protect the BMCs (docs/DESIGN.md, "Rules that protect the BMCs"):

- one request in flight per BMC (``asyncio.Lock`` per client) and a global ``asyncio.Semaphore`` that caps
  how many BMCs are being talked to at once;
- a session (``POST /redfish/v1/SessionService/Sessions`` -> ``X-Auth-Token``), re-created transparently once
  per request on a 401; HTTP Basic when the service has no session support (404 / 405 / 501);
- a 20 s timeout; exponential backoff with full jitter on connection errors and 500/502/503/504 only
  (a read timeout means the BMC is busy or hung, so it is not retried);
- ``$expand`` on collections only when the service root's ``ProtocolFeaturesSupported.ExpandQuery`` says so.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import random
import ssl
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from gcc_collector.credentials import Credentials

log = logging.getLogger("gcc.collector.redfish")

Json = dict[str, Any]
SESSIONS_PATH = "/redfish/v1/SessionService/Sessions"
RETRY_STATUSES = frozenset({500, 502, 503, 504})
NO_SESSION_STATUSES = frozenset({404, 405, 501})
MAX_COLLECTION_PAGES = 50


class RedfishError(Exception):
    """Base class for everything the client raises."""


class BmcUnreachable(RedfishError):
    """The BMC did not answer (connection refused, timeout, TLS failure) after the allowed retries."""


class InvalidResponse(RedfishError):
    """The BMC answered with something that is not a JSON object."""


class RedfishHTTPError(RedfishError):
    def __init__(self, status: int, path: str, message: str | None = None) -> None:
        self.status = status
        self.path = path
        super().__init__(message or f"HTTP {status} for {path}")


class NotFound(RedfishHTTPError):
    """404: the resource moved. The poller rediscovers the BMC's tree."""


class AuthError(RedfishHTTPError):
    """Credentials rejected (login failed, or 401 again right after a fresh login)."""


def parse_bmc_host(bmc_host: str) -> str:
    """Base URL for a ``bmc_host`` value: ``host``, ``host:port`` or a full URL. A bare host means https.

    A trailing ``/redfish`` or ``/redfish/v1`` is dropped; the client always builds paths from the root.
    """
    value = bmc_host.strip()
    if not value:
        raise ValueError("bmc_host is empty")
    if "://" not in value:
        value = f"https://{value}"
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"unsupported bmc_host {bmc_host!r}")
    path = parts.path.rstrip("/")
    for suffix in ("/redfish/v1", "/redfish"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return f"{parts.scheme}://{parts.netloc}{path}"


def expand_query(root: Json) -> str | None:
    """The ``$expand`` value to use for collections, from ``ProtocolFeaturesSupported.ExpandQuery``."""
    features = root.get("ProtocolFeaturesSupported")
    if not isinstance(features, dict):
        return None
    expand = features.get("ExpandQuery")
    if expand is True:
        return "."
    if not isinstance(expand, dict) or not expand.get("NoLinks"):
        return None
    return ".($levels=1)" if expand.get("Levels") else "."


@functools.cache
def shared_tls_context(verify: bool) -> ssl.SSLContext:
    """One TLS context for all BMC clients (creating one per client costs ~50 ms and memory)."""
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


CredentialSource = Credentials | Callable[[], Awaitable[Credentials]]


class RedfishClient:
    """Talks to one BMC. Safe to share between tasks: requests are serialised by a per-BMC lock."""

    def __init__(
        self,
        bmc_host: str,
        credentials: CredentialSource,
        *,
        verify: bool | ssl.SSLContext = True,
        timeout: float = 20.0,
        semaphore: asyncio.Semaphore | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 2,
        backoff_base: float = 0.5,
        backoff_cap: float = 8.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.bmc_host = bmc_host
        self.base_url = parse_bmc_host(bmc_host)
        self._credentials = credentials
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            verify=verify if isinstance(verify, ssl.SSLContext) else shared_tls_context(verify),
            timeout=httpx.Timeout(timeout),
            transport=transport,
            headers={"Accept": "application/json", "OData-Version": "4.0"},
            follow_redirects=False,
        )
        self._lock = asyncio.Lock()
        self._semaphore = semaphore or asyncio.Semaphore(1)
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._sleep = sleep
        self._token: str | None = None
        self._session_path: str | None = None
        self._basic: httpx.BasicAuth | None = None
        self.expand: str | None = None
        self.requests_sent = 0

    # ------------------------------------------------------------------------------ public API
    @property
    def auth_mode(self) -> str:
        if self._basic is not None:
            return "basic"
        return "session" if self._token else "none"

    def configure(self, service_root: Json) -> None:
        """Enable ``$expand`` if the service root advertises it."""
        self.expand = expand_query(service_root)

    async def get(self, path: str, *, query: str | None = None) -> Json:
        """GET a resource as a JSON object. Raises NotFound, AuthError, RedfishHTTPError, BmcUnreachable."""
        url = f"{path}?{query}" if query else path
        async with self._lock:
            resp = await self._authed("GET", url)
        if resp.status_code == 404:
            raise NotFound(404, path)
        if resp.status_code >= 400:
            raise RedfishHTTPError(resp.status_code, path)
        try:
            body = resp.json()
        except ValueError:
            raise InvalidResponse(f"{path}: response is not JSON") from None
        if not isinstance(body, dict):
            raise InvalidResponse(f"{path}: response is not a JSON object")
        return body

    async def get_root(self) -> Json:
        """The service root. Also turns on ``$expand`` when the service supports it."""
        root = await self.get("/redfish/v1")
        self.configure(root)
        return root

    async def get_collection(self, path: str) -> list[Json]:
        """All members of a collection, expanded in one call when the BMC supports ``$expand``.

        Members that come back as bare links are fetched one by one. ``Members@odata.nextLink`` is followed.
        """
        if self.expand:
            try:
                coll = await self.get(path, query=f"$expand={self.expand}")
            except NotFound:
                raise
            except RedfishHTTPError as exc:
                if exc.status not in (400, 405, 501):
                    raise
                log.info("%s: $expand rejected (%s); disabling it", self.bmc_host, exc.status)
                self.expand = None
                coll = await self.get(path)
        else:
            coll = await self.get(path)
        members: list[Json] = []
        pages = 0
        while True:
            for member in coll.get("Members") or []:
                if not isinstance(member, dict):
                    continue
                if _is_link(member):
                    member_path = member.get("@odata.id")
                    if isinstance(member_path, str):
                        members.append(await self.get(member_path))
                else:
                    members.append(member)
            next_link = coll.get("Members@odata.nextLink")
            pages += 1
            if not isinstance(next_link, str) or pages >= MAX_COLLECTION_PAGES:
                break
            coll = await self.get(next_link)
        return members

    async def close(self) -> None:
        """Delete the session (best effort) and close connections."""
        if self._session_path and self._token:
            try:
                async with self._lock:
                    await self._http.delete(
                        self._session_path, headers={"X-Auth-Token": self._token}, timeout=5.0
                    )
            except httpx.HTTPError:
                pass
        self._token = None
        self._session_path = None
        await self._http.aclose()

    # ---------------------------------------------------------------------------- internals
    async def _creds(self) -> Credentials:
        if isinstance(self._credentials, Credentials):
            return self._credentials
        return await self._credentials()

    async def _login(self) -> None:
        creds = await self._creds()
        self._token = None
        self._session_path = None
        resp = await self._send(
            "POST",
            SESSIONS_PATH,
            json={"UserName": creds.username, "Password": creds.password.get_secret_value()},
        )
        token = resp.headers.get("X-Auth-Token")
        if resp.status_code in (200, 201, 202, 204) and token:
            self._token = token
            location = resp.headers.get("Location")
            if location:
                self._session_path = urlsplit(location).path or None
            self._basic = None
            log.debug("%s: session created", self.bmc_host)
            return
        if resp.status_code in NO_SESSION_STATUSES or (resp.status_code < 300 and not token):
            log.info("%s: sessions unsupported (%s); using Basic auth", self.bmc_host, resp.status_code)
            self._basic = httpx.BasicAuth(creds.username, creds.password.get_secret_value())
            return
        if resp.status_code in (401, 403):
            raise AuthError(resp.status_code, SESSIONS_PATH, f"login rejected by {self.bmc_host}")
        raise RedfishHTTPError(resp.status_code, SESSIONS_PATH, f"login failed with HTTP {resp.status_code}")

    def _auth(self) -> tuple[dict[str, str], httpx.BasicAuth | None]:
        if self._token:
            return {"X-Auth-Token": self._token}, None
        return {}, self._basic

    async def _authed(self, method: str, url: str) -> httpx.Response:
        if self._token is None and self._basic is None:
            await self._login()
        headers, basic = self._auth()
        resp = await self._send(method, url, headers=headers, auth=basic)
        if resp.status_code != 401:
            return resp
        if self._basic is not None:
            raise AuthError(401, url, f"Basic credentials rejected by {self.bmc_host}")
        log.info("%s: session expired; logging in again", self.bmc_host)
        await self._login()
        headers, basic = self._auth()
        resp = await self._send(method, url, headers=headers, auth=basic)
        if resp.status_code == 401:
            raise AuthError(401, url, f"credentials rejected by {self.bmc_host}")
        return resp

    def _delay(self, attempt: int) -> float:
        # Full jitter: uniform(0, min(cap, base * 2^attempt)).
        return random.uniform(0, min(self._backoff_cap, self._backoff_base * (2**attempt)))

    async def _send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        auth: httpx.BasicAuth | None = None,
        json: Json | None = None,
    ) -> httpx.Response:
        attempt = 0
        while True:
            try:
                async with self._semaphore:
                    self.requests_sent += 1
                    request = self._http.build_request(method, url, headers=headers, json=json)
                    resp = await self._http.send(
                        request, auth=auth if auth is not None else httpx.USE_CLIENT_DEFAULT
                    )
                    await resp.aread()
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
                if attempt >= self._max_retries:
                    raise BmcUnreachable(f"{self.bmc_host}: {type(exc).__name__}") from None
            except httpx.TimeoutException as exc:
                raise BmcUnreachable(f"{self.bmc_host}: {type(exc).__name__}") from None
            except httpx.HTTPError as exc:
                raise BmcUnreachable(f"{self.bmc_host}: {type(exc).__name__}") from None
            else:
                if resp.status_code not in RETRY_STATUSES or attempt >= self._max_retries:
                    return resp
            await self._sleep(self._delay(attempt))
            attempt += 1


def _is_link(member: Json) -> bool:
    return all(key.startswith("@odata.") for key in member)
