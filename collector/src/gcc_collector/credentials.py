"""BMC credential providers: one shared env account, a local YAML file, or HashiCorp Vault KV v2.

Credentials are resolved on the collector only. Passwords are held as ``SecretStr``, never logged, and
never included in anything sent to the cloud (the cloud only knows the ``credential_ref`` name).
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml
from pydantic import SecretStr

from gcc_collector.config import CollectorEnv

log = logging.getLogger("gcc.collector.credentials")


class CredentialError(RuntimeError):
    """No usable credentials for a BMC. The message never contains a password."""


@dataclass(frozen=True)
class Credentials:
    username: str
    password: SecretStr

    def __repr__(self) -> str:  # pragma: no cover - defensive; dataclass repr would show SecretStr anyway
        return f"Credentials(username={self.username!r}, password='**********')"


class CredentialProvider(Protocol):
    async def get(self, credential_ref: str, bmc_host: str) -> Credentials: ...

    async def aclose(self) -> None: ...


def _creds(raw: Any, where: str) -> Credentials:
    if not isinstance(raw, dict) or not raw.get("username") or raw.get("password") is None:
        raise CredentialError(f"{where}: expected a mapping with 'username' and 'password'")
    return Credentials(username=str(raw["username"]), password=SecretStr(str(raw["password"])))


class EnvProvider:
    """One read-only account for every BMC (`GCC_BMC_USERNAME` / `GCC_BMC_PASSWORD`)."""

    def __init__(self, username: str | None, password: SecretStr | None) -> None:
        if not username or password is None:
            raise CredentialError("GCC_BMC_USERNAME and GCC_BMC_PASSWORD are required for the env provider")
        self._creds = Credentials(username=username, password=password)

    async def get(self, credential_ref: str, bmc_host: str) -> Credentials:
        return self._creds

    async def aclose(self) -> None:
        return None


class FileProvider:
    """YAML file: ``{default: {username, password}, refs: {<ref>: {...}}, hosts: {<bmc_host>: {...}}}``.

    Lookup order: the exact ``bmc_host``, then the ``credential_ref``, then ``default``. The file is re-read
    when its modification time changes, so rotating a password needs no restart.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._mtime: float | None = None
        self._data: dict[str, Any] = {}

    def _load(self) -> dict[str, Any]:
        try:
            mtime = self._path.stat().st_mtime
        except OSError as exc:
            raise CredentialError(f"credentials file {self._path} is not readable: {exc.strerror}") from None
        if mtime != self._mtime:
            try:
                data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                raise CredentialError(f"credentials file {self._path} is not valid YAML") from None
            if not isinstance(data, dict):
                raise CredentialError(f"credentials file {self._path} must contain a mapping")
            self._data, self._mtime = data, mtime
        return self._data

    async def get(self, credential_ref: str, bmc_host: str) -> Credentials:
        data = self._load()
        hosts = data.get("hosts") or {}
        refs = data.get("refs") or {}
        if bmc_host in hosts:
            return _creds(hosts[bmc_host], f"hosts.{bmc_host}")
        if credential_ref in refs:
            return _creds(refs[credential_ref], f"refs.{credential_ref}")
        if "default" in data:
            return _creds(data["default"], "default")
        raise CredentialError(f"no credentials for ref {credential_ref!r} or host {bmc_host!r}")

    async def aclose(self) -> None:
        return None


class VaultProvider:
    """HashiCorp Vault KV v2: ``GET <addr>/v1/<mount>/data/<path>/<credential_ref>`` -> username/password.

    Secrets are cached for ``cache_ttl_s`` so 500 BMCs do not mean 500 Vault reads a minute.
    """

    def __init__(
        self,
        addr: str,
        token: SecretStr,
        mount: str = "secret",
        path: str = "gcc/bmc",
        *,
        cache_ttl_s: float = 300.0,
        verify: bool | ssl.SSLContext = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._mount = mount.strip("/")
        self._path = path.strip("/")
        self._token = token
        self._ttl = cache_ttl_s
        self._cache: dict[str, tuple[float, Credentials]] = {}
        self._lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            base_url=addr.rstrip("/"), timeout=10.0, verify=verify, transport=transport
        )

    async def get(self, credential_ref: str, bmc_host: str) -> Credentials:
        now = time.monotonic()
        hit = self._cache.get(credential_ref)
        if hit is not None and now - hit[0] < self._ttl:
            return hit[1]
        async with self._lock:
            url = f"/v1/{self._mount}/data/{self._path}/{credential_ref}"
            try:
                resp = await self._http.get(url, headers={"X-Vault-Token": self._token.get_secret_value()})
            except httpx.HTTPError as exc:
                raise CredentialError(f"vault unreachable: {type(exc).__name__}") from None
            if resp.status_code != 200:
                raise CredentialError(f"vault returned {resp.status_code} for ref {credential_ref!r}")
            try:
                data = resp.json()["data"]["data"]
            except (ValueError, KeyError, TypeError):
                raise CredentialError(f"vault secret for ref {credential_ref!r} has no data") from None
            creds = _creds(data, f"vault ref {credential_ref!r}")
            self._cache[credential_ref] = (now, creds)
            return creds

    async def aclose(self) -> None:
        await self._http.aclose()


def make_provider(env: CollectorEnv) -> CredentialProvider:
    if env.credentials_provider == "env":
        return EnvProvider(env.bmc_username, env.bmc_password)
    if env.credentials_provider == "file":
        return FileProvider(env.credentials_file)
    if not env.vault_addr or env.vault_token is None:
        raise CredentialError("VAULT_ADDR and VAULT_TOKEN are required for the vault provider")
    return VaultProvider(env.vault_addr, env.vault_token, env.vault_mount, env.vault_path)
