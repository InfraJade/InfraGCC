"""$expand follows each vendor's ExpandQuery capabilities: Dell 1 level, Lenovo 2 levels, HPE ignores it."""

from __future__ import annotations

from typing import Any

import pytest

from gcc_redfish_sim.simulator.redfish import ExpandError, parse_expand

from .conftest import ClientFactory, basic, make_bmc

Json = dict[str, Any]
DELL_CAPS = {"ExpandAll": True, "Levels": True, "Links": True, "MaxLevels": 1, "NoLinks": True}


def _is_link(node: Json) -> bool:
    return set(node) == {"@odata.id"}


def test_parse_expand() -> None:
    assert parse_expand("*", DELL_CAPS) == ("*", 1)
    assert parse_expand(".", DELL_CAPS) == (".", 1)
    assert parse_expand("~", DELL_CAPS) == ("~", 1)
    assert parse_expand(".($levels=1)", DELL_CAPS) == (".", 1)
    assert parse_expand("*($levels=2)", {**DELL_CAPS, "MaxLevels": 2}) == ("*", 2)
    for bad in ("*($levels=2)", ".($levels=0)", "x", "*($levels=)", ""):
        with pytest.raises(ExpandError):
            parse_expand(bad, DELL_CAPS)
    with pytest.raises(ExpandError):
        parse_expand("~", {**DELL_CAPS, "Links": False})


async def _get(client: Any, path: str) -> tuple[int, Json]:
    resp = await client.get(path, headers=basic())
    return resp.status, await resp.json()


async def test_dell_expands_one_level(bmc_client: ClientFactory) -> None:
    client = await bmc_client(make_bmc(1))
    status, body = await _get(client, "/redfish/v1/Systems?$expand=.($levels=1)")
    assert status == 200
    system = body["Members"][0]
    assert system["Model"] == "PowerEdge R750"
    assert _is_link(system["Processors"])  # only one level
    status, body = await _get(client, "/redfish/v1/Systems?$expand=*($levels=2)")
    assert status == 400
    assert body["error"]["@Message.ExtendedInfo"][0]["MessageId"].endswith("QueryParameterOutOfRange")


async def test_dot_skips_links_and_star_follows_them(bmc_client: ClientFactory) -> None:
    client = await bmc_client(make_bmc(1))
    path = "/redfish/v1/Systems/System.Embedded.1"
    _, dot = await _get(client, f"{path}?$expand=.")
    assert dot["Processors"]["Members@odata.count"] == 2
    assert _is_link(dot["Links"]["Chassis"][0])
    _, star = await _get(client, f"{path}?$expand=*")
    assert star["Links"]["Chassis"][0]["ChassisType"] == "RackMount"
    assert star["Processors"]["Members@odata.count"] == 2
    _, tilde = await _get(client, f"{path}?$expand=~")
    assert _is_link(tilde["Processors"])
    assert tilde["Links"]["Chassis"][0]["ChassisType"] == "RackMount"


async def test_lenovo_expands_two_levels(bmc_client: ClientFactory) -> None:
    client = await bmc_client(make_bmc(3))
    status, body = await _get(client, "/redfish/v1/Chassis/1/ThermalSubsystem?$expand=.($levels=2)")
    assert status == 200
    fan = body["Fans"]["Members"][0]
    assert fan["SpeedPercent"]["SpeedRPM"] > 0
    status, body = await _get(client, "/redfish/v1/Chassis/1/ThermalSubsystem?$expand=.($levels=1)")
    assert _is_link(body["Fans"]["Members"][0])
    status, _ = await _get(client, "/redfish/v1/Chassis/1?$expand=.($levels=3)")
    assert status == 400


async def test_hpe_ignores_expand(bmc_client: ClientFactory) -> None:
    client = await bmc_client(make_bmc(2))
    _, plain = await _get(client, "/redfish/v1/Systems")
    for query in ("*", ".($levels=1)", "garbage"):
        status, body = await _get(client, f"/redfish/v1/Systems?$expand={query}")
        assert status == 200
        assert body == plain
        assert _is_link(body["Members"][0])
    _, root = await _get(client, "/redfish/v1")
    assert "ProtocolFeaturesSupported" not in root


async def test_expand_needs_auth_on_service_root(bmc_client: ClientFactory) -> None:
    client = await bmc_client(make_bmc(1))
    body = await (await client.get("/redfish/v1?$expand=*")).json()
    assert _is_link(body["Systems"])
