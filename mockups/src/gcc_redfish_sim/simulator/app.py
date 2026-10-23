"""Entry point: `gcc-bmc-simulator` serves SIM_COUNT virtual BMCs and the control API in one process."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
from datetime import UTC, datetime

from aiohttp import web

from gcc_redfish_sim.simulator.config import ConfigError, SimConfig
from gcc_redfish_sim.simulator.control import TeamsSink, create_control_app
from gcc_redfish_sim.simulator.fleet import Fleet
from gcc_redfish_sim.simulator.redfish import create_bmc_app

log = logging.getLogger("gcc_bmc_simulator")


async def drift_loop(fleet: Fleet, step_s: float, stop: asyncio.Event) -> None:
    while not stop.is_set():
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=step_s)
        if not stop.is_set():
            try:
                fleet.step(datetime.now(UTC))
            except Exception:  # keep simulating; one bad step must not stop every BMC
                log.exception("drift step failed")


async def serve(config: SimConfig, stop: asyncio.Event) -> None:
    fleet = Fleet(config)
    access_log = logging.getLogger("aiohttp.access") if config.access_log else None
    runners: list[web.AppRunner] = []
    try:
        control = web.AppRunner(
            create_control_app(fleet, TeamsSink()), access_log=access_log, shutdown_timeout=1.0
        )
        runners.append(control)
        await control.setup()
        await web.TCPSite(control, config.host, config.control_port, shutdown_timeout=1.0).start()
        for bmc in fleet.bmcs.values():
            app = create_bmc_app(bmc, config.username, config.password)
            runner = web.AppRunner(app, access_log=access_log, shutdown_timeout=1.0)
            runners.append(runner)
            await runner.setup()
            await web.TCPSite(runner, config.host, bmc.port, shutdown_timeout=1.0).start()
        log.info(
            "simulating %d BMCs on %s ports %d-%d; control API on port %d; fault rate %.3g/BMC/h; seed %s",
            len(fleet.bmcs),
            config.host,
            config.port_for(1),
            config.port_for(config.count),
            config.control_port,
            config.fault_rate_per_hour,
            config.seed if config.seed is not None else "random",
        )
        await drift_loop(fleet, config.step_s, stop)
    finally:
        for bmc in fleet.bmcs.values():  # release requests hanging on an unresponsive BMC
            bmc.release_waiters()
        for runner in reversed(runners):
            await runner.cleanup()
        log.info("simulator stopped")


async def _main(config: SimConfig) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # Windows: Ctrl+C raises KeyboardInterrupt instead
            loop.add_signal_handler(sig, stop.set)
    await serve(config, stop)


def main() -> None:
    try:
        config = SimConfig.from_env()
    except ConfigError as exc:
        print(f"gcc-bmc-simulator: invalid configuration: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_main(config))


if __name__ == "__main__":
    main()
