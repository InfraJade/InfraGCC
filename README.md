# Jade GCC — Data Center Monitoring Platform

> Draft (infra). The lead finalizes this file.

Monitors Dell, HPE and Lenovo servers in the GCC data centers over Redfish: live sensor readings, health per
part, inventory and firmware compliance, alerting (email and Teams), and Superset dashboards embedded in a
React app. Design: [docs/DESIGN.md](docs/DESIGN.md). Build plan: [PLAN.md](PLAN.md). Decisions:
[DECISIONS.md](DECISIONS.md). Collector ↔ ingest contract: [docs/contracts/README.md](docs/contracts/README.md).

## Architecture

```
 Data center (on-prem)                         │  Cloud (Kubernetes in prod, Docker Compose in dev)
                                               │
  BMCs (iDRAC / iLO / XCC) ◄─Redfish─ collector│x2 per site ──HTTPS 443, mTLS──► ingest API ──► TimescaleDB
   read-only account          (vault creds,    │  outbound only, gzip batches,      │  COPY       (readings
                               disk buffer 24h)│  heartbeat 30 s                    │             hypertable,
                                               │                                    ▼             5m/1h rollups,
                                               │                    Redis (pub/sub, Celery)       reporting views)
                                               │                      │         │                 ▲      ▲
                                               │            alert worker   scheduler              │      │
                                               │            (rules, email,  (missing data,        │      │
                                               │             Teams)          compliance, ...)     │      │
                                               │                      │                           │      │
   Browser ◄── web (nginx + React) ◄── app API (REST /api/v1, WebSocket /api/v1/live) ─────────────┘      │
      │              │  embedded dashboards (guest tokens, RLS by site)                                   │
      └──OIDC──► Keycloak (dev) / company IdP           Superset ── read-only user, views only ─────────────┘
```

