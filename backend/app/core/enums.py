"""Domain enumerations. Stored as text with CHECK constraints rather than PostgreSQL enum types."""

from __future__ import annotations

from enum import StrEnum


class Health(StrEnum):
    OK = "OK"
    WARNING = "Warning"
    CRITICAL = "Critical"
    UNKNOWN = "Unknown"

    @property
    def rank(self) -> int:
        return _HEALTH_RANK[self]

    @classmethod
    def worst(cls, values: list[Health]) -> Health:
        if not values:
            return cls.UNKNOWN
        return max(values, key=lambda h: h.rank)


# Unknown ranks above OK: a server we cannot see is worse than a healthy one, better than a failing one.
_HEALTH_RANK = {Health.OK: 0, Health.UNKNOWN: 1, Health.WARNING: 2, Health.CRITICAL: 3}


class Severity(StrEnum):
    INFO = "Info"
    WARNING = "Warning"
    CRITICAL = "Critical"

    @property
    def rank(self) -> int:
        return {Severity.INFO: 0, Severity.WARNING: 1, Severity.CRITICAL: 2}[self]


class AlertState(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class ServerStatus(StrEnum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    DECOMMISSIONED = "decommissioned"


class RuleType(StrEnum):
    THRESHOLD = "threshold"
    STATE = "state"
    MISSING_DATA = "missing_data"
    EVENT = "event"
    COMPLIANCE = "compliance"


class ThresholdScope(StrEnum):
    GLOBAL = "global"
    MODEL = "model"
    SITE = "site"
    SERVER = "server"


class ThresholdDirection(StrEnum):
    ABOVE = "above"
    BELOW = "below"
    DEVIATION_PCT = "deviation_pct"
    PCT_OF_CAPACITY = "pct_of_capacity"


class MaintenanceScope(StrEnum):
    SITE = "site"
    RACK = "rack"
    SERVER = "server"


class ComponentType(StrEnum):
    CPU = "cpu"
    DIMM = "dimm"
    DRIVE = "drive"
    PSU = "psu"
    FAN = "fan"
    NIC = "nic"
    STORAGE_CONTROLLER = "storage_controller"
    VOLUME = "volume"


class RouteChannel(StrEnum):
    EMAIL = "email"
    TEAMS = "teams"


class MetricType(StrEnum):
    GAUGE = "gauge"
    STATE = "state"
    EVENT = "event"
    VERSION = "version"


class Role(StrEnum):
    VIEWER = "viewer"
    NOC_OPERATOR = "noc_operator"
    DC_ENGINEER = "dc_engineer"
    PLATFORM_ADMIN = "platform_admin"
    ANALYST = "analyst"


def check_in(column: str, enum: type[StrEnum]) -> str:
    """SQL CHECK expression restricting a text column to an enum's values."""
    values = ", ".join(f"'{v.value}'" for v in enum)
    return f"{column} IN ({values})"
