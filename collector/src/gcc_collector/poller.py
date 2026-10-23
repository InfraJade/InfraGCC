"""Polls one server: owns its Redfish client, discovery cache, vendor adapter and between-poll state."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from gcc_collector.adapters import (
    ALL_KINDS,
    PollContext,
    PollKind,
    ServerState,
    VendorAdapter,
    detect_adapter,
)
from gcc_collector.credentials import CredentialError
from gcc_collector.redfish.client import BmcUnreachable, NotFound, RedfishClient, RedfishError
from gcc_collector.redfish.discovery import BmcMap, DiscoveryError, discover
from gcc_collector.schema import Reading, ServerConfig, ServerPayload

log = logging.getLogger("gcc.collector.poller")


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


@dataclass
class PollResult:
    payload: ServerPayload
    ok: bool
    vendor: str
    error: str | None = None


class ServerPoller:
    def __init__(
        self,
        server: ServerConfig,
        client: RedfishClient,
        *,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.server = server
        self.client = client
        self.clock = clock
        self.bmc: BmcMap | None = None
        self.adapter: VendorAdapter | None = None
        self.state = ServerState()
        self.contacted = False  # a poll has succeeded at least once

    @property
    def vendor(self) -> str:
        if self.adapter is not None:
            return self.adapter.vendor_name
        return self.server.vendor or "unknown"

    async def _discover(self) -> BmcMap:
        self.bmc = await discover(self.client)
        self.adapter = detect_adapter(self.bmc.root, self.bmc.system)
        return self.bmc

    def invalidate(self) -> None:
        self.bmc = None

    async def poll(self, kinds: frozenset[PollKind]) -> PollResult:
        """One poll. Never raises for BMC problems: a failed poll is a ``bmc_reachable = 0`` payload."""
        if not self.contacted:
            kinds = ALL_KINDS  # first contact: identity, inventory and firmware right away
        try:
            payload = await self._poll(kinds)
        except (RedfishError, DiscoveryError, CredentialError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            level = logging.INFO if isinstance(exc, BmcUnreachable) else logging.WARNING
            log.log(level, "server %s (%s): poll failed: %s", self.server.id, self.server.bmc_host, reason)
            if not isinstance(exc, BmcUnreachable):
                self.invalidate()
            return PollResult(self.unreachable(), ok=False, vendor=self.vendor, error=reason)
        self.contacted = True
        return PollResult(payload, ok=True, vendor=self.vendor)

    async def _poll(self, kinds: frozenset[PollKind]) -> ServerPayload:
        now = self.clock()
        if self.bmc is None or self.adapter is None or "inventory" in kinds:
            await self._discover()  # the daily re-walk also picks up added or moved resources
        assert self.bmc is not None and self.adapter is not None
        try:
            output = await self.adapter.poll(PollContext(self.client, self.bmc, now), self.state, kinds)
        except NotFound as exc:
            # A cached path is gone: walk the tree again and retry once, tolerating 404s this time.
            log.info("server %s: %s returned 404; rediscovering", self.server.id, exc.path)
            bmc = await self._discover()
            assert self.adapter is not None
            output = await self.adapter.poll(
                PollContext(self.client, bmc, now, strict_404=False), self.state, kinds
            )
        return ServerPayload(
            server_id=self.server.id,
            polled_at=self.clock(),
            readings=output.readings,
            bmc_limits=output.bmc_limits,
            events=output.events,
            identity=output.identity,
            components=output.components,
            firmware=output.firmware,
        )

    def unreachable(self) -> ServerPayload:
        now = self.clock()
        reading = Reading(time=now, metric="bmc_reachable", component="", value=0, status="Unreachable")
        return ServerPayload(server_id=self.server.id, polled_at=now, readings=[reading])

    async def close(self) -> None:
        await self.client.close()
