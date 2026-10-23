"""One virtual BMC: its server state, drift, active faults, log, sessions and a cached resource tree."""

from __future__ import annotations

import asyncio
import random
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from gcc_redfish_sim.catalog import ModelSpec, make_state, model_for_index
from gcc_redfish_sim.model import OK, LogEntry
from gcc_redfish_sim.simulator import physics
from gcc_redfish_sim.simulator.faults import Fault, FaultKind, effects, log_entry, overlay
from gcc_redfish_sim.tree import STYLES, R, Style, build_tree

Json = dict[str, Any]

SESSIONS_PATH = f"{R}/SessionService/Sessions"
SESSION_TIMEOUT_S = 1800.0  # matches SessionService.SessionTimeout in the tree
MAX_LOG_ENTRIES = 1024  # matches LogService.MaxNumberOfRecords (WrapsWhenFull)


@dataclass
class Session:
    id: str
    token: str
    username: str
    created: datetime
    last_used: float = field(default_factory=time.monotonic)

    @property
    def path(self) -> str:
        return f"{SESSIONS_PATH}/{self.id}"

    def to_json(self) -> Json:
        return {
            "@odata.id": self.path,
            "@odata.type": "#Session.v1_6_0.Session",
            "Id": self.id,
            "Name": "User Session",
            "Description": "User Session",
            "UserName": self.username,
            "SessionType": "Redfish",
            "CreatedTime": self.created.isoformat(timespec="seconds"),
        }


