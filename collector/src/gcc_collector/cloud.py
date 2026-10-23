"""Client for the cloud ingest API: config, batches, heartbeat. Outbound HTTPS only.

Auth (D8): ``token`` mode sends ``Authorization: Bearer <GCC_INGEST_TOKEN>``; ``mtls`` mode (when
``GCC_CLIENT_CERT`` is set) presents the client certificate, verified by the cloud's nginx. Both send
``X-Collector-Name``.
"""

from __future__ import annotations

import gzip
import logging
import ssl
from typing import Any

import httpx

from gcc_collector import __version__
from gcc_collector.config import CollectorEnv
from gcc_collector.schema import BatchResponse, CollectorConfig, Heartbeat, HeartbeatResponse

log = logging.getLogger("gcc.collector.cloud")


class IngestError(Exception):
    """The cloud did not take the request."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class IngestUnavailable(IngestError):
    """Retry later: network error, 5xx, 401/403 (e.g. collector not enabled yet), 408, 429."""


class IngestRejected(IngestError):
    """The batch itself is bad (400, 413, 422): retrying the same bytes can never succeed."""


PERMANENT_STATUSES = frozenset({400, 413, 415, 422})


def _ssl_context(env: CollectorEnv) -> ssl.SSLContext | bool:
    if env.ingest_auth_mode == "mtls" or env.ca_bundle is not None:
        ctx = ssl.create_default_context(cafile=str(env.ca_bundle) if env.ca_bundle else None)
        if env.client_cert is not None:
            ctx.load_cert_chain(str(env.client_cert), str(env.client_key) if env.client_key else None)
        return ctx
    return True


class CloudClient:
    def __init__(
        self,
        env: CollectorEnv,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.collector_name = env.collector_name
        headers = {
            "X-Collector-Name": env.collector_name,
            "User-Agent": f"gcc-collector/{__version__}",
            "Accept": "application/json",
        }
        if env.ingest_auth_mode == "token" and env.ingest_token is not None:
            headers["Authorization"] = f"Bearer {env.ingest_token.get_secret_value()}"
        self._http = httpx.AsyncClient(
            base_url=env.ingest_url,
            headers=headers,
            timeout=httpx.Timeout(timeout),
            verify=_ssl_context(env) if transport is None else True,
            transport=transport,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        content: bytes | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            resp = await self._http.request(method, path, content=content, json=json, headers=headers)
        except httpx.HTTPError as exc:
            raise IngestUnavailable(f"{method} {path}: {type(exc).__name__}") from None
        if resp.status_code < 300:
            return resp
        detail = resp.text[:300]
        if resp.status_code in PERMANENT_STATUSES:
            raise IngestRejected(
                f"{method} {path}: HTTP {resp.status_code}: {detail}", status=resp.status_code
            )
        raise IngestUnavailable(
            f"{method} {path}: HTTP {resp.status_code}: {detail}", status=resp.status_code
        )

    async def get_config(self) -> CollectorConfig:
        resp = await self._request("GET", "/ingest/v1/config")
        return CollectorConfig.model_validate_json(resp.content)

    async def post_batch(self, body_gz: bytes) -> BatchResponse:
        resp = await self._request(
            "POST",
            "/ingest/v1/batches",
            content=body_gz,
            headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
        )
        try:
            return BatchResponse.model_validate_json(resp.content)
        except ValueError:
            return BatchResponse()

    async def heartbeat(self, heartbeat: Heartbeat) -> HeartbeatResponse:
        resp = await self._request("POST", "/ingest/v1/heartbeat", json=heartbeat.model_dump(mode="json"))
        try:
            return HeartbeatResponse.model_validate_json(resp.content)
        except ValueError:
            return HeartbeatResponse()

    async def aclose(self) -> None:
        await self._http.aclose()


def gzip_json(body: bytes) -> bytes:
    return gzip.compress(body, compresslevel=6, mtime=0)
