# Collector ↔ ingest contract (v1)

The on-prem collector and the cloud ingest API deploy separately, so each owns its own Pydantic models
(DECISIONS.md D7). This file is the written contract; `ingest-batch.example.json` is the executable one:
the collector's test suite writes it from a real adapter run against the mockup trees, and the backend's
test suite validates and ingests it. Any drift fails CI.

All bodies are JSON (UTF-8). Times are ISO 8601 with offset (UTC, `Z`). Unknown fields are rejected by
ingest (`extra="forbid"`), so additions are a contract change: bump `schema` and update both sides.

## Authentication

| Mode (`INGEST_AUTH_MODE`) | Collector sends | Ingest checks |
|---|---|---|
| `token` (dev) | `Authorization: Bearer <INGEST_SHARED_TOKEN>` and `X-Collector-Name: <name>` | token matches; the name is an enabled row in `collectors` |
| `mtls` (prod) | client certificate on the TLS connection (terminated by nginx, `infra/nginx/ingest-mtls.conf`) | `X-Client-Cert-Fingerprint` from a trusted proxy matches `collectors.cert_fingerprint` |

Errors are RFC 9457 `application/problem+json`. 401 = unknown collector / bad token, 413 = body too
large, 422 = validation error (`errors` array lists each field).

## `GET /ingest/v1/config`

What this collector should poll right now. Collectors call it on start and every `config_refresh_s`.

```json
{
  "collector": {"id": 1, "name": "pnq1-col-a", "site_code": "PNQ1"},
  "config_version": "9f2c1e0a",
  "settings": {
    "sensor_interval_s": 60,
    "health_interval_s": 300,
    "inventory_interval_s": 86400,
    "batch_interval_s": 12,
    "heartbeat_interval_s": 30,
    "config_refresh_s": 60,
    "max_parallel_bmcs": 50,
    "request_timeout_s": 20
  },
  "servers": [
    {
      "id": 12,
      "bmc_host": "http://bmc-simulator:20001",
      "vendor": "Dell",
      "status": "active",
      "credential_ref": "default",
      "takeover": false
    }
  ]
}
```

- `bmc_host`: `host`, `host:port`, or a full base URL. A bare host means `https://host`. A value with an
  explicit `http://` scheme is only used for simulators/mockups.
- `vendor`: last vendor the cloud saw (from inventory), or `null` before first contact. The collector still
  detects the vendor itself from the service root / Systems resource; this is only a hint.
- `status`: `active` or `maintenance` (still polled). Decommissioned servers are not listed.
- `credential_ref`: key the collector's credential provider resolves locally (`default` unless an admin set
  one). Passwords never cross this API.
- `takeover`: `true` when the server's preferred collector is offline and this collector covers it (D9).
- `config_version`: opaque hash of the response; it changes whenever the server list or settings change.

## `POST /ingest/v1/batches`

`Content-Type: application/json`, `Content-Encoding: gzip` (ingest also accepts uncompressed bodies).
Max body 20 MiB after decompression. Idempotent by `batch_id` (replays after a network failure are
accepted and ignored: `"duplicate": true`).

```json
{
  "schema": 1,
  "batch_id": "6f1c0c1e-6a55-4f0b-9b8e-2c9a0f2b8f11",
  "collector": "pnq1-col-a",
  "sent_at": "2026-10-22T10:00:12Z",
  "servers": [ServerPayload, ...]
}
```

### ServerPayload

Every list is optional (omitted or `null` = "nothing new of this kind"). An empty list `[]` for
`components` / `firmware` means "the server has none" and is rarely what you want.

| Field | Type | Meaning |
|---|---|---|
| `server_id` | int | From the config response |
| `polled_at` | time | When this poll finished |
| `readings` | Reading[] | Sensor and state samples (60 s and 5 min schedules) |
| `bmc_limits` | BmcLimit[] | Thresholds the BMC reports per sensor (send with the 5 min or daily poll) |
| `events` | Event[] | New log entries since the last poll (collector tracks the last seen entry per log) |
| `identity` | Identity | Server identity from Systems/Chassis/Managers (daily, and on first contact) |
| `components` | Component[] | **Full** snapshot of parts (daily). Parts missing from a snapshot are marked removed |
| `firmware` | Firmware[] | **Full** snapshot of installed firmware (daily) |