class VirtualBmc:
    def __init__(self, index: int, port: int, rng: random.Random, now: datetime) -> None:
        self.index = index
        self.port = port
        self.spec: ModelSpec = model_for_index(index)
        self.state = make_state(self.spec.key, index)
        self.style: Style = STYLES[self.state.profile]
        self.rng = rng
        self.physics = physics.Physics.initial(self.state, index, rng)
        self._drive_life = {d.key: d.life_left_pct for d in self.state.drives()}
        self._nic_up = {n.key: n.link_up for n in self.state.nics}
        self.faults: dict[int, Fault] = {}
        self.sessions: dict[str, Session] = {}  # by token
        self._session_seq = 0
        self._tree: dict[str, Json] | None = None
        self._responsive = asyncio.Event()
        self._responsive.set()
        self.step(now)

    # ------------------------------------------------------------------------- state
    @property
    def vendor(self) -> str:
        return self.style.vendor

    def tree(self) -> dict[str, Json]:
        """All resources keyed by path; rendered on first use after a change, then cached."""
        if self._tree is None:
            self._tree = build_tree(self.state)
        return self._tree

    def step(self, now: datetime) -> None:
        physics.step(self.physics, self.state, now, self.rng, effects(list(self.faults.values())))
        self.refresh()

    def refresh(self) -> None:
        """Re-derive the rendered state from physics + baseline + active faults, and drop the cache."""
        s = self.state
        physics.write_readings(self.physics, s)
        s.power_state = "On"
        for t in s.temps:
            t.health = physics.temp_health(t)
        for f in s.fans:
            f.health = physics.fan_health(f)
        for p in s.psus:
            p.health = OK
        for d in s.drives():
            d.life_left_pct = self._drive_life[d.key]
            d.health = OK
        for n in s.nics:
            n.link_up = self._nic_up[n.key]
        for fault in sorted(self.faults.values(), key=lambda f: f.id):
            overlay(fault, s)
        self._tree = None

    def set_load(self, load: float | None) -> None:
        """Pin the workload (0..1) or, with None, let it wander again."""
        self.physics.pinned_load = load
        if load is not None:
            self.state.load = load

    # ------------------------------------------------------------------------ faults
    def kinds(self) -> set[FaultKind]:
        return {f.kind for f in self.faults.values()}

    def add_fault(self, fault: Fault, now: datetime) -> None:
        self.faults[fault.id] = fault
        self._log_fault(fault, now, cleared=False)
        if fault.kind == FaultKind.BMC_UNRESPONSIVE:
            self._responsive.clear()
        self.refresh()

    def remove_fault(self, fault_id: int, now: datetime) -> Fault | None:
        fault = self.faults.pop(fault_id, None)
        if fault is None:
            return None
        if fault.kind == FaultKind.BMC_UNRESPONSIVE and FaultKind.BMC_UNRESPONSIVE not in self.kinds():
            self.sessions.clear()  # a BMC reset drops its sessions
            self._responsive.set()
        self._log_fault(fault, now, cleared=True)
        self.refresh()
        return fault

    def _log_fault(self, fault: Fault, now: datetime, *, cleared: bool) -> None:
        entry = log_entry(fault, self.state, cleared=cleared)
        if entry is not None:
            self.add_log(*entry, now=now)

    def add_log(self, severity: str, message_id: str, message: str, *, now: datetime) -> LogEntry:
        sel = self.state.sel
        next_id = max((int(e.id) for e in sel), default=0) + 1
        created = now.astimezone(physics.SITE_TZ).isoformat(timespec="seconds")
        entry = LogEntry(str(next_id), created, severity, message, message_id)
        sel.append(entry)
        del sel[:-MAX_LOG_ENTRIES]
        self._tree = None
        return entry

    @property
    def unresponsive(self) -> bool:
        return not self._responsive.is_set()

    async def wait_responsive(self) -> None:
        await self._responsive.wait()

    def release_waiters(self) -> None:
        """Let requests hanging on an unresponsive BMC finish (used at shutdown)."""
        self._responsive.set()

    # ---------------------------------------------------------------------- sessions
    def create_session(self, username: str, now: datetime) -> Session:
        self.expire_sessions()
        self._session_seq += 1
        session = Session(str(self._session_seq), secrets.token_hex(16), username, now)
        self.sessions[session.token] = session
        return session

    def session_for_token(self, token: str) -> Session | None:
        session = self.sessions.get(token)
        if session is None:
            return None
        if time.monotonic() - session.last_used > SESSION_TIMEOUT_S:
            del self.sessions[token]
            return None
        session.last_used = time.monotonic()
        return session

    def session_by_id(self, session_id: str) -> Session | None:
        return next((s for s in self.sessions.values() if s.id == session_id), None)

    def delete_session(self, session_id: str) -> bool:
        session = self.session_by_id(session_id)
        if session is None:
            return False
        del self.sessions[session.token]
        return True

    def expire_sessions(self) -> None:
        cutoff = time.monotonic() - SESSION_TIMEOUT_S
        for token in [t for t, s in self.sessions.items() if s.last_used < cutoff]:
            del self.sessions[token]

    # --------------------------------------------------------------------- resources
    def resolve(self, path: str) -> Json | None:
        """The resource at `path`, including the live session collection and session resources."""
        if path == SESSIONS_PATH:
            members = [{"@odata.id": s.path} for s in sorted(self.sessions.values(), key=lambda s: int(s.id))]
            return {
                "@odata.id": SESSIONS_PATH,
                "@odata.type": "#SessionCollection.SessionCollection",
                "Name": "Session Collection",
                "Members": members,
                "Members@odata.count": len(members),
            }
        if path.startswith(SESSIONS_PATH + "/"):
            session = self.session_by_id(path.removeprefix(SESSIONS_PATH + "/"))
            return session.to_json() if session else None
        return self.tree().get(path)

    def summary(self) -> Json:
        return {
            "index": self.index,
            "port": self.port,
            "model_key": self.spec.key,
            "model": self.state.model,
            "vendor": self.vendor,
            "serial": self.state.serial,
            "service_tag": self.state.sku if self.state.profile == "dell" else None,
            "power_state": self.state.power_state,
            "health": self.state.system_health(),
            "load": round(self.state.load, 3),
            "load_pinned": self.physics.pinned_load is not None,
            "responsive": not self.unresponsive,
            "faults": [{"id": f.id, "kind": str(f.kind), "target": f.target} for f in self.faults.values()],
        }
