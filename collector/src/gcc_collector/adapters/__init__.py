"""Vendor adapters: map each vendor's Redfish answers to contract metric codes and part names."""

from __future__ import annotations

from gcc_collector.adapters.base import (
    ALL_KINDS,
    PollContext,
    PollKind,
    PollOutput,
    ServerState,
    VendorAdapter,
)
from gcc_collector.adapters.registry import detect_adapter

__all__ = [
    "ALL_KINDS",
    "PollContext",
    "PollKind",
    "PollOutput",
    "ServerState",
    "VendorAdapter",
    "detect_adapter",
]
