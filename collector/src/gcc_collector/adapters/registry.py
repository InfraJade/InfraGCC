"""Pick the adapter for a BMC from the system's Manufacturer, the service root's Oem keys and Vendor."""

from __future__ import annotations

from gcc_collector.adapters.base import VendorAdapter, text
from gcc_collector.adapters.dell import DellAdapter
from gcc_collector.adapters.generic import GenericAdapter
from gcc_collector.adapters.hpe import HpeAdapter
from gcc_collector.adapters.lenovo import LenovoAdapter
from gcc_collector.redfish.client import Json

ADAPTERS: dict[str, type[VendorAdapter]] = {"Dell": DellAdapter, "HPE": HpeAdapter, "Lenovo": LenovoAdapter}


def vendor_of(root: Json, system: Json) -> str | None:
    """``Dell`` / ``HPE`` / ``Lenovo``, or None for anything else."""
    manufacturer = (text(system.get("Manufacturer")) or "").lower()
    raw_oem = root.get("Oem")
    oem: set[str] = set(raw_oem) if isinstance(raw_oem, dict) else set()
    root_vendor = (text(root.get("Vendor")) or "").lower()
    if "dell" in manufacturer or "Dell" in oem or root_vendor == "dell":
        return "Dell"
    if (
        manufacturer in ("hpe", "hp")
        or "hewlett" in manufacturer
        or "Hpe" in oem
        or "Hp" in oem
        or root_vendor in ("hpe", "hp")
    ):
        return "HPE"
    if "lenovo" in manufacturer or "Lenovo" in oem or root_vendor == "lenovo":
        return "Lenovo"
    return None


def detect_adapter(root: Json, system: Json) -> VendorAdapter:
    manufacturer = text(system.get("Manufacturer")) or text(root.get("Vendor"))
    vendor = vendor_of(root, system)
    if vendor is None:
        return GenericAdapter(manufacturer)
    return ADAPTERS[vendor](manufacturer)
