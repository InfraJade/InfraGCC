"""The Redfish HTTP service of one virtual BMC.

Behaves like a real BMC where the collector can tell the difference:
  - `/redfish` and `/redfish/v1` answer without credentials; everything else needs a session token
    (`X-Auth-Token`) or HTTP Basic, else 401 with a Redfish error body.
  - `POST /redfish/v1/SessionService/Sessions` {"UserName","Password"} -> 201, `X-Auth-Token`, `Location`;
    the session resource supports GET and DELETE; sessions expire after 30 min idle.
  - `$expand` follows the profile's `ProtocolFeaturesSupported.ExpandQuery` (Dell 1 level, Lenovo 2,
    HPE none: the query is ignored, as iLO 5 does). Supported forms: `*`, `.`, `~`, each optionally with
    `($levels=n)`.
  - A BMC with the `bmc_unresponsive` fault accepts connections and then never answers until cleared.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aiohttp import web

from gcc_redfish_sim.simulator.bmc import SESSIONS_PATH, Json, VirtualBmc
from gcc_redfish_sim.tree import R

BMC_KEY = web.AppKey("bmc", VirtualBmc)


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str


CREDENTIALS_KEY = web.AppKey("credentials", Credentials)

_BASE = "Base.1.16"
_EXPAND_RE = re.compile(r"^(?P<mode>[*.~])(?:\(\$levels=(?P<levels>\d+)\))?$")
_UNAUTHENTICATED = {"/redfish", R}
_READ = ("GET", "HEAD")


# --------------------------------------------------------------------------------- responses


def json_response(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> web.Response:
    return web.Response(
        body=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        status=status,
        content_type="application/json",
        charset="utf-8",
        headers={"OData-Version": "4.0", "Cache-Control": "no-cache", **(headers or {})},
    )


def redfish_error(
    status: int, message_id: str, message: str, headers: dict[str, str] | None = None
) -> web.Response:
    body = {
        "error": {
            "code": f"{_BASE}.GeneralError",
            "message": "A general error has occurred. See ExtendedInfo for more information.",
            "@Message.ExtendedInfo": [
                {
                    "@odata.type": "#Message.v1_1_1.Message",
                    "MessageId": f"{_BASE}.{message_id}",
                    "Message": message,
                    "Severity": "Critical",
                    "MessageSeverity": "Critical",
                    "Resolution": "None.",
                }
            ],
        }
    }
    return json_response(body, status, headers)


def _unauthorized() -> web.Response:
    return redfish_error(
        401,
        "NoValidSession",
        "There is no valid session established with the implementation.",
        {"WWW-Authenticate": 'Basic realm="RedfishService"'},
    )


# ---------------------------------------------------------------------------------- $expand


class ExpandError(ValueError):
    pass


def parse_expand(value: str, capabilities: Json) -> tuple[str, int]:
    """(mode, levels) for a `$expand` value, validated against the service's ExpandQuery capabilities."""
    match = _EXPAND_RE.match(value.strip())
    if match is None:
        raise ExpandError(f"The value '{value}' for the query parameter $expand is not valid.")
    mode = match["mode"]
    supported = {"*": "ExpandAll", ".": "NoLinks", "~": "Links"}[mode]
    if not capabilities.get(supported, False):
        raise ExpandError(f"The value '{value}' for the query parameter $expand is not supported.")
    levels = 1
    if match["levels"] is not None:
        if not capabilities.get("Levels", False):
            raise ExpandError("The $levels option of the query parameter $expand is not supported.")
        levels = int(match["levels"])
    max_levels = int(capabilities.get("MaxLevels", 1))
    if not 1 <= levels <= max_levels:
        raise ExpandError(
            f"The value '{levels}' for the query parameter $levels is out of range 1 to {max_levels}."
        )
    return mode, levels


def expand(body: Json, mode: str, levels: int, resolve: Any) -> Json:
    """Replace link objects ({"@odata.id": ...} alone) with the resources they point to.

    `*` expands every link, `.` only links outside `Links` (subordinate resources), `~` only those inside
    `Links`. Links with a fragment (`...#/Fans/0`) point into a resource and are left alone.
    """

    def wanted(in_links: bool) -> bool:
        return mode == "*" or (mode == "." and not in_links) or (mode == "~" and in_links)

    def walk(node: Any, in_links: bool, depth: int) -> Any:
        if isinstance(node, dict):
            if depth > 0 and len(node) == 1 and "@odata.id" in node and wanted(in_links):
                target = resolve(node["@odata.id"])
                if target is not None:
                    return resource(target, depth - 1)
                return node
            return {k: walk(v, in_links or k == "Links", depth) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, in_links, depth) for v in node]
        return node

    def resource(res: Json, depth: int) -> Json:
        return {k: walk(v, k == "Links", depth) for k, v in res.items()}

    return resource(body, levels)


