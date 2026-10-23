# syntax=docker/dockerfile:1.7
#
# Jade GCC on-prem collector: polls BMCs over Redfish, pushes batches to the cloud ingest API.
#   docker build -t gcc-collector:dev collector
#   docker run --env-file collector.env -v gcc-buffer:/var/lib/gcc-collector/buffer gcc-collector:dev
# Configuration is environment only (docs/contracts/README.md, "Collector environment variables").

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

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# ---------------------------------------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="gcc-collector" \
      org.opencontainers.image.description="Jade GCC on-prem Redfish collector"

RUN groupadd --system --gid 10001 gcc \
 && useradd --system --uid 10001 --gid gcc --home-dir /app --no-create-home --shell /usr/sbin/nologin gcc \
 && mkdir -p /var/lib/gcc-collector/buffer /etc/gcc-collector \
 && chown -R 10001:10001 /var/lib/gcc-collector

ENV PATH=/app/.venv/bin:${PATH} \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GCC_BUFFER_DIR=/var/lib/gcc-collector/buffer

WORKDIR /app

COPY --from=build --chown=root:root /app/.venv /app/.venv

# The disk buffer is the only writable path; mount a volume there so batches survive restarts.
VOLUME ["/var/lib/gcc-collector/buffer"]

USER 10001:10001

EXPOSE 9108

STOPSIGNAL SIGTERM

CMD ["python", "-m", "gcc_collector"]
