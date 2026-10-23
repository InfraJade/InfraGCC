"""Redfish client: sessions, re-login, Basic fallback, retries/backoff, single-flight, $expand."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from conftest import HPE, TreeBmc, creds, tree_client

from gcc_collector.redfish.client import (
    AuthError,
    BmcUnreachable,
    NotFound,
    RedfishClient,
    RedfishHTTPError,
    expand_query,
    parse_bmc_host,
)


class Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10.20.1.11", "https://10.20.1.11"),
        ("bmc01.dc.local:8443", "https://bmc01.dc.local:8443"),
        ("http://bmc-simulator:20001", "http://bmc-simulator:20001"),
        ("https://10.0.0.5/", "https://10.0.0.5"),
        ("https://10.0.0.5/redfish/v1/", "https://10.0.0.5"),
        ("  http://redfish-dell:8000  ", "http://redfish-dell:8000"),
    ],
)
def test_parse_bmc_host(value: str, expected: str) -> None:
    assert parse_bmc_host(value) == expected


@pytest.mark.parametrize("value", ["", "ftp://x", "http://"])
def test_parse_bmc_host_rejects(value: str) -> None:
    with pytest.raises(ValueError):
        parse_bmc_host(value)


def test_expand_query() -> None:
    assert expand_query({}) is None
    assert expand_query({"ProtocolFeaturesSupported": {"ExpandQuery": {"NoLinks": False}}}) is None
    assert expand_query({"ProtocolFeaturesSupported": {"ExpandQuery": {"NoLinks": True}}}) == "."
    full = {"ProtocolFeaturesSupported": {"ExpandQuery": {"NoLinks": True, "Levels": True, "MaxLevels": 1}}}
    assert expand_query(full) == ".($levels=1)"


async def test_session_login_token_and_delete_on_close(dell_bmc: TreeBmc) -> None:
    client = tree_client(dell_bmc)
    system = await client.get("/redfish/v1/Systems/System.Embedded.1")
    assert system["Id"] == "System.Embedded.1"
    assert client.auth_mode == "session"
    assert dell_bmc.logins == 1
    assert dell_bmc.requests[-1].headers["X-Auth-Token"] == "token-1"
    await client.close()
    assert dell_bmc.deleted == ["/redfish/v1/SessionService/Sessions/1"]


async def test_relogin_once_on_401(dell_bmc: TreeBmc) -> None:
    client = tree_client(dell_bmc)
    await client.get("/redfish/v1/Systems")
    dell_bmc.expire_sessions()  # the BMC dropped the session (timeout / reboot)
    system = await client.get("/redfish/v1/Systems/System.Embedded.1")
    assert system["Id"] == "System.Embedded.1"
    assert dell_bmc.logins == 2
    await client.close()


async def test_401_after_relogin_is_auth_error() -> None:
    calls = {"login": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            calls["login"] += 1
            return httpx.Response(201, headers={"X-Auth-Token": f"t{calls['login']}"})
        return httpx.Response(401)

    client = RedfishClient("http://bmc.test", creds(), transport=httpx.MockTransport(handler))
    with pytest.raises(AuthError):
        await client.get("/redfish/v1/Systems")
    assert calls["login"] == 2  # initial login + exactly one re-login
    await client.close()


async def test_login_rejected_is_auth_error() -> None:
    client = RedfishClient(
        "http://bmc.test", creds(), transport=httpx.MockTransport(lambda r: httpx.Response(401))
    )
    with pytest.raises(AuthError):
        await client.get("/redfish/v1/Systems")
    await client.close()


@pytest.mark.parametrize("status", [404, 405, 501])
async def test_basic_auth_fallback(status: int) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(status)
        if not request.headers.get("Authorization", "").startswith("Basic "):
            return httpx.Response(401)
        return httpx.Response(200, json={"Id": "1"})

    client = RedfishClient("bmc.test", creds(), transport=httpx.MockTransport(handler))
    assert (await client.get("/redfish/v1/Systems/1"))["Id"] == "1"
    assert client.auth_mode == "basic"
    assert str(seen[-1].url).startswith("https://bmc.test/")  # bare host means https
    await client.close()


async def test_basic_fallback_against_tree() -> None:
    bmc = TreeBmc(HPE, sessions=False)
    client = tree_client(bmc)
    assert (await client.get("/redfish/v1/Systems/1"))["Id"] == "1"
    assert client.auth_mode == "basic"
    await client.close()


async def test_connect_errors_retry_with_backoff_then_unreachable() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("refused", request=request)

    sleeps = Sleeps()
    client = RedfishClient(
        "http://bmc.test",
        creds(),
        transport=httpx.MockTransport(handler),
        max_retries=3,
        backoff_base=0.5,
        backoff_cap=1.5,
        sleep=sleeps,
    )
    with pytest.raises(BmcUnreachable):
        await client.get("/redfish/v1/Systems")
    assert attempts["n"] == 4  # 1 + 3 retries, all on the login request
    assert len(sleeps.delays) == 3
    caps = [0.5, 1.0, 1.5]  # min(cap, base * 2^attempt)
    assert all(0 <= d <= c for d, c in zip(sleeps.delays, caps, strict=True))
    await client.close()


async def test_5xx_is_retried_then_succeeds(dell_bmc: TreeBmc) -> None:
    failures = {"left": 2}
    inner = dell_bmc.transport()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and failures["left"]:
            failures["left"] -= 1
            return httpx.Response(503)
        return await inner.handle_async_request(request)

    sleeps = Sleeps()
    client = RedfishClient("http://bmc.test", creds(), transport=httpx.MockTransport(handler), sleep=sleeps)
    assert (await client.get("/redfish/v1/Systems"))["Members@odata.count"] == 1
    assert len(sleeps.delays) == 2
    await client.close()


async def test_5xx_after_retries_raises_http_error() -> None:
    sleeps = Sleeps()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, headers={"X-Auth-Token": "t"})
        return httpx.Response(500)

    client = RedfishClient(
        "http://bmc.test", creds(), transport=httpx.MockTransport(handler), max_retries=1, sleep=sleeps
    )
    with pytest.raises(RedfishHTTPError) as err:
        await client.get("/redfish/v1/Systems")
    assert err.value.status == 500
    assert len(sleeps.delays) == 1
    await client.close()


async def test_read_timeout_is_not_retried() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, headers={"X-Auth-Token": "t"})
        attempts["n"] += 1
        raise httpx.ReadTimeout("slow", request=request)

    sleeps = Sleeps()
    client = RedfishClient("http://bmc.test", creds(), transport=httpx.MockTransport(handler), sleep=sleeps)
    with pytest.raises(BmcUnreachable):
        await client.get("/redfish/v1/Systems")
    assert attempts["n"] == 1
    assert sleeps.delays == []
    await client.close()


async def test_timeout_setting_is_20s_by_default() -> None:
    client = RedfishClient("bmc.test", creds())
    assert client._http.timeout.read == 20.0
    await client.close()


async def test_not_found(dell_bmc: TreeBmc) -> None:
    client = tree_client(dell_bmc)
    with pytest.raises(NotFound):
        await client.get("/redfish/v1/Nope")
    await client.close()


class Concurrency:
    """Async handler that records how many requests overlap."""

    def __init__(self) -> None:
        self.current = 0
        self.peak = 0
        self.by_host: dict[str, int] = {}
        self.peak_by_host: dict[str, int] = {}

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        self.current += 1
        self.by_host[host] = self.by_host.get(host, 0) + 1
        self.peak = max(self.peak, self.current)
        self.peak_by_host[host] = max(self.peak_by_host.get(host, 0), self.by_host[host])
        await asyncio.sleep(0.01)
        self.current -= 1
        self.by_host[host] -= 1
        if request.method == "POST":
            return httpx.Response(201, headers={"X-Auth-Token": "t"})
        return httpx.Response(200, json={"path": request.url.path})


async def test_single_request_in_flight_per_bmc() -> None:
    probe = Concurrency()
    client = RedfishClient(
        "http://bmc.test", creds(), transport=httpx.MockTransport(probe), semaphore=asyncio.Semaphore(50)
    )
    results = await asyncio.gather(*(client.get(f"/redfish/v1/x/{i}") for i in range(10)))
    assert [r["path"] for r in results] == [f"/redfish/v1/x/{i}" for i in range(10)]
    assert probe.peak == 1
    await client.close()


async def test_global_semaphore_caps_parallel_bmcs() -> None:
    probe = Concurrency()
    semaphore = asyncio.Semaphore(2)
    clients = [
        RedfishClient(
            f"http://bmc{i}.test", creds(), transport=httpx.MockTransport(probe), semaphore=semaphore
        )
        for i in range(5)
    ]
    await asyncio.gather(*(c.get(f"/redfish/v1/x/{j}") for c in clients for j in range(3)))
    assert probe.peak == 2
    assert max(probe.peak_by_host.values()) == 1
    for c in clients:
        await c.close()


async def test_expand_used_only_when_advertised(dell_bmc: TreeBmc) -> None:
    client = tree_client(dell_bmc)
    await client.get_root()
    assert client.expand == ".($levels=1)"
    before = len(dell_bmc.requests)
    members = await client.get_collection("/redfish/v1/Systems/System.Embedded.1/Memory")
    assert len(members) == 16
    assert len(dell_bmc.requests) - before == 1
    assert "%24expand" in str(dell_bmc.requests[-1].url) or "$expand" in str(dell_bmc.requests[-1].url)
    await client.close()

    hpe = TreeBmc(HPE)
    client = tree_client(hpe)
    await client.get_root()
    assert client.expand is None
    before = len(hpe.requests)
    members = await client.get_collection("/redfish/v1/Systems/1/Memory")
    assert len(members) == 12
    assert len(hpe.requests) - before == 13  # collection + one GET per member
    assert not any("expand" in str(r.url) for r in hpe.requests)
    await client.close()


async def test_expand_rejected_falls_back(dell_bmc: TreeBmc) -> None:
    inner = dell_bmc.transport()

    async def handler(request: httpx.Request) -> httpx.Response:
        if "expand" in str(request.url):
            return httpx.Response(400)
        return await inner.handle_async_request(request)

    client = RedfishClient("http://bmc.test", creds(), transport=httpx.MockTransport(handler))
    await client.get_root()
    members = await client.get_collection("/redfish/v1/Systems/System.Embedded.1/Processors")
    assert len(members) == 2
    assert client.expand is None
    await client.close()


async def test_hung_bmc_times_out_without_blocking_others(dell_bmc: TreeBmc) -> None:
    """A BMC that accepts the TCP connection and never answers becomes a failed poll after the timeout."""
    accepted: list[asyncio.StreamWriter] = []

    async def hang(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.append(writer)
        await asyncio.sleep(3600)

    server = await asyncio.start_server(hang, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    semaphore = asyncio.Semaphore(50)
    hung = RedfishClient(f"http://127.0.0.1:{port}", creds(), timeout=0.3, semaphore=semaphore)
    healthy = tree_client(dell_bmc, semaphore=semaphore)
    loop = asyncio.get_running_loop()
    started = loop.time()
    results = await asyncio.gather(
        hung.get("/redfish/v1/Systems"), healthy.get("/redfish/v1/Systems"), return_exceptions=True
    )
    assert isinstance(results[0], BmcUnreachable)
    assert isinstance(results[1], dict)
    assert loop.time() - started < 5
    assert accepted  # the connection was accepted; the read timed out
    await hung.close()
    await healthy.close()
    for writer in accepted:
        writer.close()
    server.close()