### Reading

```json
{"time": "2026-10-22T10:00:01Z", "metric": "inlet_temp_c", "component": "", "value": 22.5, "status": "OK"}
```

- `metric`: a `metric_definitions.code` (27 codes, see `backend/alembic/versions/0004_reference_data.py`).
  Not `sel_event` or `firmware_version`; those travel as `events` / `firmware`.
- `component`: `""` for server-level sensors (inlet, exhaust, power draw/capacity/limit, power state,
  system health, BMC health/reachable, fan/PSU redundancy). Otherwise the normalized part name (D13):
  `CPU1`, `CPU2`, `DIMM A1`, `Fan 1`, `PSU 1`, `Disk 0`, `RAID.SL.3-1` (controller), `Volume 0`, `NIC 1`.
- `value` and `status` by metric type:

| Metrics | `value` | `status` |
|---|---|---|
| gauges (`*_temp_c`, `fan_rpm`, `fan_pct`, `power_*_w`, `psu_input_v`, `drive_life_pct`) | the number | sensor health `OK`/`Warning`/`Critical` if the BMC gives one, else `null` |
| health states (`*_health`, `fan_redundancy`, `psu_redundancy`) | 0 OK, 1 Warning, 2 Critical, `null` unknown | `OK` / `Warning` / `Critical` / `Unknown` |
| `power_state` | 1 On, 0 Off | `On` / `Off` (or the raw Redfish value, e.g. `PoweringOn`) |
| `nic_link` | 1 Up, 0 Down | `Up` / `Down` (Redfish `LinkUp` → `Up`, `LinkDown`/`NoLink` → `Down`) |
| `bmc_reachable` | 1 yes, 0 no | `Reachable` / `Unreachable` |

When a BMC does not answer, the collector sends one reading `bmc_reachable = 0` (`Unreachable`) for that
cycle and nothing else for the server. The ingest API derives `health_status` rows from all state metrics.

### BmcLimit

```json
{"metric": "cpu_temp_c", "component": "CPU1",
 "lower_critical": null, "lower_warning": null, "upper_warning": 85.0, "upper_critical": 95.0}
```

From Redfish `UpperThresholdNonCritical`/`UpperThresholdCritical`/`LowerThreshold…` (legacy) or
`Thresholds.UpperCaution/UpperCritical/LowerCaution/LowerCritical.Reading` (newer layout).

### Event

```json
{"entry_id": "Sel/2", "time": "2026-10-01T08:00:00Z", "severity": "Critical",
 "message": "The system inlet temperature is greater than the upper critical threshold.",
 "message_id": "TMP0120"}
```

`entry_id` is `<LogService Id>/<entry Id>`, unique per server. `severity` is `OK`, `Warning` or `Critical`.

### Identity

```json
{"vendor": "Dell", "model": "PowerEdge R750", "serial": "7XK2M93", "sku": "R750",
 "hostname": "pnq1-a01-r750-01", "uuid": "4c4c4544-…", "asset_tag": null,
 "bmc_model": "iDRAC9", "bmc_firmware": "7.10.70.00", "bmc_mac": "D0:8E:79:00:00:10",
 "system_path": "/redfish/v1/Systems/System.Embedded.1", "host_ips": ["10.20.1.11"]}
```

`vendor` is normalized to `Dell`, `HPE`, `Lenovo` or the raw manufacturer string for others.

### Component

```json
{"type": "drive", "name": "Disk 0", "model": "MZ7LH960HAJR0D3", "manufacturer": "Samsung",
 "serial": "S45NNE0R123456", "capacity": 960.0, "capacity_unit": "GB", "firmware_version": "HXT7904Q",
 "location": "Bay 0", "link_up": null, "extra": {"media": "SSD", "protocol": "SATA"}}
```

