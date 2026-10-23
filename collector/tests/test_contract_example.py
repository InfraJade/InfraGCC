"""Writes docs/contracts/ingest-batch.example.json from a real Dell adapter run (DECISIONS.md D7).

The backend's test suite validates and ingests the same file, so any drift between the two sides fails CI.
The run uses a fixed clock and batch id, so the file only changes when the adapter output changes. It is
trimmed to one server and a few items per list, but always contains every list kind.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conftest import DELL, FIXED_NOW, TreeBmc, tree_poller

from gcc_collector.adapters import ALL_KINDS
from gcc_collector.schema import Batch, ServerPayload

EXAMPLE = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "ingest-batch.example.json"
BATCH_ID = "6f1c0c1e-6a55-4f0b-9b8e-2c9a0f2b8f11"
SENT_AT = FIXED_NOW.replace(second=12)


def trim(payload: ServerPayload) -> ServerPayload:
    """One reading per metric code, two limits, every event, one component and one firmware per type."""
    readings, metrics = [], set()
    for r in payload.readings or []:
        if r.metric not in metrics:
            metrics.add(r.metric)
            readings.append(r)
    comps, comp_types = [], set()
    for c in payload.components or []:
        if c.type not in comp_types:
            comp_types.add(c.type)
            comps.append(c)
    firmware, fw_types = [], set()
    for f in payload.firmware or []:
        if f.component_type not in fw_types:
            fw_types.add(f.component_type)
            firmware.append(f)
    return payload.model_copy(
        update={
            "server_id": 1,
            "readings": readings,
            "bmc_limits": (payload.bmc_limits or [])[:2],
            "components": comps,
            "firmware": firmware,
        }
    )


def _line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def render(batch: dict[str, Any]) -> str:
    """Same layout as the hand-written file: one list item per line, identity as a block."""
    out = ["{"]
    for key in ("schema", "batch_id", "collector", "sent_at"):
        out.append(f'  "{key}": {_line(batch[key])},')
    out.append('  "servers": [')
    for si, server in enumerate(batch["servers"]):
        out.append("    {")
        keys = list(server)
        for ki, key in enumerate(keys):
            comma = "," if ki < len(keys) - 1 else ""
            value = server[key]
            if isinstance(value, list):
                out.append(f'      "{key}": [')
                for ii, item in enumerate(value):
                    out.append(f"        {_line(item)}" + ("," if ii < len(value) - 1 else ""))
                out.append(f"      ]{comma}")
            elif isinstance(value, dict):
                out.append(f'      "{key}": {{')
                items = list(value.items())
                for ii, (k, v) in enumerate(items):
                    out.append(f'        "{k}": {_line(v)}' + ("," if ii < len(items) - 1 else ""))
                out.append(f"      }}{comma}")
            else:
                out.append(f'      "{key}": {_line(value)}{comma}')
        out.append("    }" + ("," if si < len(batch["servers"]) - 1 else ""))
    out.append("  ]")
    out.append("}")
    return "\n".join(out) + "\n"


async def test_write_ingest_batch_example() -> None:
    poller = tree_poller(TreeBmc(DELL))
    result = await poller.poll(ALL_KINDS)
    await poller.close()
    assert result.ok
    batch = Batch(batch_id=BATCH_ID, collector="pnq1-col-a", sent_at=SENT_AT, servers=[trim(result.payload)])
    wire = batch.to_json_dict()
    server = wire["servers"][0]
    for kind in ("readings", "bmc_limits", "events", "identity", "components", "firmware"):
        assert server.get(kind), f"example must contain {kind}"
    assert {r["metric"] for r in server["readings"]} >= {"inlet_temp_c", "bmc_reachable", "nic_link"}

    text = render(wire)
    assert json.loads(text) == wire
    EXAMPLE.write_text(text, encoding="utf-8", newline="\n")

    # The file on disk validates against the collector's contract models and round-trips exactly.
    reparsed = Batch.model_validate(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    assert reparsed.to_json_dict() == wire
