"""Any other Redfish BMC (Supermicro, Cisco, ...): standard properties only; vendor = raw manufacturer."""

from __future__ import annotations

from typing import ClassVar

from gcc_collector.adapters.base import VendorAdapter


class GenericAdapter(VendorAdapter):
    vendor: ClassVar[str] = "Generic"

    @property
    def vendor_name(self) -> str:
        return self.manufacturer or "Unknown"
