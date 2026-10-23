"""Shared fixtures: an httpx transport that serves the mockup trees like a BMC (sessions, $expand)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from gcc_collector.credentials import Credentials
from gcc_collector.poller import ServerPoller
from gcc_collector.redfish.client import RedfishClient
from gcc_collector.schema import ServerConfig

TREES = Path(__file__).resolve().parents[2] / "mockups" / "trees"
DELL = "dell-poweredge-r750"
HPE = "hpe-proliant-dl380-gen10"
LENOVO = "lenovo-thinksystem-sr650-v3"
FIXED_NOW = datetime(2026, 10, 22, 10, 0, 1, tzinfo=UTC)

Json = dict[str, Any]


def creds() -> Credentials:
    return Credentials(username="gcc-monitor", password=SecretStr("dev-bmc-pw"))


class TreeBmc:
    """Serves ``mockups/trees/<tree>`` over an httpx MockTransport.

    - ``POST /redfish/v1/SessionService/Sessions`` returns a token (unless ``sessions=False``: 405);
    - every other request must carry the token (or Basic auth) or gets 401;
    - ``?$expand=...`` inlines collection members when the tree's root advertises ExpandQuery;
    - ``overrides`` replaces documents by path, ``missing`` makes paths 404.
    """

    def __init__(self, tree: str, *, sessions: bool = True, expand: bool | None = None) -> None:
        self.root_dir = TREES / tree
        self.sessions = sessions
        self.overrides: dict[str, Json] = {}
        self.missing: set[str] = set()
        self.requests: list[httpx.Request] = []
        self.tokens: set[str] = set()
        self.logins = 0
        self.deleted: list[str] = []
        root = self.load("/redfish/v1")
        self.expand = bool(root and root.get("ProtocolFeaturesSupported")) if expand is None else expand

    def load(self, path: str) -> Json | None:
        path = path.rstrip("/")
        if path in self.missing:
            return None
        if path in self.overrides:
            return self.overrides[path]
        file = self.root_dir / path.lstrip("/") / "index.json"
        if not file.is_file():
            return None
        data: Json = json.loads(file.read_text(encoding="utf-8"))
        return data

    def expire_sessions(self) -> None:
        self.tokens.clear()

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.rstrip("/") or "/"
        if request.method == "POST" and path == "/redfish/v1/SessionService/Sessions":
            if not self.sessions:
                return httpx.Response(405)
            body = json.loads(request.content)
            if body != {"UserName": "gcc-monitor", "Password": "dev-bmc-pw"}:
                return httpx.Response(401)
            self.logins += 1
            token = f"token-{self.logins}"
            self.tokens.add(token)
            return httpx.Response(
                201,
                headers={
                    "X-Auth-Token": token,
                    "Location": f"/redfish/v1/SessionService/Sessions/{self.logins}",
                },
                json={"Id": str(self.logins)},
            )
        if path != "/redfish/v1" and not self._authorized(request):
            return httpx.Response(401)
        if request.method == "DELETE":
            self.deleted.append(path)
            return httpx.Response(204)
        doc = self.load(path)
        if doc is None:
            return httpx.Response(404, json={"error": {"code": "Base.1.0.ResourceMissingAtURI"}})
        if "$expand" in request.url.query.decode() and self.expand and isinstance(doc.get("Members"), list):
            members = []
            for member in doc["Members"]:
                target = self.load(member.get("@odata.id", "")) if set(member) == {"@odata.id"} else None
                members.append(target if target is not None else member)
            doc = {**doc, "Members": members}
        return httpx.Response(200, json=doc)

    def _authorized(self, request: httpx.Request) -> bool:
        token = request.headers.get("X-Auth-Token")
        if token is not None:
            return token in self.tokens
        auth = request.headers.get("Authorization", "")
        return auth.startswith("Basic ") and not self.sessions

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def get_count(self, predicate: Callable[[str], bool] | None = None) -> int:
        return sum(
            1 for r in self.requests if r.method == "GET" and (predicate is None or predicate(r.url.path))
        )


@pytest.fixture
def dell_bmc() -> TreeBmc:
    return TreeBmc(DELL)


@pytest.fixture
def hpe_bmc() -> TreeBmc:
    return TreeBmc(HPE)


@pytest.fixture
def lenovo_bmc() -> TreeBmc:
    return TreeBmc(LENOVO)


def tree_client(bmc: TreeBmc, **kwargs: Any) -> RedfishClient:
    return RedfishClient("http://bmc.test", creds(), transport=bmc.transport(), **kwargs)


def tree_poller(bmc: TreeBmc, server_id: int = 1) -> ServerPoller:
    server = ServerConfig(id=server_id, bmc_host="http://bmc.test")
    return ServerPoller(server, tree_client(bmc), clock=lambda: FIXED_NOW)
