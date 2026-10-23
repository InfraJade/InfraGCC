# Simulated hardware: Redfish mockups and the BMC simulator

Two things live here (PLAN.md Phase 3, DECISIONS.md D26–D27):

1. **Static vendor mockup trees** (`trees/`) in DMTF Redfish Mockup Server format. The three reference BMCs
   in compose serve them unchanged, and the collector's adapter tests replay them.
2. **`gcc-bmc-simulator`**: one process that serves N virtual BMCs (one port each), with session auth,
   `$expand`, realistic drift, faults and a control API.

Both are rendered from the same code: `catalog.py` (models and initial state of each server), `model.py`
(the `ServerState`), `tree.py` (vendor-style Redfish resources from a state).

## The three trees

| Tree | BMC | Layout | Vendor specifics |
|---|---|---|---|
| `dell-poweredge-r750` | iDRAC9 7.x | **both**: newer `ThermalSubsystem`/`PowerSubsystem`/`Sensors`/`EnvironmentMetrics` **and** legacy `Thermal`/`Power` | `Oem.Dell` (DellSystem, service tag), IDs like `System.Embedded.1`, `iDRAC.Embedded.1`, `Fan.Embedded.1A`, `PSU.Slot.1`, `RAID.SL.3-1`; second chassis (drive backplane); SEL under the Manager with entries inlined in `Members`; `$expand` up to 1 level |
| `hpe-proliant-dl380-gen10` | iLO 5 | **legacy only** (`Thermal`/`Power`) | `Oem.Hpe` (PostState, PSU `BayNumber`), sensor names like `01-Inlet Ambient`, fans in **percent**; Integrated Management Log (`IML`) under the System; no `$expand` |
| `lenovo-thinksystem-sr650-v3` | XCC2 | **newer only** | `Oem.Lenovo`, `PlatformLog` under the System (plus an `AuditLog` to ignore); `$expand` up to 2 levels |

Each tree covers: service root, SessionService, AccountService, Systems (processors, memory, storage with
drives and volumes, Ethernet interfaces, log services), Chassis (thermal, power, sensors), Managers (BMC
NIC, log services), UpdateService firmware inventory (installed and `Previous-…` images). Resource IDs avoid
`:` so trees check out on Windows. The layout split follows real firmware generations; see D26.

### Regenerate

```sh
cd mockups
uv run gcc-generate-mockups          # or: uv run python -m gcc_redfish_sim.generate --out trees
git diff --stat trees                # should be empty unless you changed catalog/tree code
```

The generator updates files in place (LF line endings on every platform) and removes stale ones.
`tests/test_crawl.py` fails if the trees on disk are out of date.

### Serve with the DMTF Redfish Mockup Server

```sh
docker run --rm -p 8000:8000 -v "$PWD/trees/dell-poweredge-r750:/mockup:ro" \
  dmtf/redfish-mockup-server:latest -D /mockup -H 0.0.0.0 -p 8000
curl -s http://localhost:8000/redfish/v1/Systems/System.Embedded.1
```

(In Git Bash prefix the command with `MSYS_NO_PATHCONV=1`.) The mockup server needs no credentials.

## BMC simulator

```sh
cd mockups
uv run gcc-bmc-simulator                                   # 36 BMCs on 20001-20036, control on 9100
SIM_COUNT=3 SIM_BASE_PORT=21000 SIM_CONTROL_PORT=21900 SIM_HOST=127.0.0.1 uv run gcc-bmc-simulator
docker build -t gcc-bmc-simulator:dev . && docker run --rm -p 9100:9100 -p 20001-20036:20001-20036 gcc-bmc-simulator:dev
```

BMC *i* (1-based) listens on `SIM_BASE_PORT + i` and runs model `FLEET[(i - 1) % 6]` (Dell R750, HPE DL380
Gen10, Lenovo SR650 V3, Dell R650, HPE DL360 Gen10, Lenovo SR630 V3), the same order `backend/app/seed.py`
uses. Serials, MACs, UUIDs and service tags are unique per index. Each BMC serves exactly the paths of the
static tree of its vendor (plus log entries written later). Resources are rendered lazily and cached until
the state changes, so 500 BMCs in one process are cheap (~1.5 ms per render, only when polled).

| Variable | Default | Meaning |
|---|---|---|
| `SIM_COUNT` | `36` | Number of virtual BMCs (tested with 500) |
| `SIM_BASE_PORT` | `20000` | BMC *i* listens on `SIM_BASE_PORT + i` |
| `SIM_CONTROL_PORT` | `9100` | Control API and Teams webhook sink |
| `SIM_HOST` | `0.0.0.0` | Bind address (use `127.0.0.1` on a laptop) |
| `SIM_USERNAME` / `SIM_PASSWORD` | `gcc-monitor` / `dev-bmc-pw` | The one account every BMC accepts |
| `SIM_FAULT_RATE` | `0.05` | Random faults per BMC per hour (`0` disables) |
| `SIM_SEED` | random | Makes drift, fault targets and random faults repeatable |
| `SIM_STEP_S` | `10` | Seconds between drift steps |
| `SIM_ACCESS_LOG` | `false` | Per-request access log (off: only fault changes are logged) |
| `SIM_LOG_LEVEL` | `INFO` | |

### Redfish behaviour

- `/redfish` and `/redfish/v1` answer without credentials; everything else returns 401 (Redfish error
  `NoValidSession`) unless the request has a valid `X-Auth-Token` or HTTP Basic credentials.
