"""Simulator settings from the environment (see mockups/README.md)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

MAX_PORT = 65535


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class SimConfig:
    count: int = 36
    base_port: int = 20000
    control_port: int = 9100
    host: str = "0.0.0.0"  # noqa: S104 - the simulator runs in a container and must be reachable
    username: str = "gcc-monitor"
    password: str = "dev-bmc-pw"  # noqa: S105 - dev-only default, documented
    fault_rate_per_hour: float = 0.05
    seed: str | None = None
    step_s: float = 10.0
    access_log: bool = False
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if self.count < 1:
            raise ConfigError("SIM_COUNT must be at least 1")
        if self.base_port < 1 or self.base_port + self.count > MAX_PORT:
            raise ConfigError(f"ports {self.base_port + 1}..{self.base_port + self.count} are out of range")
        if self.base_port < self.control_port <= self.base_port + self.count:
            raise ConfigError("SIM_CONTROL_PORT falls inside the BMC port range")
        if self.fault_rate_per_hour < 0:
            raise ConfigError("SIM_FAULT_RATE must not be negative")
        if self.step_s <= 0:
            raise ConfigError("SIM_STEP_S must be positive")

    def port_for(self, index: int) -> int:
        return self.base_port + index

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SimConfig:
        e = os.environ if env is None else env
        d = cls.__dataclass_fields__

        def get(name: str, field: str) -> str:
            value = e.get(name, "").strip()
            return value if value else str(d[field].default)

        try:
            return cls(
                count=int(get("SIM_COUNT", "count")),
                base_port=int(get("SIM_BASE_PORT", "base_port")),
                control_port=int(get("SIM_CONTROL_PORT", "control_port")),
                host=get("SIM_HOST", "host"),
                username=get("SIM_USERNAME", "username"),
                password=get("SIM_PASSWORD", "password"),
                fault_rate_per_hour=float(get("SIM_FAULT_RATE", "fault_rate_per_hour")),
                seed=e.get("SIM_SEED", "").strip() or None,
                step_s=float(get("SIM_STEP_S", "step_s")),
                access_log=get("SIM_ACCESS_LOG", "access_log").lower() in ("1", "true", "yes", "on"),
                log_level=get("SIM_LOG_LEVEL", "log_level").upper(),
            )
        except ValueError as exc:
            if isinstance(exc, ConfigError):
                raise
            raise ConfigError(str(exc)) from exc
