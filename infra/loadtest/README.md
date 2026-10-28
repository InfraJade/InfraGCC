# 500-server load test

Checks the stack against the design targets (docs/DESIGN.md "Proposed success measures", "Sizing and
performance", "Load test") with 500 simulated BMCs, and writes a pass/fail report.

| Target | Design | How the runner measures it |
|---|---|---|
| Ingest throughput | about 330 readings/s at 500 servers | rows in `readings` with `time` inside the window ÷ window length (counted 30 s after the window, so batches in flight land); pass at ≥ 90 % of the estimate scaled to the fleet size |
| Servers reporting | ≥ 99 % of onboarded servers report every 5 minutes | distinct servers with a reading (other than `bmc_reachable`) in each full 5-minute bucket of the window; worst bucket |
| Live freshness | live readings < 2 minutes old | every 30 s: share of onboarded servers whose newest `latest_readings` row is < 120 s old; worst sample ≥ 99 % |
| Ingest lag | ingest keeps up, no growing lag | every 30 s: p95 over servers of `now() − newest reading`; worst sample < 120 s, and the mean of the last third of the samples at most 15 s above the first third |
| Alert delay | alert within 2 minutes | see below; < 120 s |
| Dashboards | 30-day views < 3 s | the queries in `queries.py` over 30 days as `gcc_superset_ro`, 3 runs each; slowest run < 3 s |

All "now" values come from the database clock, which is the same Docker host clock the collectors stamp
readings with.

## Alert delay, measured fairly

At the start of the window the runner clears faults on one simulated BMC (default: the last one, in the
load-test racks), checks there is no open inlet alert for that server, and injects `inlet_spike`
(`POST http://localhost:9100/faults {"bmc": 500, "kind": "inlet_spike"}`, inlet ≥ 37.5 °C). It polls
`alerts` every 2 s until a new row for that server and `inlet_temp_c` appears, then clears the fault.

The inlet rule only fires after the value has stayed bad for its hold duration (3 minutes, D14), and the
first bad value can only be seen at the next 60-second poll. Neither is alerting latency, so:

    delay = alert first visible − (first ingested inlet reading above the warning threshold + rule duration)

The report also lists injection → first bad reading (poll delay) and injection → alert (end to end). The
delay can be clamped to 0: the evaluation window can turn all-bad slightly before
`first bad + duration` because the last good sample was earlier.

## Machine

Docker with at least 8 CPU threads and 16 GB RAM (the overlay caps the database at 4 CPUs / 6 GB, the
simulator, ingest API and each collector at 2 CPUs). About 15 GB free disk for 30 days of history at the
default profile. The 30-day backfill takes minutes on an idle machine and much longer on a busy one.

## Run

```sh
# from the repo root; an empty volume so the database tuning in the overlay applies
docker compose down -v
docker compose -f compose.yaml -f infra/loadtest/compose.loadtest.yaml up -d --build
docker compose -f compose.yaml -f infra/loadtest/compose.loadtest.yaml ps    # wait until healthy

# full run: 30-day history check/backfill, 5 min warm-up, 10 min window, alert, dashboard queries
uv run --project infra/loadtest python infra/loadtest/runner.py

# quicker: 1 min warm-up, 3 min window
uv run --project infra/loadtest python infra/loadtest/runner.py --quick

# dashboard timing only, against any database with the schema (e.g. a scratch copy)
uv run --project infra/loadtest python infra/loadtest/runner.py --skip-live \
  --db-url postgresql://gcc_owner:dev-owner-pw@localhost:15433/gcc \
  --ro-db-url postgresql://gcc_superset_ro:dev-superset-ro-pw@localhost:15433/gcc
```

Reports go to `infra/loadtest/reports/<UTC timestamp>.md` and `.json` (git-ignored). The exit code is 1 if
any measured target failed.

Useful options (`--help` for all): `--window-min`, `--warmup-min`, `--sample-s`, `--alert-bmc`,
`--history-days`, `--history-profile handful|dashboard|full`, `--history-safe`, `--skip-history`,
`--skip-alert`, `--skip-queries`. Connection settings can also come from `LOADTEST_DB_URL`,
`LOADTEST_RO_DB_URL` and `LOADTEST_SIM_URL`.

Overlay variables: `LOADTEST_SERVERS` (500), `LOADTEST_SIM_FAULT_RATE` (0), `LOADTEST_TS_TUNE_MEMORY` (4GB),
`LOADTEST_TS_TUNE_NUM_CPUS` (4).

## Fleet layout

`migrate` runs the dev seed (36 simulated BMCs + 3 DMTF reference BMCs) and then
`python -m app.seed loadtest --servers 500`, which onboards BMCs 37–500 into "Load Test Hall" racks
alternating between PNQ1 and HYD1. Collectors are assigned per site, so `collector-pnq1-a` and
`collector-pnq1-b` split PNQ1's half (about 125 servers each) and `collector-hyd1-a` polls HYD1's half
(about 250), which is the per-collector load of one pair splitting 500 servers.

## History backfill

The window only produces minutes of data, so before measuring the runner makes sure `readings` reaches back
`--history-days` (30): it writes one sample per series every 5 minutes for every onboarded server, from the
range start up to the oldest existing reading (live data is never touched), newest day first, then refreshes
`readings_5m` and `readings_1h` for each day. One sample per 5 minutes yields the same number of rollup rows
as real 60-second data. Profiles: `handful` (inlet, exhaust, power, 2 CPU temperatures), `dashboard`
(+ 6 fans; default), `full` (28 series, closer to a real server's ~50).

As a superuser (the compose `gcc_owner`) it skips per-row FK checks for the bulk COPY
(`session_replication_role = replica`) and inserts each day's first and last row with triggers on in the same
transaction, so TimescaleDB still logs an invalidation for the whole day. `--history-safe` uses plain COPY.

## Tests

```sh
cd infra/loadtest
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```
