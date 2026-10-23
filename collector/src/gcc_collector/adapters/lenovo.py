"""Lenovo XClarity Controller (XCC / XCC2): newer sensor layout, PlatformLog under the system, and
``BMC-Primary`` / ``BMC-Backup`` firmware entries."""

from __future__ import annotations

import re
from typing import ClassVar

from gcc_collector.adapters.base import TempRule, VendorAdapter, dig, text
from gcc_collector.redfish.client import Json

_I = re.IGNORECASE


class LenovoAdapter(VendorAdapter):
    vendor: ClassVar[str] = "Lenovo"
    TEMP_RULES: ClassVar[list[TempRule]] = [
        (re.compile(r"^Ambient Temp$", _I), "inlet_temp_c", ""),
        (re.compile(r"^Exhaust Temp$", _I), "exhaust_temp_c", ""),
        (re.compile(r"^CPU\s?(\d+) (?:DTS|Temp)$", _I), "cpu_temp_c", "CPU{0}"),
        (re.compile(r"^DIMM\s?(\d+) Temp$", _I), "dimm_temp_c", "DIMM {0}"),
    ]
    INCLUDE_LOGS: ClassVar[tuple[str, ...]] = ("PlatformLog", "EventLog", "SEL")

    def bmc_model(self, manager: Json | None, root: Json) -> str | None:
        model = text(dig(manager, "Model")) or ""
        match = re.search(r"XClarity Controller\s*(\d*)", model, _I)
        if match:
            return f"XCC{match.group(1)}"
        return model or text(root.get("Product"))

    def firmware_active(self, entry: Json) -> bool:
        entry_id = (text(entry.get("Id")) or "").lower()
        if entry_id.endswith("-backup") or "pending" in entry_id:
            return False
        return super().firmware_active(entry)
