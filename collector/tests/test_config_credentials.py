"""Environment config, credential providers (env / file / Vault) and the heartbeat/config cycle."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from gcc_collector.app import Collector
from gcc_collector.cloud import CloudClient
from gcc_collector.config import load_env
from gcc_collector.credentials import (
    CredentialError,
    EnvProvider,
    FileProvider,
    VaultProvider,
    make_provider,
)
from gcc_collector.schema import Heartbeat

EXAMPLE_CREDENTIALS = Path(__file__).resolve().parents[1] / "credentials.example.yaml"


def test_load_env_defaults_and_values() -> None:
    env = load_env({"GCC_COLLECTOR_NAME": "pnq1-col-a", "GCC_BMC_VERIFY_TLS": "false", "GCC_INGEST_URL": ""})
    assert env.ingest_url == "http://localhost:8001"
    assert env.bmc_verify_tls is False
    assert env.buffer_dir == Path("/var/lib/gcc-collector/buffer")
    assert env.buffer_ttl_s == 86400
    assert env.metrics_port == 9108
    assert env.ingest_auth_mode == "token"
    mtls = load_env({"GCC_COLLECTOR_NAME": "x", "GCC_CLIENT_CERT": "/c.pem", "GCC_CLIENT_KEY": "/k.pem"})
    assert mtls.ingest_auth_mode == "mtls"


def test_load_env_requires_name() -> None:
    with pytest.raises(ValueError):
        load_env({})
    with pytest.raises(ValueError):
        load_env({"GCC_COLLECTOR_NAME": "x", "GCC_BMC_VERIFY_TLS": "maybe"})


async def test_env_provider_and_secret_hygiene(caplog: pytest.LogCaptureFixture) -> None:
    env = load_env(
        {"GCC_COLLECTOR_NAME": "x", "GCC_BMC_USERNAME": "gcc-monitor", "GCC_BMC_PASSWORD": "s3cret"}
    )
    provider = make_provider(env)
    assert isinstance(provider, EnvProvider)
    got = await provider.get("default", "10.0.0.1")
    assert got.username == "gcc-monitor"
    assert got.password.get_secret_value() == "s3cret"
    assert "s3cret" not in repr(got) and "s3cret" not in repr(env)
    with pytest.raises(CredentialError):
        make_provider(load_env({"GCC_COLLECTOR_NAME": "x"}))


async def test_file_provider_lookup_order(tmp_path: Path) -> None:
    path = tmp_path / "credentials.yaml"
    path.write_text(
        "default: {username: gcc-monitor, password: dflt}\n"
        "refs:\n  hyd-lab: {username: lab, password: labpw}\n"
        "hosts:\n  '10.0.0.9': {username: special, password: hostpw}\n",
        encoding="utf-8",
    )
    provider = FileProvider(path)
    assert (await provider.get("default", "10.0.0.1")).password.get_secret_value() == "dflt"
    assert (await provider.get("hyd-lab", "10.0.0.1")).username == "lab"
    assert (await provider.get("hyd-lab", "10.0.0.9")).username == "special"
    path.write_text("refs: {}\n", encoding="utf-8")

    os.utime(path, (1, 1))  # force a different mtime so the file is re-read
    with pytest.raises(CredentialError):
        await provider.get("default", "10.0.0.1")


async def test_file_provider_with_example_file() -> None:
    provider = FileProvider(EXAMPLE_CREDENTIALS)
    assert (await provider.get("default", "bmc")).username == "gcc-monitor"


async def test_vault_provider_kv2_and_cache() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.headers.get("X-Vault-Token") != "root-token":
            return httpx.Response(403)
        if request.url.path == "/v1/secret/data/gcc/bmc/default":
            return httpx.Response(200, json={"data": {"data": {"username": "gcc-monitor", "password": "v"}}})
        return httpx.Response(404)

    provider = VaultProvider(
        "http://vault:8200", SecretStr("root-token"), transport=httpx.MockTransport(handler)
    )
    first = await provider.get("default", "h")
    second = await provider.get("default", "h2")
    assert first == second and first.password.get_secret_value() == "v"
    assert len(calls) == 1  # cached
    with pytest.raises(CredentialError) as err:
        await provider.get("missing", "h")
    assert "404" in str(err.value)
    await provider.aclose()


class FakeCloud:
    def __init__(self) -> None:
        self.version = "v1"
        self.heartbeats: list[dict[str, object]] = []
        self.config_calls = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/ingest/v1/config":
            self.config_calls += 1
            return httpx.Response(
                200,
                json={
                    "collector": {"id": 1, "name": "pnq1-col-a", "site_code": "PNQ1"},
                    "config_version": self.version,
                    "settings": {"sensor_interval_s": 60, "max_parallel_bmcs": 50},
                    "servers": [
                        {
                            "id": 12,
                            "bmc_host": "http://bmc-simulator:20001",
                            "vendor": "Dell",
                            "status": "active",
                            "credential_ref": "default",
                            "takeover": False,
                            "future_field": 1,
                        }
                    ],
                },
            )
        if request.url.path == "/ingest/v1/heartbeat":
            body = json.loads(request.content)
            Heartbeat.model_validate(body)
            self.heartbeats.append(body)
            return httpx.Response(200, json={"ok": True, "config_version": self.version})
        return httpx.Response(404)


async def test_config_and_heartbeat_cycle(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    env = load_env(
        {
            "GCC_COLLECTOR_NAME": "pnq1-col-a",
            "GCC_INGEST_URL": "http://ingest.test",
            "GCC_INGEST_TOKEN": "dev-ingest-token",
            "GCC_BUFFER_DIR": str(tmp_path),
            "GCC_BMC_USERNAME": "gcc-monitor",
            "GCC_BMC_PASSWORD": "dev-bmc-pw",
        }
    )
    fake = FakeCloud()
    collector = Collector(env, cloud=CloudClient(env, transport=httpx.MockTransport(fake.handler)))
    assert await collector.refresh_config()
    assert collector.config_version == "v1"
    assert set(collector.scheduler.entries) == {12}
    assert (tmp_path / "config-cache.json").exists()

    await collector.send_heartbeat()
    hb = fake.heartbeats[-1]
    assert hb["collector"] == "pnq1-col-a" and hb["config_version"] == "v1"
    stats = hb["stats"]
    assert isinstance(stats, dict) and stats["servers_assigned"] == 1
    assert not collector.refresh_now.is_set()

    fake.version = "v2"  # an admin onboarded a server: heartbeat says the config changed
    await collector.send_heartbeat()
    assert collector.refresh_now.is_set()

    # A restart while the cloud is down polls with the cached config.
    offline = Collector(
        env,
        cloud=CloudClient(env, transport=httpx.MockTransport(lambda r: httpx.Response(503))),
    )
    assert not await offline.refresh_config()
    assert offline.load_cached_config()
    assert set(offline.scheduler.entries) == {12}

    assert "dev-bmc-pw" not in caplog.text and "dev-ingest-token" not in caplog.text
    await collector.shutdown()
    await offline.shutdown()
