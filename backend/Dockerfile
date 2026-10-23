# syntax=docker/dockerfile:1.7
#
# One image, four services (plus the one-shot migrate job). The command picks the service:
#   app API      uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --proxy-headers   (default)
#   ingest API   uvicorn app.ingest.main:app --host 0.0.0.0 --port 8001 --proxy-headers
#   alert worker celery -A app.worker.celery_app worker -Q alerts,notify -c 4 -n alerts@%h
#   scheduler    celery -A app.worker.celery_app worker -B -Q scheduled -c 2 -n scheduler@%h
#   migrate      sh -c "alembic upgrade head && python -m app.seed dev"
#
# Build: docker build -t gcc-backend:dev backend

ARG PYTHON_IMAGE=python:3.12-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.9

FROM ${UV_IMAGE} AS uv

# ---------------------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS build

COPY --from=uv /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_HTTP_TIMEOUT=180

WORKDIR /app

# Dependencies first (cached until pyproject.toml / uv.lock change). The project itself is not installed:
# the source is on PYTHONPATH, so `alembic`, `uvicorn app...`, `celery -A app...` and `python -m app...`
# all import it from /app.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="gcc-backend" \
      org.opencontainers.image.description="Jade GCC ingest API, app API, alert worker, scheduler and migrations"

RUN groupadd --system --gid 10001 gcc \
 && useradd --system --uid 10001 --gid gcc --home-dir /app --no-create-home --shell /usr/sbin/nologin gcc

ENV PATH=/app/.venv/bin:${PATH} \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=build --chown=root:root /app/.venv /app/.venv
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root alembic ./alembic
COPY --chown=root:root app ./app
COPY --chown=root:root scripts ./scripts

# Code is root-owned and read-only for the service user; nothing in the image needs to be writable.
USER 10001:10001

EXPOSE 8000 8001

CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
