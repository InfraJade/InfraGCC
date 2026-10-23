"""All virtual BMCs, the drift step, and fault bookkeeping (random and on demand)."""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta

from gcc_redfish_sim.simulator.bmc import VirtualBmc
from gcc_redfish_sim.simulator.config import SimConfig
from gcc_redfish_sim.simulator.faults import RANDOM_WEIGHTS, Fault, FaultKind, choose_target

log = logging.getLogger("gcc_bmc_simulator")

RANDOM_FAULT_MIN_S = 300.0
RANDOM_FAULT_MAX_S = 1800.0


class FaultError(Exception):
    def __init__(self, status: int, title: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.title = title
        self.detail = detail


def _now(now: datetime | None) -> datetime:
    return now if now is not None else datetime.now(UTC)


class Fleet:
    def __init__(self, config: SimConfig, now: datetime | None = None) -> None:
        self.config = config
        start = _now(now)
        seed = config.seed
        self.rng = random.Random(f"faults-{seed}") if seed is not None else random.Random()
        self.bmcs: dict[int, VirtualBmc] = {}
        for i in range(1, config.count + 1):
            bmc_rng = random.Random(f"bmc-{seed}-{i}") if seed is not None else random.Random()
            self.bmcs[i] = VirtualBmc(i, config.port_for(i), bmc_rng, start)
        self.faults: dict[int, Fault] = {}
        self._next_fault_id = 1

    # --------------------------------------------------------------------------- drift
    def step(self, now: datetime | None = None) -> None:
        """One drift step for every BMC, then expire faults and maybe raise random ones."""
        now = _now(now)
        for bmc in self.bmcs.values():
            bmc.step(now)
        for fault in [f for f in self.faults.values() if f.expires_at is not None and f.expires_at <= now]:
            self.clear_fault(fault.id, now=now, reason="expired")
        self._random_faults(now)

    def _random_faults(self, now: datetime) -> None:
        p = self.config.fault_rate_per_hour * self.config.step_s / 3600.0
        if p <= 0:
            return
        kinds = list(RANDOM_WEIGHTS)
        weights = list(RANDOM_WEIGHTS.values())
        for index, bmc in self.bmcs.items():
            if self.rng.random() >= p:
                continue
            kind = self.rng.choices(kinds, weights)[0]
            if kind in bmc.kinds():
                continue
            duration = self.rng.uniform(RANDOM_FAULT_MIN_S, RANDOM_FAULT_MAX_S)
            self.raise_fault(index, kind, duration_s=duration, source="random", now=now)

    # -------------------------------------------------------------------------- faults
    def bmc(self, index: int) -> VirtualBmc:
        bmc = self.bmcs.get(index)
        if bmc is None:
            raise FaultError(404, "Unknown BMC", f"BMC {index} does not exist (1..{len(self.bmcs)})")
        return bmc

    def raise_fault(
        self,
        index: int,
        kind: FaultKind | str,
        *,
        duration_s: float | None = None,
        source: str = "manual",
        now: datetime | None = None,
    ) -> Fault:
        now = _now(now)
        bmc = self.bmc(index)
        try:
            kind = FaultKind(kind)
        except ValueError:
            allowed = ", ".join(k.value for k in FaultKind)
            raise FaultError(400, "Unknown fault kind", f"kind must be one of: {allowed}") from None
        if duration_s is not None and duration_s <= 0:
            raise FaultError(400, "Invalid duration", "duration_s must be positive")
        if kind in bmc.kinds():
            existing = next(f for f in bmc.faults.values() if f.kind == kind)
            raise FaultError(
                409, "Fault already active", f"BMC {index} already has {kind} (fault {existing.id})"
            )
        target, value = choose_target(kind, bmc.state, self.rng)
        fault = Fault(
            id=self._next_fault_id,
            bmc=index,
            kind=kind,
            target=target,
            value=value,
            source=source,
            started_at=now,
            expires_at=now + timedelta(seconds=duration_s) if duration_s is not None else None,
        )
        self._next_fault_id += 1
        self.faults[fault.id] = fault
        bmc.add_fault(fault, now)
        log.info(
            "fault %d raised: bmc=%d port=%d model=%s kind=%s target=%s source=%s duration=%s",
            fault.id,
            index,
            bmc.port,
            bmc.spec.key,
            kind,
            target or "-",
            source,
            f"{duration_s:.0f}s" if duration_s is not None else "until cleared",
        )
        return fault

    def clear_fault(self, fault_id: int, *, now: datetime | None = None, reason: str = "manual") -> Fault:
        fault = self.faults.pop(fault_id, None)
        if fault is None:
            raise FaultError(404, "Unknown fault", f"fault {fault_id} is not active")
        bmc = self.bmcs[fault.bmc]
        bmc.remove_fault(fault_id, _now(now))
        log.info(
            "fault %d cleared: bmc=%d port=%d kind=%s target=%s reason=%s",
            fault.id,
            fault.bmc,
            bmc.port,
            fault.kind,
            fault.target or "-",
            reason,
        )
        return fault

    def clear_all(self, *, now: datetime | None = None) -> int:
        ids = list(self.faults)
        for fault_id in ids:
            self.clear_fault(fault_id, now=now)
        return len(ids)