# ---------------------------------------------------------------------------------- handlers


def _normalize(path: str) -> str:
    path = re.sub(r"/{2,}", "/", path)
    return path.rstrip("/") if path != "/" else path


def _authenticated(request: web.Request, bmc: VirtualBmc) -> bool:
    token = request.headers.get("X-Auth-Token")
    if token:
        return bmc.session_for_token(token) is not None
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("basic "):
        try:
            user, _, password = (
                base64.b64decode(auth[6:].strip(), validate=True).decode("utf-8").partition(":")
            )
        except (binascii.Error, UnicodeDecodeError):
            return False
        return _check_credentials(request, user, password)
    return False


def _check_credentials(request: web.Request, user: str, password: str) -> bool:
    expected = request.app[CREDENTIALS_KEY]
    ok_user = hmac.compare_digest(user.encode("utf-8"), expected.username.encode("utf-8"))
    ok_password = hmac.compare_digest(password.encode("utf-8"), expected.password.encode("utf-8"))
    return ok_user and ok_password


async def _create_session(request: web.Request, bmc: VirtualBmc) -> web.Response:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return redfish_error(400, "MalformedJSON", "The request body submitted was malformed JSON.")
    if not isinstance(body, dict):
        return redfish_error(400, "MalformedJSON", "The request body submitted was malformed JSON.")
    user, password = body.get("UserName"), body.get("Password")
    if not isinstance(user, str) or not isinstance(password, str):
        return redfish_error(
            400,
            "PropertyMissing",
            "The property UserName or Password is a required property and must be included.",
        )
    if not _check_credentials(request, user, password):
        return redfish_error(401, "ResourceAtUriUnauthorized", "Access to the resource was unauthorized.")
    session = bmc.create_session(user, datetime.now(UTC))
    return json_response(session.to_json(), 201, {"X-Auth-Token": session.token, "Location": session.path})


async def handle(request: web.Request) -> web.StreamResponse:
    bmc = request.app[BMC_KEY]
    if bmc.unresponsive:
        await bmc.wait_responsive()
    path = _normalize(request.path)
    method = request.method

    if path == SESSIONS_PATH and method == "POST":
        return await _create_session(request, bmc)
    if path in _UNAUTHENTICATED and method in _READ:
        if path == "/redfish":
            return json_response({"v1": f"{R}/"})
        root = bmc.resolve(R)
        assert root is not None
        return json_response(root)
    if not _authenticated(request, bmc):
        return _unauthorized()

    if method == "DELETE" and path.startswith(SESSIONS_PATH + "/"):
        if bmc.delete_session(path.removeprefix(SESSIONS_PATH + "/")):
            return web.Response(status=204, headers={"OData-Version": "4.0"})
        return redfish_error(
            404,
            "ResourceNotFound",
            f"The requested resource of type Session named '{path.rsplit('/', 1)[-1]}' was not found.",
        )
    resource = bmc.resolve(path)
    if resource is None:
        return redfish_error(
            404, "ResourceNotFound", f"The requested resource at URI '{path}' was not found."
        )
    if method not in _READ:
        allow = (
            "GET, HEAD, POST"
            if path == SESSIONS_PATH
            else "GET, HEAD, DELETE"
            if (path.startswith(SESSIONS_PATH + "/"))
            else "GET, HEAD"
        )
        return redfish_error(
            405, "OperationNotAllowed", "The HTTP method is not allowed on this resource.", {"Allow": allow}
        )

    expand_query = request.query.get("$expand")
    capabilities = bmc.style.expand
    if expand_query is not None and capabilities is not None:
        try:
            mode, levels = parse_expand(expand_query, capabilities)
        except ExpandError as exc:
            return redfish_error(400, "QueryParameterOutOfRange", str(exc))
        resource = expand(resource, mode, levels, bmc.resolve)
    return json_response(resource)


def create_bmc_app(bmc: VirtualBmc, username: str, password: str) -> web.Application:
    app = web.Application()
    app[BMC_KEY] = bmc
    app[CREDENTIALS_KEY] = Credentials(username, password)
    app.router.add_route("*", "/{tail:.*}", handle)
    return app
