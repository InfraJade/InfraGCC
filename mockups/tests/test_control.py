"""Control API and Teams webhook sink."""

from __future__ import annotations

import pytest

from gcc_redfish_sim.simulator.config import ConfigError, SimConfig
from gcc_redfish_sim.simulator.control import TeamsSink
from gcc_redfish_sim.simulator.fleet import Fleet

from .conftest import Client


async def test_health_and_bmcs(control_client: Client) -> None:
    health = await (await control_client.get("/health")).json()
    assert health["status"] == "ok"
    assert health["bmcs"] == 6
    assert health["ports"] == [30001, 30006]
    bmcs = await (await control_client.get("/bmcs")).json()
    assert [b["index"] for b in bmcs] == [1, 2, 3, 4, 5, 6]
    assert [b["port"] for b in bmcs] == [30001, 30002, 30003, 30004, 30005, 30006]
    assert [b["vendor"] for b in bmcs[:3]] == ["Dell", "HPE", "Lenovo"]
    assert len({b["serial"] for b in bmcs}) == 6
    one = await (await control_client.get("/bmcs/2")).json()
    assert one["model"] == "ProLiant DL380 Gen10"
    assert (await control_client.get("/bmcs/7")).status == 404
    assert (await control_client.get("/bmcs/x")).status == 400


async def test_fault_lifecycle(control_client: Client, fleet: Fleet) -> None:
    resp = await control_client.post("/faults", json={"bmc": 1, "kind": "fan_slow", "duration_s": 600})
    assert resp.status == 201
    fault = await resp.json()
    assert fault["kind"] == "fan_slow"
    assert fault["port"] == 30001
    assert fault["expires_at"] is not None
    assert fault["target"].startswith("Fan.Embedded.")
    assert fleet.bmcs[1].state.system_health() == "Critical"

    resp = await control_client.post("/faults", json={"bmc": 1, "kind": "fan_slow"})
    assert resp.status == 409
    assert resp.content_type == "application/problem+json"
    for bad in (
        {"bmc": 1, "kind": "meltdown"},
        {"bmc": "1", "kind": "fan_slow"},
        {"bmc": 1},
        {"bmc": 1, "kind": "psu_warning", "duration_s": -5},
        {"bmc": 1, "kind": "psu_warning", "duration_s": "long"},
    ):
        assert (await control_client.post("/faults", json=bad)).status == 400, bad
    assert (await control_client.post("/faults", json={"bmc": 42, "kind": "fan_slow"})).status == 404
    assert (await control_client.post("/faults", data=b"nope")).status == 400

    await control_client.post("/faults", json={"bmc": 2, "kind": "power_off"})
    faults = await (await control_client.get("/faults")).json()
    assert {f["kind"] for f in faults} == {"fan_slow", "power_off"}
    bmcs = await (await control_client.get("/bmcs")).json()
    assert bmcs[0]["faults"][0]["kind"] == "fan_slow"
    assert bmcs[1]["power_state"] == "Off"

    resp = await control_client.delete(f"/faults/{fault['id']}")
    assert resp.status == 200
    assert fleet.bmcs[1].state.system_health() == "OK"
    assert (await control_client.delete(f"/faults/{fault['id']}")).status == 404
    resp = await control_client.delete("/faults")
    assert (await resp.json()) == {"cleared": 1}
    assert (await (await control_client.get("/faults")).json()) == []


async def test_set_load(control_client: Client, fleet: Fleet) -> None:
    resp = await control_client.post("/bmcs/3/load", json={"load": 0.9})
    assert resp.status == 200
    body = await resp.json()
    assert body["load"] == 0.9
    assert body["load_pinned"] is True
    fleet.step()
    assert fleet.bmcs[3].state.load == 0.9
    for bad in ({"load": 1.5}, {"load": "high"}, {"load": True}):
        assert (await control_client.post("/bmcs/3/load", json=bad)).status == 400
    body = await (await control_client.post("/bmcs/3/load", json={"load": None})).json()
    assert body["load_pinned"] is False


async def test_teams_sink(control_client: Client) -> None:
    for n in range(3):
        resp = await control_client.post(
            f"/webhooks/teams/{'PNQ1' if n < 2 else 'HYD1'}", json={"text": f"m{n}"}
        )
        assert resp.status == 200
        assert await resp.text() == "1"
    assert (await control_client.post("/webhooks/teams/PNQ1", data=b"not json")).status == 400
    posts = await (await control_client.get("/webhooks/teams")).json()
    assert [p["body"]["text"] for p in posts] == ["m2", "m1", "m0"]
    pnq = await (await control_client.get("/webhooks/teams?channel=PNQ1")).json()
    assert [p["body"]["text"] for p in pnq] == ["m1", "m0"]
    one = await (await control_client.get("/webhooks/teams?limit=1")).json()
    assert len(one) == 1
    assert (await (await control_client.delete("/webhooks/teams")).json()) == {"cleared": 3}


def test_teams_sink_keeps_last_500() -> None:
    sink = TeamsSink()
    for n in range(520):
        sink.add("x", {"n": n})
    posts = sink.list()
    assert len(posts) == 500
    assert posts[0]["body"] == {"n": 519}
    assert posts[-1]["body"] == {"n": 20}


def test_config_from_env() -> None:
    cfg = SimConfig.from_env({})
    assert (cfg.count, cfg.base_port, cfg.control_port) == (36, 20000, 9100)
    assert (cfg.username, cfg.password, cfg.fault_rate_per_hour, cfg.seed) == (
        "gcc-monitor",
        "dev-bmc-pw",
        0.05,
        None,
    )
    cfg = SimConfig.from_env({"SIM_COUNT": "500", "SIM_BASE_PORT": "21000", "SIM_SEED": "7"})
    assert cfg.port_for(500) == 21500
    assert cfg.seed == "7"
    for bad in (
        {"SIM_COUNT": "0"},
        {"SIM_COUNT": "x"},
        {"SIM_BASE_PORT": "65500"},
        {"SIM_CONTROL_PORT": "20005"},
    ):
        with pytest.raises(ConfigError):
            SimConfig.from_env(bad)


def test_fleet_of_500_is_cheap() -> None:
    fleet = Fleet(SimConfig(count=500, seed="big", fault_rate_per_hour=0.0))
    assert len({b.state.serial for b in fleet.bmcs.values()}) == 500
    assert len({b.state.bmc_mac for b in fleet.bmcs.values()}) == 500
    assert len({b.port for b in fleet.bmcs.values()}) == 500
    fleet.step()
    assert all(b._tree is None for b in fleet.bmcs.values())  # rendering is lazy
