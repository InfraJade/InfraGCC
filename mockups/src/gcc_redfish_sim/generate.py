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


def _render(body: object) -> str:
    return json.dumps(body, indent=2, ensure_ascii=False) + "\n"


def write_tree(out_dir: Path, name: str, model_key: str, index: int) -> int:
    """Write one tree in place: changed files are rewritten, stale ones removed.

    The tree is updated in place (not deleted and rewritten) so a mockup server or test reading it at the
    same time never sees it missing. Files are written with LF line endings on every platform.
    """
    root = out_dir / name
    tree = build_tree(make_state(model_key, index))
    files = {root / path.lstrip("/") / "index.json": _render(body) for path, body in tree.items()}
    files[root / "redfish" / "index.json"] = _render({"v1": "/redfish/v1/"})
    for target, text in files.items():
        if target.is_file() and target.read_bytes() == text.encode("utf-8"):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    if root.exists():
        for stale in sorted(set(root.rglob("index.json")) - set(files)):
            stale.unlink()
        for directory in sorted((d for d in root.rglob("*") if d.is_dir()), key=lambda d: -len(d.parts)):
            if not any(directory.iterdir()):
                shutil.rmtree(directory, ignore_errors=True)
    return len(tree)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    for name, model_key, index in REFERENCE_TREES:
        count = write_tree(args.out, name, model_key, index)
        print(f"{name}: {count} resources")


if __name__ == "__main__":
    main()
