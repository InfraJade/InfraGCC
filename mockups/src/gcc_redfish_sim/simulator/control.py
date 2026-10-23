"""Control API (port SIM_CONTROL_PORT) and the Microsoft Teams webhook sink.

  GET    /health                      liveness and counts
  GET    /bmcs                        every BMC: index, port, model, serial, power, health, load, faults
  GET    /bmcs/{i}                    one BMC
  POST   /bmcs/{i}/load               {"load": 0..1} pins the workload; {"load": null} lets it wander again
  GET    /faults                      active faults
  POST   /faults                      {"bmc": i, "kind": "...", "duration_s": optional} -> 201
  DELETE /faults/{id}                 clear one fault
  DELETE /faults                      clear all faults
  POST   /webhooks/teams/{channel}    store a Teams webhook post (last 500 kept); answers 200 "1" like Teams
  GET    /webhooks/teams              stored posts, newest first (?channel=, ?limit=)
  DELETE /webhooks/teams              forget stored posts

Errors are RFC 9457 `application/problem+json`.
"""

from __future__ import annotations

import itertools
import json
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

from aiohttp import web

from gcc_redfish_sim.simulator.faults import FaultKind
from gcc_redfish_sim.simulator.fleet import FaultError, Fleet

TEAMS_KEEP = 500


class TeamsSink:
    def __init__(self, keep: int = TEAMS_KEEP) -> None:
        self.posts: deque[dict[str, Any]] = deque(maxlen=keep)
        self._ids = itertools.count(1)

    def add(self, channel: str, body: Any) -> dict[str, Any]:
        post = {
            "id": next(self._ids),
            "channel": channel,
            "received_at": datetime.now(UTC).isoformat(),
            "body": body,
        }
        self.posts.append(post)
        return post

    def list(self, channel: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        posts = [p for p in reversed(self.posts) if channel is None or p["channel"] == channel]
        return posts[:limit] if limit is not None else posts


FLEET_KEY = web.AppKey("fleet", Fleet)
SINK_KEY = web.AppKey("teams_sink", TeamsSink)
STARTED_KEY = web.AppKey("started", float)


def problem(status: int, title: str, detail: str) -> web.Response:
    return web.json_response(
        {"type": "about:blank", "title": title, "status": status, "detail": detail},
        status=status,
        content_type="application/problem+json",
    )


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise FaultError(400, "Invalid JSON", "The request body is not valid JSON") from None
    if not isinstance(body, dict):
        raise FaultError(400, "Invalid JSON", "The request body must be a JSON object")
    return body


def _int(value: str, what: str) -> int:
    try:
        return int(value)
    except ValueError:
        raise FaultError(400, f"Invalid {what}", f"{what} must be an integer") from None


@web.middleware
async def _errors(request: web.Request, handler: Any) -> web.StreamResponse:
    try:
        response: web.StreamResponse = await handler(request)
    except FaultError as exc:
        return problem(exc.status, exc.title, exc.detail)
    return response


async def health(request: web.Request) -> web.Response:
    fleet = request.app[FLEET_KEY]
    return web.json_response(
        {
            "status": "ok",
            "bmcs": len(fleet.bmcs),
            "ports": [fleet.config.port_for(1), fleet.config.port_for(len(fleet.bmcs))],
            "active_faults": len(fleet.faults),
            "uptime_s": round(time.monotonic() - request.app[STARTED_KEY], 1),
        }
    )


async def list_bmcs(request: web.Request) -> web.Response:
    return web.json_response([b.summary() for b in request.app[FLEET_KEY].bmcs.values()])


async def get_bmc(request: web.Request) -> web.Response:
    fleet = request.app[FLEET_KEY]
    return web.json_response(fleet.bmc(_int(request.match_info["index"], "BMC index")).summary())


async def set_load(request: web.Request) -> web.Response:
    fleet = request.app[FLEET_KEY]
    bmc = fleet.bmc(_int(request.match_info["index"], "BMC index"))
    body = await _json_body(request)
    load = body.get("load")
    if load is not None and (
        isinstance(load, bool) or not isinstance(load, int | float) or not 0 <= load <= 1
    ):
        raise FaultError(400, "Invalid load", "load must be a number from 0 to 1, or null")
    bmc.set_load(float(load) if load is not None else None)
    bmc.refresh()
    return web.json_response(bmc.summary())


async def list_faults(request: web.Request) -> web.Response:
    fleet = request.app[FLEET_KEY]
    return web.json_response([f.to_json(fleet.bmcs[f.bmc].port) for f in fleet.faults.values()])


async def create_fault(request: web.Request) -> web.Response:
    fleet = request.app[FLEET_KEY]
    body = await _json_body(request)
    index, kind, duration = body.get("bmc"), body.get("kind"), body.get("duration_s")
    if isinstance(index, bool) or not isinstance(index, int):
        raise FaultError(400, "Invalid BMC", "bmc must be an integer BMC index")
    if not isinstance(kind, str):
        allowed = ", ".join(k.value for k in FaultKind)
        raise FaultError(400, "Unknown fault kind", f"kind must be one of: {allowed}")
    if duration is not None and (isinstance(duration, bool) or not isinstance(duration, int | float)):
        raise FaultError(400, "Invalid duration", "duration_s must be a number of seconds")
    fault = fleet.raise_fault(index, kind, duration_s=float(duration) if duration is not None else None)
    return web.json_response(fault.to_json(fleet.bmcs[index].port), status=201)


async def delete_fault(request: web.Request) -> web.Response:
    fleet = request.app[FLEET_KEY]
    fault = fleet.clear_fault(_int(request.match_info["fault_id"], "fault id"))
    return web.json_response(fault.to_json(fleet.bmcs[fault.bmc].port))


async def delete_faults(request: web.Request) -> web.Response:
    return web.json_response({"cleared": request.app[FLEET_KEY].clear_all()})


async def teams_post(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return web.Response(status=400, text="Bad payload received by generic incoming webhook.")
    request.app[SINK_KEY].add(request.match_info["channel"], body)
    return web.Response(status=200, text="1")


async def teams_list(request: web.Request) -> web.Response:
    limit = request.query.get("limit")
    posts = request.app[SINK_KEY].list(
        request.query.get("channel"), _int(limit, "limit") if limit is not None else None
    )
    return web.json_response(posts)


async def teams_clear(request: web.Request) -> web.Response:
    sink = request.app[SINK_KEY]
    count = len(sink.posts)
    sink.posts.clear()
    return web.json_response({"cleared": count})


def create_control_app(fleet: Fleet, sink: TeamsSink | None = None) -> web.Application:
    app = web.Application(middlewares=[_errors])
    app[FLEET_KEY] = fleet
    app[SINK_KEY] = sink if sink is not None else TeamsSink()
    app[STARTED_KEY] = time.monotonic()
    app.router.add_get("/health", health)
    app.router.add_get("/bmcs", list_bmcs)
    app.router.add_get("/bmcs/{index}", get_bmc)
    app.router.add_post("/bmcs/{index}/load", set_load)
    app.router.add_get("/faults", list_faults)
    app.router.add_post("/faults", create_fault)
    app.router.add_delete("/faults", delete_faults)
    app.router.add_delete("/faults/{fault_id}", delete_fault)
    app.router.add_post("/webhooks/teams/{channel}", teams_post)
    app.router.add_get("/webhooks/teams", teams_list)
    app.router.add_delete("/webhooks/teams", teams_clear)
    return app