- `POST /redfish/v1/SessionService/Sessions` `{"UserName": "...", "Password": "..."}` → `201`, headers
  `X-Auth-Token` and `Location: /redfish/v1/SessionService/Sessions/<id>`. `GET`/`DELETE` on the session;
  the Sessions collection lists live sessions. Idle sessions expire after 30 minutes.
- `$expand` as advertised in `ProtocolFeaturesSupported.ExpandQuery`: Dell `*`, `.`, `~` with
  `($levels=1)`; Lenovo up to `($levels=2)`; more levels than supported → 400 `QueryParameterOutOfRange`.
  HPE iLO 5 advertises nothing and ignores the parameter.
- Unknown paths → 404 `ResourceNotFound`; other methods → 405.

```sh
curl -s -D - -o /dev/null -H 'Content-Type: application/json' \
  -d '{"UserName":"gcc-monitor","Password":"dev-bmc-pw"}' http://localhost:20001/redfish/v1/SessionService/Sessions
curl -s -H "X-Auth-Token: <token>" 'http://localhost:20001/redfish/v1/Chassis/System.Embedded.1/ThermalSubsystem/Fans?$expand=.($levels=1)'
curl -s -u gcc-monitor:dev-bmc-pw http://localhost:20002/redfish/v1/Chassis/1/Thermal
```

### Drift (every `SIM_STEP_S`)

Correlated and bounded: inlet temperature follows a diurnal curve in site time (IST, peak mid-afternoon,
±1.5 °C) plus a per-rack offset; CPU load is a mean-reverting random walk (busier in business hours, or
pinned through the control API); power draw, PSU output (shared, ~94 % efficiency), CPU/DIMM temperatures,
fan speed and exhaust temperature follow load and inlet with thermal lag. Without faults every sensor stays
below the BMC's own thresholds; sensor health is always derived from those thresholds.

### Faults

| Kind | Effect | Log entry (SEL / IML / PlatformLog) |
|---|---|---|
| `fan_slow` | one fan below its lower critical RPM (HPE: 5 %), fan health Critical, fan redundancy Warning, thermal/system rollup Critical; the other fans speed up | Critical on raise, OK on clear |
| `psu_warning` | one PSU health Warning, power/system rollup Warning | Warning / OK |
| `inlet_spike` | inlet just above the BMC's upper caution (> 36 °C, health Warning); fans, exhaust and CPUs heat up over the next steps | Warning / OK |
| `drive_wear` | one drive `PredictedMediaLifeLeftPercent` 5, health Warning, storage/system rollup Warning | Warning |
| `nic_down` | the last host NIC that was up goes `LinkDown`, `SpeedMbps` 0 | Warning / OK |
| `critical_sel` | nothing but the log: a Critical entry (uncorrectable memory error) with the current time | Critical |
| `bmc_unresponsive` | the BMC accepts connections and never answers until cleared; clearing drops its sessions | OK "BMC reset" on clear |
| `power_off` | `PowerState` Off on System and Chassis; draw falls to standby, temperatures fall to near inlet, fans to minimum | OK / OK |

Faults overlay the drifting physics, so clearing one restores the resources exactly; log entries stay (they
are history), with site-local timestamps (`+05:30`). One fault of each kind per BMC at a time. Random faults
(`SIM_FAULT_RATE`) last 5–30 minutes; manual faults last `duration_s` or until cleared. Expiry is checked at
each drift step. Every raise/clear is logged as one line.

### Control API (`SIM_CONTROL_PORT`)

| Method and path | Body / query | Result |
|---|---|---|
| `GET /health` | | `{"status":"ok","bmcs":36,"ports":[20001,20036],"active_faults":0,"uptime_s":…}` |
| `GET /bmcs` | | `[{"index","port","model_key","model","vendor","serial","power_state","health","load","faults":[…]}]` |
| `GET /bmcs/{i}` | | one BMC |
| `POST /bmcs/{i}/load` | `{"load": 0.9}` or `{"load": null}` | pins the workload (takes effect over the next steps) / unpins |
| `GET /faults` | | active faults |
| `POST /faults` | `{"bmc": 5, "kind": "fan_slow", "duration_s": 600}` | `201` with the fault (`id`, `target`, `expires_at`); `409` if that kind is already active |
| `DELETE /faults/{id}` | | clears one fault |
| `DELETE /faults` | | clears all: `{"cleared": n}` |
| `POST /webhooks/teams/{channel}` | any JSON (Teams card) | `200` text `1`, like a Teams incoming webhook; last 500 kept |
| `GET /webhooks/teams` | `?channel=PNQ1&limit=20` | stored posts, newest first |
| `DELETE /webhooks/teams` | | forget stored posts |

Errors are `application/problem+json`.

```sh
curl -s localhost:9100/bmcs
curl -s -X POST localhost:9100/faults -H 'Content-Type: application/json' -d '{"bmc": 1, "kind": "inlet_spike", "duration_s": 600}'
curl -s -X POST localhost:9100/faults -H 'Content-Type: application/json' -d '{"bmc": 2, "kind": "bmc_unresponsive"}'
curl -s localhost:9100/faults
curl -s -X DELETE localhost:9100/faults/1
curl -s -X DELETE localhost:9100/faults
curl -s -X POST localhost:9100/bmcs/3/load -H 'Content-Type: application/json' -d '{"load": 0.95}'
curl -s 'localhost:9100/webhooks/teams?channel=PNQ1'
```

## Development

```sh
cd mockups
uv sync
uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest
```

Tests cover drift bounds over 25 simulated hours per model, every fault's resources/rollups/log and its
clean removal, auth and sessions, `$expand` per vendor, a link crawl of every model, the static-tree paths
and freshness, and the control API.