`type` ∈ `cpu`, `dimm`, `drive`, `psu`, `fan`, `nic`, `storage_controller`, `volume`. `name` matches the
`component` used in readings. `link_up` is only set for NICs (feeds `expected_link_up` on first sighting, D19).
Capacities: CPUs in cores (`capacity_unit` `cores`), DIMMs `GiB`, drives `GB`, PSUs `W`, NICs `Mbps`, volumes `GB`.

### Firmware

```json
{"component": "BIOS", "component_key": "BIOS", "component_type": "bios", "version": "1.15.2"}
```

`component_key` is what baselines match: `BIOS`, `BMC`, `CPLD`, `PSU`, `NIC`, `RAID`, or `DRIVE:<model>`.
`component_type` ∈ `bios`, `bmc`, `cpld`, `psu`, `nic`, `storage_controller`, `drive`, `other`. Only
installed (active) firmware is sent, not `Previous-…` / staged images.

### Response

```json
{"batch_id": "6f1c…", "duplicate": false, "servers": 1, "readings": 52, "events": 2}
```

## `POST /ingest/v1/heartbeat`

```json
{
  "collector": "pnq1-col-a",
  "version": "1.0.0",
  "hostname": "collector-pnq1-a",
  "sent_at": "2026-10-22T10:00:30Z",
  "config_version": "9f2c1e0a",
  "stats": {
    "servers_assigned": 12,
    "servers_ok": 11,
    "polls_ok_1m": 22,
    "polls_failed_1m": 1,
    "cycles_skipped_1m": 0,
    "buffer_batches": 0,
    "buffer_bytes": 0,
    "last_batch_at": "2026-10-22T10:00:24Z",
    "errors_by_vendor": {"Dell": 0, "HPE": 1, "Lenovo": 0}
  }
}
```

Response: `{"ok": true, "config_version": "9f2c1e0a"}`. If it differs from the collector's, the collector
refreshes config immediately instead of waiting for the next refresh.

## Collector environment variables

| Variable | Default | Meaning |
|---|---|---|
| `GCC_INGEST_URL` | `http://localhost:8001` | Ingest API base URL |
| `GCC_COLLECTOR_NAME` | — (required) | Must match a `collectors.name` row |
| `GCC_INGEST_TOKEN` | — | Shared token (dev / `token` mode) |
| `GCC_CLIENT_CERT`, `GCC_CLIENT_KEY`, `GCC_CA_BUNDLE` | — | mTLS client certificate, key, and CA to verify the cloud (prod) |
| `GCC_CREDENTIALS_PROVIDER` | `env` | `env`, `file` or `vault` |
| `GCC_BMC_USERNAME`, `GCC_BMC_PASSWORD` | — | `env` provider: one read-only account for every BMC |
| `GCC_CREDENTIALS_FILE` | `/etc/gcc-collector/credentials.yaml` | `file` provider: `{default: {username, password}, refs: {<ref>: {…}}, hosts: {<bmc_host>: {…}}}` |
| `VAULT_ADDR`, `VAULT_TOKEN`, `GCC_VAULT_MOUNT`, `GCC_VAULT_PATH` | —, —, `secret`, `gcc/bmc` | `vault` provider: KV v2 secret `<mount>/data/<path>/<credential_ref>` with `username`, `password` |
| `GCC_BMC_VERIFY_TLS` | `true` | Verify BMC certificates (set `false` only in labs) |
| `GCC_BMC_CA_BUNDLE` | — | CA bundle for BMC certificates signed by the company CA |
| `GCC_BUFFER_DIR` | `/var/lib/gcc-collector/buffer` | Offline disk queue |
| `GCC_BUFFER_TTL_S` | `86400` | Drop buffered batches older than this |
| `GCC_LOG_LEVEL` | `INFO` | |
| `GCC_METRICS_PORT` | `9108` | Prometheus `/metrics` (0 disables) |

# App ↔ live updates (Redis)

The ingest API and the alert worker publish to one Redis pub/sub channel, `gcc:live` (constant
`LIVE_CHANNEL` in `backend/app/core/live.py`). The app API's WebSocket hub subscribes once and fans out to
browsers by server and site. Message shapes are the `LiveMessage` models in that module.
