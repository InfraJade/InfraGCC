"""Every simulated model serves a closed tree: each @odata.id link resolves (like the mockup smoke test),
and the simulator serves exactly the paths of the static mockup trees."""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Any

import pytest

from gcc_redfish_sim.catalog import make_state
from gcc_redfish_sim.generate import DEFAULT_OUT, REFERENCE_TREES
from gcc_redfish_sim.simulator.faults import FaultKind
from gcc_redfish_sim.simulator.fleet import Fleet
from gcc_redfish_sim.tree import build_tree

from .conftest import MODEL_INDEXES, T0, ClientFactory, make_bmc, make_config, session_token


def _links(node: Any) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("@odata.id", "DataSourceUri") and isinstance(value, str):
                found.append(value.split("#", 1)[0])
            else:
                found.extend(_links(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_links(item))
    return found


async def _crawl(client: Any, token: str) -> set[str]:
    seen: set[str] = set()
    queue = deque(["/redfish/v1"])
    while queue:
        path = queue.popleft()
        if path in seen:
            continue
        seen.add(path)
        resp = await client.get(path, headers={"X-Auth-Token": token})
        assert resp.status == 200, f"{path} -> {resp.status}"
        body = await resp.json()
        assert body["@odata.id"] == path
        queue.extend(link for link in _links(body) if link not in seen)
    return seen


@pytest.mark.parametrize("model_key", list(MODEL_INDEXES))
async def test_every_link_resolves(model_key: str, bmc_client: ClientFactory) -> None:
    fleet = Fleet(make_config(), now=T0)
    index = MODEL_INDEXES[model_key]
    for kind in (FaultKind.FAN_SLOW, FaultKind.CRITICAL_SEL, FaultKind.NIC_DOWN, FaultKind.DRIVE_WEAR):
        fleet.raise_fault(index, kind, now=T0)
    bmc = fleet.bmcs[index]
    client = await bmc_client(bmc)
    token = await session_token(client)
    seen = await _crawl(client, token)
    missing = set(bmc.tree()) - seen
    assert not missing, f"unreachable resources: {sorted(missing)[:5]}"


def _static_paths(tree_dir: Path) -> set[str]:
    out = set()
    for f in tree_dir.rglob("index.json"):
        rel = f.parent.relative_to(tree_dir).as_posix()
        out.add("/" + rel)
    return out


@pytest.mark.parametrize(("name", "model_key", "_index"), REFERENCE_TREES)
def test_simulator_serves_the_static_tree_paths(name: str, model_key: str, _index: int) -> None:
    static = _static_paths(DEFAULT_OUT / name) - {"/redfish"}
    simulated = set(make_bmc(MODEL_INDEXES[model_key]).tree())
    assert simulated == static


@pytest.mark.parametrize(("name", "model_key", "index"), REFERENCE_TREES)
def test_static_trees_are_up_to_date(name: str, model_key: str, index: int) -> None:
    tree = build_tree(make_state(model_key, index))
    root = DEFAULT_OUT / name
    for path, body in tree.items():
        on_disk = (root / path.lstrip("/") / "index.json").read_bytes()
        assert b"\r\n" not in on_disk, f"{path}: CRLF line endings"
        assert json.loads(on_disk) == body, f"{path} differs: run gcc-generate-mockups"
