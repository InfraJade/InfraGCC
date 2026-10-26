"""Derive `health_status` from state readings (DECISIONS.md D11, D19).

| metric | value → health |
|---|---|
| `*_health`, `fan_redundancy`, `psu_redundancy` | the reported status (0 OK, 1 Warning, 2 Critical) |
| `power_state` | On → OK, Off → Warning, anything else → Unknown |
| `nic_link` | Up → OK; Down → Warning on an expected link, OK otherwise |
| `bmc_reachable` | 1 → OK, 0 → Critical |
"""

from __future__ import annotations

from app.core.enums import Health

_BY_STATUS = {h.value.lower(): h for h in Health}
_BY_VALUE = {0: Health.OK, 1: Health.WARNING, 2: Health.CRITICAL}


def derive_health(
    metric: str, value: float | None, status: str | None, *, expected_link_up: bool | None = None
) -> Health:
    if metric == "power_state":
        if value == 1:
            return Health.OK
        if value == 0:
            return Health.WARNING
        return Health.UNKNOWN
    if metric == "nic_link":
        if value == 1:
            return Health.OK
        if value == 0:
            return Health.WARNING if expected_link_up else Health.OK
        return Health.UNKNOWN
    if metric == "bmc_reachable":
        if value == 1:
            return Health.OK
        if value == 0:
            return Health.CRITICAL
        return Health.UNKNOWN
    if status is not None and status.lower() in _BY_STATUS:
        return _BY_STATUS[status.lower()]
    if value is not None and int(value) == value and int(value) in _BY_VALUE:
        return _BY_VALUE[int(value)]
    return Health.UNKNOWN