A reading's path: collector polls a BMC → vendor adapter maps it to a metric code → batch to the ingest API →
`readings` (plus latest values, health, events, inventory) → alert worker evaluates rules → app API pushes the
value to open browsers → Superset sees it in the next 5-minute rollup.

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2.24+) with **at least 8 GB RAM** and ~10 GB disk for images.
- Free host ports 3000, 8000, 8001, 8025, 8080, 8090, 9100, 5433 (all overridable, see `.env.example`).
- For development outside containers: [uv](https://docs.astral.sh/uv/) (provides Python 3.12) and Node 20+.

## Start

```sh
docker compose up -d --build      # from the repo root; no .env needed (dev defaults, DECISIONS.md D3)
docker compose ps                 # wait until everything is healthy (first start: 3–5 minutes)
```

`compose.yaml` includes `infra/docker-compose.yml`. Startup order is enforced with healthchecks: database,
Redis, mockups/simulator → Keycloak and `migrate` (schema + dev seed, one-shot) → APIs and workers →
`superset-init` (imports dashboards, one-shot) → collectors, Superset, web.

To change a port or a secret: `cp .env.example .env` and edit. Stop with `docker compose down`; reset all data
with `docker compose down -v`.

## URLs and demo logins

| What | URL | Login |
|---|---|---|
| Web app | http://localhost:3000 | demo users below |
| App API docs (OpenAPI) | http://localhost:8000/docs | bearer token |
| Ingest API | http://localhost:8001 | collector token (`dev-ingest-token`) |
| Keycloak admin console | http://localhost:8080/admin | `admin` / `dev-keycloak-admin` |
| Superset | http://localhost:8090 | `admin` / `dev-superset-admin`, or SSO as `analyst` / `admin` |
| Mailpit (alert email) | http://localhost:8025 | — |
| BMC simulator control API | http://localhost:9100 | — |
| TimescaleDB | `localhost:5433`, database `gcc` | `gcc_owner` / `dev-owner-pw` |

Demo users (realm `gcc`, password **`demo1234`** for all):

| User | Role | Sites | Can |
|---|---|---|---|
| `viewer` | Viewer | all | see dashboards, servers, alerts |
| `noc` | NOC operator | all | + acknowledge and comment on alerts |
| `engineer` | DC engineer | all | + onboard servers, racks, maintenance windows |
| `admin` | Platform admin | all | + thresholds, rules, routes, users, audit log |
| `analyst` | Analyst | all | Viewer in the app, editor in Superset |
| `noc-pune` | NOC operator | PNQ1 only | as `noc`, limited to Pune DC1 |
| `engineer-hyd` | DC engineer | HYD1 only | as `engineer`, limited to Hyderabad DC2 |

Roles and site limits come from Keycloak groups (`gcc-<role>`, `gcc-site-<CODE>`), DECISIONS.md D20.

## Services

| Service | What it does |
|---|---|
| `timescaledb` | PostgreSQL 16 + TimescaleDB: app database `gcc` (hypertable, rollups, reporting views), plus `superset_meta` and `keycloak` databases. Least-privilege roles created by `infra/timescale/init`. |
| `redis` | Live pub/sub (`gcc:live`), rate limits, backend Celery broker; Superset cache and Celery on DBs 2–4. Not published to the host. |
| `keycloak` | OIDC provider; imports `infra/keycloak/gcc-realm.json` on first start. |
| `migrate` | One-shot: `alembic upgrade head` and the idempotent dev seed (2 sites, 4 rooms, 12 racks, 3 collectors, 36 simulated + 3 reference servers, alert routes, baselines). |
| `ingest-api` | Collector API: `/ingest/v1/config`, `/batches`, `/heartbeat`. Token auth in dev, client-certificate identity in prod. |
| `app-api` | REST API for the web app, WebSocket live updates, Superset guest tokens. |
| `alert-worker` | Celery: rule evaluation, email and Teams notifications. |
| `scheduler` | Celery beat + worker: missing data, collector heartbeats, firmware compliance, escalation, cleanup, dev backfill. |
| `redfish-dell`, `redfish-hpe`, `redfish-lenovo` | DMTF Redfish Mockup Server serving the vendor-style trees in `mockups/trees/` (reference BMCs). |
| `bmc-simulator` | 36 dynamic virtual BMCs (drift, faults, sessions), control API on 9100, Teams webhook sink. |
| `collector-pnq1-a`, `collector-pnq1-b`, `collector-hyd1-a` | The on-prem collector; two at PNQ1 to demo HA failover. Disk buffer on a named volume each. |
| `superset-init`, `superset`, `superset-worker`, `superset-beat` | Superset with the six dashboards imported on every start; embedded in the app. |
| `mailpit` | Catches alert email. |
| `web` | nginx serving the React build; proxies `/api` and the WebSocket to the app API. |

Fault injection: use the simulator control API on http://localhost:9100 (see `mockups/`) and watch the alert
appear in the app, in Mailpit and at the Teams sink.

## Onboarding a real BMC

1. **On the BMC**: create a dedicated read-only Redfish account (e.g. `gcc-monitor`, role ReadOnly). Replace the
   self-signed certificate with a company-CA certificate, or plan to pin it.
2. **Collector configuration** (on the collector VM, environment variables; full list in
   [docs/contracts/README.md](docs/contracts/README.md#collector-environment-variables)):
   - `GCC_INGEST_URL=https://ingest.<company>/`, `GCC_COLLECTOR_NAME=<name>` (must exist in Admin → Collectors)
   - Prod: `GCC_CLIENT_CERT`, `GCC_CLIENT_KEY`, `GCC_CA_BUNDLE` (mTLS; see [infra/pki/README.md](infra/pki/README.md));
     dev: `GCC_INGEST_TOKEN`.
   - `GCC_BMC_VERIFY_TLS=true` and `GCC_BMC_CA_BUNDLE=/etc/ssl/company-ca.pem`.
3. **Credentials** never leave the data center. Pick a provider with `GCC_CREDENTIALS_PROVIDER`:
   - `env`: one account for every BMC (`GCC_BMC_USERNAME`, `GCC_BMC_PASSWORD`).
   - `file`: `GCC_CREDENTIALS_FILE` YAML with `default`, per-`refs` and per-`hosts` entries
     (`collector/credentials.example.yaml`).
   - `vault`: HashiCorp Vault KV v2 (`VAULT_ADDR`, `VAULT_TOKEN`, `GCC_VAULT_MOUNT`, `GCC_VAULT_PATH`); secret
     `<mount>/data/<path>/<credential_ref>` with `username` and `password`.
4. **In the app** (DC engineer or admin): Admin → Servers → Add server: BMC address (`bmc01.dc.example` or
   `https://10.20.1.11`), rack and U position, preferred collector, optional credential ref. The collector picks
   it up within 60 s, discovers vendor/model/serial and parts itself, and data appears on the server page.

## Tests

| Package | Command (from the package directory) |
|---|---|
| backend | `uv run pytest` (DB tests need TimescaleDB; set `TEST_DATABASE_URL`), `uv run ruff check`, `uv run ruff format --check`, `uv run mypy` |
| collector | `uv run pytest`, `uv run ruff check`, `uv run mypy` (adapter tests replay `mockups/trees/`) |
| mockups (simulator) | `uv run pytest`, `uv run ruff check`, `uv run mypy` |
| superset | bundle generator tests (see `superset/`) |
| frontend | `npm ci`, `npm run lint`, `npx tsc --noEmit`, `npm test`; E2E: `npx playwright test` against the running stack |
| infra | `docker compose config -q` |

E2E and load tests sign in without a browser through the dev-only Keycloak client `gcc-e2e`
(secret `dev-e2e-secret`, password grant). It must never exist outside dev.

## Load test

`infra/loadtest/` (500 simulated BMCs, two collectors): runner reports readings/s, ingest lag, live
freshness and 30-day rollup query times against the design targets. See `infra/loadtest/`.

## Prod-style mTLS locally

```sh
sh infra/pki/make-ca.sh
for c in pnq1-col-a pnq1-col-b hyd1-col-a; do sh infra/pki/make-collector-cert.sh $c; done
docker compose -f compose.yaml -f infra/compose.mtls.yaml up -d
```

Adds nginx on `https://localhost:8443` (`infra/nginx/ingest-mtls.conf`), which verifies the client certificate
and forwards its SHA-256 fingerprint; the ingest API runs with `INGEST_AUTH_MODE=mtls`.

## Troubleshooting

- **Port already in use**: set the matching `*_PORT` in `.env` (e.g. `WEB_PORT=3001`). If you move Keycloak,
  also set `KEYCLOAK_PUBLIC_URL` and `OIDC_ISSUER` to the new port; if you move the web app, add the new origin
  to the `gcc-web` client's redirect URIs.
- **Keycloak is slow the first time**: the first start creates its schema and imports the realm (60–120 s on a
  laptop). Services that need it wait for its healthcheck.
- **Realm changes not applied**: the realm is imported only if it does not exist. Run `docker compose down -v`
  (resets all data) or delete realm `gcc` in the admin console and restart `keycloak`.
- **Changed a database password and services can't log in**: passwords are set when the `timescaledb-data`
  volume is created; reset with `docker compose down -v`.
- **`migrate` failed**: `docker compose logs migrate`; fix, then `docker compose up -d` re-runs it (the seed
  is idempotent).
- **Out of memory / containers restarting**: give Docker Desktop at least 8 GB; lower `SIM_COUNT`, or stop
  Superset (`docker compose stop superset superset-worker superset-beat`).
- **Reset everything**: `docker compose down -v --remove-orphans` removes containers, the database, collector
  buffers and Superset home.
