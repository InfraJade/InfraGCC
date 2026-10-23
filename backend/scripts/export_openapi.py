"""Write the app API's OpenAPI schema to docs/contracts/openapi-app.json (stable formatting).

    uv run python -m scripts.export_openapi            # write the file
    uv run python -m scripts.export_openapi --check    # exit 1 if the file is out of date (CI)

The frontend generates its typed client from this file (openapi-typescript).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "openapi-app.json"


def render() -> str:
    from app.api.main import app

    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="fail if the file differs instead of writing it")
    args = parser.parse_args()
    text = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            print(f"{OUTPUT} is out of date; run python -m scripts.export_openapi", file=sys.stderr)
            return 1
        return 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
