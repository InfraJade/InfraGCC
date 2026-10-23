"""Dell iDRAC9 (iDRAC8 partially): both sensor layouts, SEL under the manager, and firmware inventory
entries named ``Installed-...`` / ``Previous-...``."""

from __future__ import annotations

import re
from typing import ClassVar

from gcc_collector.adapters.base import TempRule, VendorAdapter, dig, normalize_mac, text
from gcc_collector.redfish.client import Json

_I = re.IGNORECASE


class DellAdapter(VendorAdapter):
    vendor: ClassVar[str] = "Dell"
    TEMP_RULES: ClassVar[list[TempRule]] = [
        (re.compile(r"^System Board Inlet Temp$", _I), "inlet_temp_c", ""),
        (re.compile(r"^System Board Exhaust Temp$", _I), "exhaust_temp_c", ""),
        (re.compile(r"^CPU\s?(\d+) Temp$", _I), "cpu_temp_c", "CPU{0}"),
        (re.compile(r"^DIMM\s?([A-Z]\d+) Temp$", _I), "dimm_temp_c", "DIMM {0}"),
    ]
    # "System Board Fan1A" / "Fan.Embedded.1A": rotor A is the fan itself ("Fan 1"); rotor B is "Fan 1B".
    FAN_NAME = re.compile(r"Fan[\s_.\-]*(?:Embedded[\s_.\-]*)?(\d+)([AB])?", _I)
    INCLUDE_LOGS: ClassVar[tuple[str, ...]] = ("Sel",)

    def fan_name(self, name: str | None, member_id: str | None, index: int) -> str:
        for candidate in (name, member_id):
            if candidate:
                match = self.FAN_NAME.search(candidate)
                if match:
                    rotor = (match.group(2) or "A").upper()
                    return f"Fan {int(match.group(1))}" + ("" if rotor == "A" else rotor)
        return super().fan_name(name, member_id, index)

    def dimm_name(self, dimm: Json, index: int) -> str:
        for candidate in (text(dimm.get("Id")), text(dimm.get("DeviceLocator")), text(dimm.get("Name"))):
            match = re.search(r"([A-Z]\d+)$", candidate or "")
            if match:
                return f"DIMM {match.group(1)}"
        return super().dimm_name(dimm, index)

    def bmc_model(self, manager: Json | None, root: Json) -> str | None:
        model = text(dig(manager, "Model")) or ""
        generation = re.match(r"(\d+)G", model)
        if generation:
            gen = int(generation.group(1))
            if gen <= 13:
                return "iDRAC8"
            return "iDRAC9" if gen <= 16 else "iDRAC10"
        return model or text(root.get("Product"))

    def firmware_active(self, entry: Json) -> bool:
        entry_id = text(entry.get("Id")) or ""
        if "__" in entry_id:  # iDRAC ids: Installed-<id>-<ver>__<fqdd>, Previous-..., Available-...
            return entry_id.startswith("Installed-")
        return super().firmware_active(entry)

    def identity_serial(self, system: Json) -> str | None:
        # The Service Tag (SKU on iDRAC) is what Dell support and asset registers use.
        tag = text(dig(system, "Oem", "Dell", "DellSystem", "ChassisServiceTag")) or text(system.get("SKU"))
        return tag or super().identity_serial(system)

    def fallback_bmc_mac(self, root: Json) -> str | None:
        return normalize_mac(dig(root, "Oem", "Dell", "ManagerMACAddress"))
