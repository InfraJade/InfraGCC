"""Write the static vendor mockup trees in DMTF Redfish Mockup Server format.

    python -m gcc_redfish_sim.generate [--out mockups/trees]

Each tree is `<out>/<name>/redfish/v1/.../index.json`, served unchanged by
`redfishMockupServer.py -D <out>/<name>` and replayed by the collector's adapter tests.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from gcc_redfish_sim.catalog import make_state
from gcc_redfish_sim.tree import build_tree

# (directory name, model key, simulated index). Indexes 9001+ keep serials apart from the simulated fleet.
REFERENCE_TREES = [
    ("dell-poweredge-r750", "dell-r750", 9001),
    ("hpe-proliant-dl380-gen10", "hpe-dl380-gen10", 9002),
    ("lenovo-thinksystem-sr650-v3", "lenovo-sr650-v3", 9003),
]

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "trees"


def write_tree(out_dir: Path, name: str, model_key: str, index: int) -> int:
    root = out_dir / name
    if root.exists():
        shutil.rmtree(root)
    tree = build_tree(make_state(model_key, index))
    for path, body in tree.items():
        target = root / path.lstrip("/") / "index.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (root / "redfish" / "index.json").write_text(json.dumps({"v1": "/redfish/v1/"}, indent=2) + "\n")
    return len(tree)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    for name, model_key, index in REFERENCE_TREES:
        count = write_tree(args.out, name, model_key, index)
        print(f"{name}: {count} resources")


if __name__ == "__main__":
    main()
