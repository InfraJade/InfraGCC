"""HPE iLO 5 / iLO 6 (iLO 4 partially): legacy Thermal/Power only, fans in percent, power supplies
identified by ``Oem.Hpe.BayNumber``, and the Integrated Management Log (IML) under the system."""

from __future__ import annotations

import re
from typing import ClassVar

from gcc_collector.adapters.base import TempRule, VendorAdapter, dig, first_int, text
from gcc_collector.redfish.client import Json

_I = re.IGNORECASE


class HpeAdapter(VendorAdapter):
    vendor: ClassVar[str] = "HPE"
    TEMP_RULES: ClassVar[list[TempRule]] = [
        (re.compile(r"^\d+-Inlet Ambient$", _I), "inlet_temp_c", ""),
        (re.compile(r"^\d+-Exhaust Sensor$", _I), "exhaust_temp_c", ""),
        (re.compile(r"^\d+-CPU\s?(\d+)$", _I), "cpu_temp_c", "CPU{0}"),
        (re.compile(r"^\d+-(P\d+ DIMM [\d\-]+)$", _I), "dimm_temp_c", "{0}"),
    ]
    INCLUDE_LOGS: ClassVar[tuple[str, ...]] = ("IML",)

    def psu_name(self, psu: Json, index: int) -> str:
        bay = dig(psu, "Oem", "Hpe", "BayNumber") or dig(psu, "Oem", "Hp", "BayNumber")
        if isinstance(bay, int) and not isinstance(bay, bool):
            return f"PSU {bay}"
        return super().psu_name(psu, index)

    def dimm_name(self, dimm: Json, index: int) -> str:
        # HPE labels slots per processor, "PROC 1 DIMM 1", as on the iLO UI and the chassis label.
        locator = text(dimm.get("DeviceLocator")) or ""
        match = re.match(r"PROC\s*(\d+)\s*DIMM\s*(\d+)", locator, _I) or re.match(
            r"proc(\d+)dimm(\d+)", text(dimm.get("Id")) or "", _I
        )
        if match:
            return f"PROC {match.group(1)} DIMM {match.group(2)}"
        return super().dimm_name(dimm, index)

    def drive_name(self, drive: Json, index: int) -> str:
        bay = dig(drive, "PhysicalLocation", "PartLocation", "LocationOrdinalValue")
        if not isinstance(bay, int) or isinstance(bay, bool):
            bay = first_int(text(drive.get("Id")))
        return f"Disk {bay if bay is not None else index}"

    def firmware_active(self, entry: Json) -> bool:
        name = (text(entry.get("Name")) or "").lower()
        if name.startswith(("redundant", "backup")):
            return False
        return super().firmware_active(entry)
