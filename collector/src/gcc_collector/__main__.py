"""``python -m gcc_collector``: run the collector until SIGTERM / SIGINT."""

from __future__ import annotations

import asyncio
import logging
import sys

from gcc_collector.app import Collector, configure_logging
from gcc_collector.config import load_env
from gcc_collector.credentials import CredentialError


async def _main() -> None:
    env = load_env()
    configure_logging(env.log_level)
    collector = Collector(env)
    collector.install_signal_handlers()
    await collector.run()


def main() -> None:
    try:
        asyncio.run(_main())
    except (ValueError, CredentialError) as exc:  # configuration errors: say what is wrong and exit
        logging.basicConfig()
        logging.getLogger("gcc.collector").error("cannot start: %s", exc)
        sys.exit(2)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
