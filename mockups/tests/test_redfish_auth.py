"""Authentication like a real BMC: open service root, sessions with X-Auth-Token, HTTP Basic."""

from __future__ import annotations

from .conftest import SESSIONS, USER, ClientFactory, basic, make_bmc, session_token


async def test_service_root_is_open(bmc_client: ClientFactory) -> None:
    client = await bmc_client(make_bmc(1))
    for path in ("/redfish", "/redfish/", "/redfish/v1", "/redfish/v1/"):
        resp = await client.get(path)
        assert resp.status == 200, path
        assert resp.headers["OData-Version"] == "4.0"
    root = await (await client.get("/redfish/v1")).json()
    assert root["Vendor"] == "Dell"
    assert root["Links"]["Sessions"]["@odata.id"] == SESSIONS
    assert (await (await client.get("/redfish")).json()) == {"v1": "/redfish/v1/"}


async def test_everything_else_needs_auth(bmc_client: ClientFactory) -> None:
    client = await bmc_client(make_bmc(1))
    for path in ("/redfish/v1/Systems", "/redfish/v1/Chassis/System.Embedded.1/Thermal", SESSIONS):
        resp = await client.get(path)
        assert resp.status == 401, path
        body = await resp.json()
        assert body["error"]["@Message.ExtendedInfo"][0]["MessageId"].endswith("NoValidSession")
    assert (await client.get("/redfish/v1/Systems", headers={"X-Auth-Token": "bogus"})).status == 401
    assert (await client.get("/redfish/v1/Systems", headers=basic(password="wrong"))).status == 401
    assert (await client.get("/redfish/v1/Systems", headers={"Authorization": "Basic !!!"})).status == 401


async def test_session_lifecycle(bmc_client: ClientFactory) -> None:
    client = await bmc_client(make_bmc(2))
    resp = await client.post(SESSIONS, json={"UserName": USER, "Password": "wrong"})
    assert resp.status == 401
    resp = await client.post(SESSIONS, json={"UserName": USER})
    assert resp.status == 400
    resp = await client.post(SESSIONS, data=b"{not json")
    assert resp.status == 400

    resp = await client.post(SESSIONS + "/", json={"UserName": USER, "Password": "test-pw"})
    assert resp.status == 201
    token = resp.headers["X-Auth-Token"]
    location = resp.headers["Location"]
    assert location.startswith(SESSIONS + "/")
    session = await resp.json()
    assert session["@odata.id"] == location
    assert session["UserName"] == USER
    auth = {"X-Auth-Token": token}

    assert (await client.get("/redfish/v1/Systems/1", headers=auth)).status == 200
    assert (await client.get(location, headers=auth)).status == 200
    sessions = await (await client.get(SESSIONS, headers=auth)).json()
    assert sessions["Members"] == [{"@odata.id": location}]
    assert sessions["Members@odata.count"] == 1

    other = await session_token(client)
    resp = await client.delete(location, headers={"X-Auth-Token": other})
    assert resp.status == 204
    assert (await client.get("/redfish/v1/Systems/1", headers=auth)).status == 401
    assert (await client.get("/redfish/v1/Systems/1", headers={"X-Auth-Token": other})).status == 200
    assert (await client.delete(location, headers={"X-Auth-Token": other})).status == 404


async def test_basic_auth(bmc_client: ClientFactory) -> None:
    client = await bmc_client(make_bmc(3))
    resp = await client.get("/redfish/v1/Systems/1", headers=basic())
    assert resp.status == 200
    assert (await resp.json())["Manufacturer"] == "Lenovo"


async def test_not_found_and_method_not_allowed(bmc_client: ClientFactory) -> None:
    client = await bmc_client(make_bmc(1))
    resp = await client.get("/redfish/v1/Systems/Nope", headers=basic())
    assert resp.status == 404
    assert (await resp.json())["error"]["@Message.ExtendedInfo"][0]["MessageId"].endswith("ResourceNotFound")
    resp = await client.patch("/redfish/v1/Systems/System.Embedded.1", headers=basic(), json={})
    assert resp.status == 405
    assert resp.headers["Allow"] == "GET, HEAD"
