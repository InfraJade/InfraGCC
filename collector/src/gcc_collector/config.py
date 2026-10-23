"""Collector settings from the environment (docs/contracts/README.md, "Collector environment variables").

Only local wiring lives here. What to poll and how often comes from the cloud (`GET /ingest/v1/config`).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

CredentialsProvider = Literal["env", "file", "vault"]

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class CollectorEnv(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ingest_url: str = "http://localhost:8001"
    collector_name: str
    ingest_token: SecretStr | None = None
    client_cert: Path | None = None
    client_key: Path | None = None
    ca_bundle: Path | None = None

    credentials_provider: CredentialsProvider = "env"
    bmc_username: str | None = None
    bmc_password: SecretStr | None = None
    credentials_file: Path = Path("/etc/gcc-collector/credentials.yaml")
    vault_addr: str | None = None
    vault_token: SecretStr | None = None
    vault_mount: str = "secret"
    vault_path: str = "gcc/bmc"

    bmc_verify_tls: bool = True
    bmc_ca_bundle: Path | None = None

    buffer_dir: Path = Path("/var/lib/gcc-collector/buffer")
    buffer_ttl_s: int = 86400
    log_level: str = "INFO"
    metrics_port: int = 9108

    @field_validator("ingest_url")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("collector_name")
    @classmethod
    def _required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("GCC_COLLECTOR_NAME is required")
        return value.strip()

    @property
    def ingest_auth_mode(self) -> Literal["token", "mtls"]:
        return "mtls" if self.client_cert is not None else "token"


def _bool(raw: str, name: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"{name} must be true or false, got {raw!r}")


# env var -> field name; values are converted by pydantic.
_FIELDS: dict[str, str] = {
    "GCC_INGEST_URL": "ingest_url",
    "GCC_COLLECTOR_NAME": "collector_name",
    "GCC_INGEST_TOKEN": "ingest_token",
    "GCC_CLIENT_CERT": "client_cert",
    "GCC_CLIENT_KEY": "client_key",
    "GCC_CA_BUNDLE": "ca_bundle",
    "GCC_CREDENTIALS_PROVIDER": "credentials_provider",
    "GCC_BMC_USERNAME": "bmc_username",
    "GCC_BMC_PASSWORD": "bmc_password",
    "GCC_CREDENTIALS_FILE": "credentials_file",
    "VAULT_ADDR": "vault_addr",
    "VAULT_TOKEN": "vault_token",
    "GCC_VAULT_MOUNT": "vault_mount",
    "GCC_VAULT_PATH": "vault_path",
    "GCC_BMC_CA_BUNDLE": "bmc_ca_bundle",
    "GCC_BUFFER_DIR": "buffer_dir",
    "GCC_BUFFER_TTL_S": "buffer_ttl_s",
    "GCC_LOG_LEVEL": "log_level",
    "GCC_METRICS_PORT": "metrics_port",
}


def load_env(environ: Mapping[str, str] | None = None) -> CollectorEnv:
    """Read the collector's settings. Empty variables count as unset."""
    env = os.environ if environ is None else environ
    values: dict[str, object] = {}
    for var, field in _FIELDS.items():
        raw = env.get(var, "")
        if raw.strip():
            values[field] = raw.strip()
    verify = env.get("GCC_BMC_VERIFY_TLS", "").strip()
    if verify:
        values["bmc_verify_tls"] = _bool(verify, "GCC_BMC_VERIFY_TLS")
    if "collector_name" not in values:
        raise ValueError("GCC_COLLECTOR_NAME is required")
    return CollectorEnv.model_validate(values)
