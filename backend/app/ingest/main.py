"""Ingest API application.

    uvicorn app.ingest.main:app --host 0.0.0.0 --port 8001

Connects to the database as the least-privilege `gcc_ingest` role (DATABASE_URL). Errors are RFC 9457
problem details. `/healthz` is liveness, `/readyz` also checks the database, `/metrics` is Prometheus.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import dispose_engine, get_engine
from app.core.problems import Problem, install_problem_handlers
from app.core.redis import close_redis
from app.ingest.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    yield
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    application = FastAPI(
        title="Jade GCC ingest API",
        version="1.0.0",
        description="Receives batches and heartbeats from on-prem collectors (docs/contracts/README.md).",
        lifespan=lifespan,
        openapi_url="/ingest/v1/openapi.json",
        docs_url=None,
        redoc_url=None,
    )
    install_problem_handlers(application)
    application.include_router(router)

    @application.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz", include_in_schema=False)
    async def readyz() -> dict[str, str]:
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            raise Problem(503, "Database unavailable.") from exc
        return {"status": "ready"}

    @application.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return application


app = create_app()
