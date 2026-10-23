"""Wires the collector together: config refresh, scheduler, sender, heartbeat, graceful shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import socket
import ssl
from pathlib import Path

from pydantic import ValidationError

from gcc_collector import __version__
from gcc_collector.buffer import DiskBuffer
from gcc_collector.cloud import CloudClient, IngestError
from gcc_collector.config import CollectorEnv
from gcc_collector.credentials import CredentialProvider, Credentials, make_provider
from gcc_collector.metrics import HEARTBEATS, RollingStats, start_metrics_server
from gcc_collector.poller import ServerPoller
from gcc_collector.redfish.client import RedfishClient, shared_tls_context
from gcc_collector.scheduler import Scheduler
from gcc_collector.schema import CollectorConfig, CollectorSettings, Heartbeat, HeartbeatStats, ServerConfig
from gcc_collector.sender import Sender

log = logging.getLogger("gcc.collector")

CONFIG_CACHE = "config-cache.json"


def bmc_tls(env: CollectorEnv) -> ssl.SSLContext:
    """One TLS context shared by every BMC client."""
    if env.bmc_verify_tls and env.bmc_ca_bundle is not None:
        return ssl.create_default_context(cafile=str(env.bmc_ca_bundle))
    return shared_tls_context(env.bmc_verify_tls)


class Collector:
    def __init__(
        self,
        env: CollectorEnv,
        *,
        cloud: CloudClient | None = None,
        credentials: CredentialProvider | None = None,
    ) -> None:
        self.env = env
        self.cloud = cloud or CloudClient(env)
        self.credentials = credentials or make_provider(env)
        self.buffer = DiskBuffer(env.buffer_dir, env.buffer_ttl_s)
        self.sender = Sender(self.cloud, self.buffer, env.collector_name)
        self.stats = RollingStats()
        self.settings = CollectorSettings()
        self.config_version: str | None = None
        self.stop = asyncio.Event()
        self.refresh_now = asyncio.Event()
        self._semaphore: asyncio.Semaphore | None = None
        self._tls = bmc_tls(env)
        self.scheduler = Scheduler(self.settings, self._make_poller, self.sender.add, self.stats)

    # ------------------------------------------------------------------------------- pollers
    def _make_poller(self, server: ServerConfig) -> ServerPoller:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.settings.max_parallel_bmcs)

        async def creds() -> Credentials:
            return await self.credentials.get(server.credential_ref, server.bmc_host)

        client = RedfishClient(
            server.bmc_host,
            creds,
            verify=self._tls,
            timeout=float(self.settings.request_timeout_s),
            semaphore=self._semaphore,
        )
        return ServerPoller(server, client)

    # -------------------------------------------------------------------------------- config
    @property
    def _cache_path(self) -> Path:
        return self.env.buffer_dir / CONFIG_CACHE

    def _apply(self, config: CollectorConfig) -> None:
        if config.config_version == self.config_version:
            return
        if (
            self._semaphore is not None
            and config.settings.max_parallel_bmcs != self.settings.max_parallel_bmcs
        ):
            log.warning("max_parallel_bmcs changed; it takes effect after a restart")
        self.settings = config.settings
        self.scheduler.update(config.servers, config.settings)
        self.config_version = config.config_version
        log.info(
            "config %s: %d servers (%d taken over)",
            config.config_version,
            len(config.servers),
            sum(1 for s in config.servers if s.takeover),
        )

    async def refresh_config(self) -> bool:
        try:
            config = await self.cloud.get_config()
        except (IngestError, ValidationError, ValueError) as exc:
            log.warning("cannot fetch config: %s", exc)
            return False
        self._apply(config)
        try:
            await asyncio.to_thread(self._cache_path.write_text, config.model_dump_json(), "utf-8")
        except OSError as exc:
            log.warning("cannot cache config: %s", exc)
        return True

    def load_cached_config(self) -> bool:
        """Start polling from the last known config when the cloud is unreachable at start-up."""
        try:
            config = CollectorConfig.model_validate_json(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError):
            return False
        log.warning("cloud unreachable; polling with cached config %s", config.config_version)
        self._apply(config)
        return True

    async def config_loop(self) -> None:
        while not self.stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.refresh_now.wait(), timeout=self.settings.config_refresh_s)
            self.refresh_now.clear()
            if self.stop.is_set():
                break
            await self.refresh_config()

    # ----------------------------------------------------------------------------- heartbeat
    def heartbeat_body(self) -> Heartbeat:
        snap = self.stats.snapshot()
        batches, size = self.buffer.stats()
        stats = HeartbeatStats.model_validate(
            {
                **snap,
                "servers_assigned": len(self.scheduler.entries),
                "buffer_batches": batches,
                "buffer_bytes": size,
                "last_batch_at": self.sender.last_batch_at,
            }
        )
        return Heartbeat(
            collector=self.env.collector_name,
            version=__version__,
            hostname=socket.gethostname(),
            sent_at=self.sender.clock(),
            config_version=self.config_version,
            stats=stats,
        )

    async def send_heartbeat(self) -> None:
        try:
            resp = await self.cloud.heartbeat(self.heartbeat_body())
        except IngestError as exc:
            HEARTBEATS.labels(result="failed").inc()
            log.warning("heartbeat failed: %s", exc)
            return
        HEARTBEATS.labels(result="ok").inc()
        if resp.config_version and resp.config_version != self.config_version:
            self.refresh_now.set()

    async def heartbeat_loop(self) -> None:
        while not self.stop.is_set():
            await self.send_heartbeat()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.stop.wait(), timeout=self.settings.heartbeat_interval_s)

    # ----------------------------------------------------------------------------------- run
    async def run(self) -> None:
        start_metrics_server(self.env.metrics_port)
        log.info(
            "collector %s %s starting (ingest %s, %s auth)",
            self.env.collector_name,
            __version__,
            self.env.ingest_url,
            self.env.ingest_auth_mode,
        )
        if not await self.refresh_config() and not self.load_cached_config():
            while not self.stop.is_set() and not await self.refresh_config():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self.stop.wait(), timeout=10)
        tasks = [
            asyncio.create_task(self.scheduler.run(self.stop), name="scheduler"),
            asyncio.create_task(
                self.sender.run(lambda: self.settings.batch_interval_s, self.stop), name="sender"
            ),
            asyncio.create_task(self.heartbeat_loop(), name="heartbeat"),
            asyncio.create_task(self.config_loop(), name="config"),
        ]
        await self.stop.wait()
        log.info("shutting down")
        self.refresh_now.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.shutdown()

    async def shutdown(self) -> None:
        """Finish or cancel polls, persist unsent data to the buffer, delete BMC sessions, close clients."""
        await self.scheduler.close()
        await self.sender.flush_to_disk()
        await self.cloud.aclose()
        await self.credentials.aclose()
        log.info("stopped; %d batches buffered", self.buffer.stats()[0])

    def install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.stop.set)
            except (NotImplementedError, RuntimeError):  # Windows event loops
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(self.stop.set))


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
