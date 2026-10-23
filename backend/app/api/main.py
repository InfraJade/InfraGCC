"""App API: everything the React app needs (inventory, live data, history, alerts, admin, Superset).

    uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers

REST under /api/v1 (OpenAPI at /api/v1/openapi.json, docs at /docs), WebSocket at /api/v1/live,
RFC 9457 problem details for every error, `X-Request-ID` on every response, `/healthz` (liveness) and
`/readyz` (database + Redis).
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api import live
from app.api.routers import admin, alerts, config, general, operations, servers, sites, superset
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.problems import Problem, install_problem_handlers, problem_response
from app.core.redis import get_redis
from app.schemas.common import ProblemOut
from app.services.live_hub import hub
from app.services.superset import close_superset

log = logging.getLogger("gcc.api")

try:
    API_VERSION = version("gcc-backend")
except PackageNotFoundError:  # pragma: no cover - running from a source tree without metadata
    API_VERSION = "1.0.0"

_PROBLEM = {"model": ProblemOut, "content": {"application/problem+json": {}}}
PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Missing, invalid or expired access token", **_PROBLEM},
    403: {"description": "The user's role or site scope does not allow this", **_PROBLEM},
    404: {"description": "Not found (or outside the user's sites)", **_PROBLEM},
    422: {"description": "Validation failed", **_PROBLEM},
    429: {"description": "Rate limit exceeded (see Retry-After)", **_PROBLEM},
}

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestIdMiddleware:
    """Use the caller's `X-Request-ID` (if sane) or a new one; expose it on the request and the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = next((v.decode("latin-1") for k, v in scope["headers"] if k == b"x-request-id"), "")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_id)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_settings()  # fails fast in prod with dev secrets
    await hub.start()
    try:
        yield
    finally:
        await hub.stop()
        await close_superset()


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return problem_response(Problem(500, "Something went wrong on our side."), request)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Jade GCC API",
        version=API_VERSION,
        description=(
            "App API of the Jade GCC data center monitoring platform. Every request needs an OIDC access "
            "token (`Authorization: Bearer …`). Errors are RFC 9457 `application/problem+json`. Lists use "
            "cursor pagination (`limit`, `cursor` → `{items, next_cursor}`)."
        ),
        openapi_url="/api/v1/openapi.json",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    install_problem_handlers(app)
    app.add_exception_handler(Exception, _unhandled)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After", "Content-Disposition"],
        max_age=600,
    )
    app.add_middleware(RequestIdMiddleware)

    api = APIRouter(prefix="/api/v1", responses=PROBLEM_RESPONSES)
    for module in (general, sites, servers, alerts, config, operations, admin, superset):
        api.include_router(module.router)
    api.include_router(live.router)
    app.include_router(api)

    @app.get("/healthz", tags=["health"], summary="Liveness")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"], summary="Readiness: database and Redis reachable")
    async def readyz(request: Request) -> Any:
        checks: dict[str, str] = {}
        try:
            async with get_sessionmaker()() as session:
                await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=3)
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"
        try:
            await asyncio.wait_for(get_redis().ping(), timeout=2)
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {type(exc).__name__}"
        if all(v == "ok" for v in checks.values()):
            return {"status": "ok", "checks": checks}
        return problem_response(Problem(503, "Not ready.", checks=checks), request)

    return app


app = create_app()
