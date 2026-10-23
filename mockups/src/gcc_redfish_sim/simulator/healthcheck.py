"""Container health check: `python -m gcc_redfish_sim.simulator.healthcheck` exits 0 when /health answers."""

from __future__ import annotations

import os
import sys
import urllib.request


def main() -> int:
    port = os.environ.get("SIM_CONTROL_PORT", "9100").strip() or "9100"
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/health", timeout=3) as resp:
            return 0 if resp.status == 200 else 1
    except (OSError, ValueError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
