# gcc-bmc-simulator: N virtual Redfish BMCs plus the control API / Teams webhook sink in one process.
#
#   docker build -t gcc-bmc-simulator:dev mockups
#   docker run --rm -e SIM_COUNT=36 -p 9100:9100 -p 20001-20036:20001-20036 gcc-bmc-simulator:dev
#
# Ports: control API on SIM_CONTROL_PORT (9100); BMC i (1-based) on SIM_BASE_PORT + i, i.e. 20001..20036 with
# the defaults (SIM_COUNT=36, SIM_BASE_PORT=20000). In compose the collectors reach BMCs on the internal
# network (http://bmc-simulator:2000i), so the BMC range does not need to be published on the host.

FROM ghcr.io/astral-sh/uv:0.12.9 AS uv

FROM python:3.12-slim

COPY --from=uv /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# Dependencies first (cached layer), then the project itself, both pinned by uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin sim

USER sim

ENV SIM_COUNT=36 \
    SIM_BASE_PORT=20000 \
    SIM_CONTROL_PORT=9100

EXPOSE 9100
EXPOSE 20001-20036

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-m", "gcc_redfish_sim.simulator.healthcheck"]

CMD ["gcc-bmc-simulator"]
