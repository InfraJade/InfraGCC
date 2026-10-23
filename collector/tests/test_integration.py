"""Polls a live Redfish service (the DMTF mockup server or the BMC simulator).

Skipped unless ``GCC_IT_REDFISH_URL`` is set, e.g.::

    docker run -d --name gccdev-collector-dmtf -p 18011:8000 \\
        -v "<repo>/mockups/trees/dell-poweredge-r750:/mockup:ro" \\
        dmtf/redfish-mockup-server:latest -D /mockup -H 0.0.0.0 -p 8000
    GCC_IT_REDFISH_URL=http://localhost:18011 uv run pytest -m integration
"""

from __future__ import annotations

import os

import pytest
from conftest import creds

from gcc_collector.adapters import ALL_KINDS
from gcc_collector.poller import ServerPoller
from gcc_collector.redfish.client import RedfishClient
from gcc_collector.schema import ServerConfig

URL = os.environ.get("GCC_IT_REDFISH_URL", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not URL, reason="GCC_IT_REDFISH_URL is not set"),
]


async def test_poll_live_redfish_service() -> None:
    # The DMTF mockup server is slow (seconds per $expand on Docker Desktop), so allow more than 20 s.
    client = RedfishClient(URL, creds(), verify=False, timeout=float(os.environ.get("GCC_IT_TIMEOUT", "60")))
    poller = ServerPoller(ServerConfig(id=1, bmc_host=URL), client)
    first = await poller.poll(ALL_KINDS)
    assert first.ok, first.error
    payload = first.payload
    metrics = {r.metric for r in payload.readings or []}
    assert {
        "inlet_temp_c",
        "cpu_temp_c",
        "power_w",
        "power_state",
        "system_health",
        "bmc_reachable",
    } <= metrics
    assert payload.identity is not None and payload.identity.vendor in ("Dell", "HPE", "Lenovo")
    assert payload.components and payload.firmware

    second = await poller.poll(frozenset({"sensors", "health"}))
    assert second.ok, second.error
    assert any(r.metric == "fan_health" for r in second.payload.readings or [])
    await poller.close()
