# Jade GCC — Build Plan

Source of truth: [docs/DESIGN.md](docs/DESIGN.md) (transcribed from `docs/GCC-Data-Center-Design.pdf`).
Interpretations and gap-filling choices: [DECISIONS.md](DECISIONS.md).

## 1. Repository structure

```
/
├── compose.yaml                 # thin root file: `include: infra/docker-compose.yml` → `docker compose up` from repo root
├── .env.example                 # every variable, with dev-safe defaults documented
├── PLAN.md  DECISIONS.md  README.md
├── docs/
│   ├── DESIGN.md                # design doc (source of truth)
│   ├── GCC-Data-Center-Design.pdf
│   └── contracts/ingest-batch.example.json   # collector→ingest contract, validated by both test suites
├── collector/                   # on-prem collector (Python 3.12, asyncio, httpx, pydantic)
│   ├── pyproject.toml  Dockerfile
│   ├── src/gcc_collector/
│   │   ├── __main__.py  config.py  cloud.py  credentials.py  buffer.py  sender.py  scheduler.py  metrics.py  schema.py
│   │   ├── redfish/  client.py (sessions, X-Auth-Token, re-login on 401, timeouts, backoff, 1-in-flight lock)
│   │   │            discovery.py (walks @odata.id links, caches paths, $expand detection)
│   │   └── adapters/ base.py  dell.py  hpe.py  lenovo.py  generic.py  registry.py  (sensor-name mapping tables)
│   └── tests/                   # adapter tests replay mockups/ trees through an httpx transport
├── backend/                     # one codebase, four services (ingest API, app API, alert worker, scheduler)
│   ├── pyproject.toml  Dockerfile  alembic.ini
│   ├── alembic/versions/        # core schema, hypertable, caggs+policies, reference data, grants, reporting views
│   ├── app/
│   │   ├── core/                # settings, db, redis, security (OIDC/JWKS, RBAC, site scope), problems (RFC 9457), pagination, audit, rate limit
│   │   ├── models/              # SQLAlchemy 2 ORM
│   │   ├── schemas/             # Pydantic v2 DTOs
│   │   ├── services/            # inventory, readings, thresholds, alerts engine, notifier (email/Teams), firmware, superset, live pub/sub
│   │   ├── api/                 # app API (FastAPI) + routers + WebSocket /api/v1/live
│   │   ├── ingest/              # ingest API (FastAPI): config, batches (gzip, COPY), heartbeat; token (dev) / mTLS-header (prod) auth
│   │   ├── worker/              # Celery app; alert tasks (alert worker) and beat-scheduled jobs (scheduler)
│   │   └── seed.py              # dev seed: 2 sites, 4 rooms, 12 racks, collectors, onboarded servers, routes, baselines
│   ├── scripts/export_openapi.py
│   └── tests/
├── frontend/                    # React 18 + TS (strict), Vite, Router, TanStack Query, Tailwind, ECharts, Framer Motion
│   ├── src/theme/tokens.ts      # the one design-token file (colors, radii, blur, shadows, motion)
│   ├── src/components/          # GlassCard StatTile HealthBadge DataTable SensorChart RackView PageHeader (+ shell parts)
│   ├── src/pages/               # Login Overview Site Rack Server Alerts Inventory Firmware Analytics Admin Audit
│   ├── src/api/                 # typed client generated from the backend OpenAPI schema (openapi-typescript)
│   ├── tests/  e2e/             # Vitest + RTL; Playwright
│   └── Dockerfile  nginx.conf   # static build behind nginx, proxies /api and the WebSocket (same origin)
├── superset/
│   ├── Dockerfile  superset_config.py  init_superset.py
│   └── bundle/                  # spec → generated importable export (databases/datasets/charts/dashboards YAML)
├── mockups/
│   ├── generate_mockups.py      # writes the three vendor-style DMTF mockup trees
│   ├── dell-r750/  hpe-dl380-gen10/  lenovo-sr650/      # DMTF mockup format (index.json per resource)
│   └── simulator/               # dynamic multi-BMC Redfish simulator (drift, faults, sessions, $expand, 500 BMCs) + control API
├── infra/
│   ├── docker-compose.yml       # the full local stack
│   ├── timescale/init/          # roles, extra databases (superset metadata, keycloak)
│   ├── keycloak/gcc-realm.json  # realm, clients, role groups, site groups, demo users
│   ├── nginx/ingest-mtls.conf   # prod-style mTLS termination in front of the ingest API
│   ├── pki/                     # dev CA + per-collector client-cert generator
│   └── loadtest/                # 500-server load test (compose override + runner + report)
└── .github/workflows/ci.yml
```

## 2. Local stack (one command: `docker compose up`)

| Service | Image / build | Host port | Notes |
|---|---|---|---|
| timescaledb | timescale/timescaledb (pg16) | 5432 | app DB `gcc` + `superset_meta` + `keycloak` DBs; least-privilege roles |
| redis | redis:7 | — (internal) | Celery broker, live pub/sub, rate limits; Superset cache on other DB numbers |
| keycloak | quay.io/keycloak/keycloak | 8080 | realm `gcc` imported on start; demo users for every role |
| migrate | backend image | — | one-shot: `alembic upgrade head` + idempotent dev seed |
| ingest-api | backend image | 8001 | `/ingest/v1/*`, shared dev token; mTLS-header mode for prod |
| app-api | backend image | 8000 | `/api/v1/*`, `/api/v1/live` WS, OpenAPI at `/docs` |
| alert-worker | backend image | — | Celery worker: rule evaluation + notifications |
| scheduler | backend image | — | Celery beat + worker: missing data, compliance, escalation, cleanup, dev backfill |
| redfish-dell / -hpe / -lenovo | dmtf/redfish-mockup-server | — | static vendor mockups (reference BMCs) |
| bmc-simulator | mockups/simulator | 9100 (control) | N dynamic BMCs (36 in dev, 500 in load test), fault injection, Teams webhook sink |
| collector-pnq1-a / -b, collector-hyd1-a | collector image | — | two collectors at site 1 to demo HA failover |
| superset, superset-worker, superset-beat, superset-init | superset/ | 8090 | six dashboards imported on start; embedded via guest tokens |
| mailpit | axllent/mailpit | 8025 | captures alert email in dev |
| web | frontend/ (nginx) | 3000 | the React app |

## 3. Build order and verification

Every phase ends with: `ruff check` + `ruff format --check` + `mypy --strict` (Python) / `eslint` + `tsc --noEmit` (TS),
the phase's tests green, and a commit. Verification steps below are what "done" means for each phase.

### Phase 1 — Database
- Alembic (async env) migrations for every table in the design doc, plus the supporting tables the API needs
  (`alert_activity`, `alert_routes`, `bmc_thresholds`, `users`, `app_settings`) — see DECISIONS.md.
- `readings` hypertable exactly as in the doc (1-day chunks, `(server_id, metric_code, time DESC)` index),
  compression after 7 days (segment by server/metric), 30-day retention.
- Continuous aggregates `readings_5m` (avg/min/max, real-time) and hierarchical `readings_1h`, with refresh
  policies and 13-month / 3-year retention.
- Reference data in migrations: the metric definitions for all 20 parameters, default thresholds (inlet 27/35 …),
  default alert rules for every row of the parameter table.
- DB roles/grants (ingest writes readings only; app; Superset read-only on views) and the six reporting views.
- Seed CLI: 2 sites, 4 rooms, 12 racks (+ collectors, onboarded servers, routes, baselines).
- **Verify:** start timescaledb container; `alembic upgrade head` → `downgrade base` → `upgrade head` round-trip;
  pytest checks hypertable/caggs/policies exist (`timescaledb_information.*`), seed counts (2/4/12), and that
  the Superset role can read views but not base tables.

### Phase 2 — Collector
- Shared Redfish client: session login (`POST /SessionService/Sessions`), `X-Auth-Token`, transparent re-login
  on 401, Basic-auth fallback when sessions are unsupported, 20 s timeout, exponential backoff with jitter,
  `asyncio.Lock` per BMC (one request in flight), global semaphore (~50 BMCs in parallel), `$expand` when the
  service root advertises `ProtocolFeaturesSupported.ExpandQuery`.
- Discovery: walk from `/redfish/v1` via `@odata.id` (Systems, Chassis, Managers, Storage, LogServices,
  UpdateService/FirmwareInventory); never assume IDs; cache per BMC; rediscover on 404.
- Adapters (Dell / HPE / Lenovo / generic) with sensor-name → metric-code mapping tables; prefer
  ThermalSubsystem/PowerSubsystem/Sensors, fall back to Thermal/Power.
- All 20 parameters on 60 s / 5 min / daily schedules; a cycle is skipped (not queued) if the previous one for
  that BMC is still running.
- Sender: batches every 10–15 s, gzip; on failure → disk buffer (24 h TTL) and in-order replay. Heartbeat every 30 s.
  Config refresh every 60 s (picks up onboarding changes and HA failover reassignment).
- Credentials: env default / YAML file / HashiCorp Vault KV v2 providers — read locally, never sent to the cloud.
- **Verify:** unit tests for the client (401 → re-login, timeout/backoff, single-flight), discovery, buffer
  (ordering, TTL, replay), scheduler skip-cycle; adapter tests per vendor against the mockup trees asserting
  all 20 parameters map to the expected metric codes and component names, including the legacy-layout fallback.

### Phase 3 — Simulated hardware
- `mockups/generate_mockups.py` writes three vendor-style trees in DMTF mockup format (Dell iDRAC9 with the new
  ThermalSubsystem/PowerSubsystem/Sensors layout + `Oem.Dell`; HPE iLO 5 with only legacy Thermal/Power +
  `Oem.Hpe`; Lenovo XCC with both layouts + `Oem.Lenovo`), each with real-world sensor naming.
- Three DMTF Redfish Mockup Server containers serve them unchanged (reference BMCs).
- `bmc-simulator` loads the same trees as templates and serves N virtual BMCs (one port each), with unique
  serials/MACs, session auth, `$expand`, realistic drift (diurnal inlet, CPU load ↔ power ↔ temperatures ↔
  fan RPM), and random + on-demand faults: fan slows, PSU → Warning, inlet spike, drive wear, NIC down,
  critical SEL entry, BMC stops answering. Control API to list/trigger/clear faults; Teams webhook sink.
- **Verify:** simulator unit tests (bounds of drift, faults change the right resources, auth); collector
  integration test against the DMTF container; compose up → data from all three vendors lands in `readings`
  every minute (Gate 1 query).

### Phase 4 — Backend
- Ingest API: `GET /ingest/v1/config`, `POST /ingest/v1/batches` (gzip, validation, COPY into readings, upserts of
  latest_readings / health_status / events / inventory / firmware / BMC limits), `POST /ingest/v1/heartbeat`;
  auth = shared token in dev, client-cert identity from the TLS-terminating proxy in prod (nginx config provided).
  Publishes live updates to Redis and enqueues alert evaluation.
- App API: every endpoint in the design doc plus the ones the screens need (overview, sites/rooms/racks CRUD,
  search, components, CSV export, alert comments/resolve, routes, maintenance windows, collectors, baselines,
  users, metrics). Cursor pagination + server-side filtering on every list; RFC 9457 errors; OpenAPI.
- Security: OIDC JWT validation via JWKS; roles and site scopes from SSO groups; RBAC for the five roles;
  site checks on every endpoint; per-user rate limits; audit log for sign-ins, asset changes, threshold/rule
  changes and alert actions.
- WebSocket `/api/v1/live`: auth message, subscribe to servers/sites, fan-out from Redis pub/sub.
- Alert worker: threshold (with duration), state, missing data, event and compliance rules; one alert per
  server+metric+part (dedupe key); window-based flap protection (bad for the full duration to open, good for the
  full duration to resolve); maintenance-window muting; routing per site+severity; email (SMTP) and Teams
  (webhook) senders; 15-minute critical escalation.
- Scheduler: missing-data checks (30 s), collector heartbeat checks, daily firmware compliance, escalation,
  retention cleanup, weekly report email.
- Superset guest-token endpoint with RLS `site_id IN (...)` for site-limited users.
- **Verify:** pytest against a real TimescaleDB: ingest round-trip (gzip batch → rows), contract fixture,
  every endpoint's RBAC + site filtering, pagination, problem+json, alert-rule scenarios (fire after duration,
  no flap, resolve after duration, severity escalation, dedupe, maintenance mute, missing data, event,
  compliance, escalation), notifier payloads, guest token (mocked Superset), WebSocket subscribe/receive.

### Phase 5 — Superset
- Superset image with the Postgres driver + `superset_config.py` (embedding, guest token 5 min, Keycloak SSO for
  analysts, Redis cache/Celery, reports).
- Read-only DB user over the `reporting` views (v_readings_5m, v_readings_1h, v_server_health, v_alerts,
  v_inventory, v_firmware_compliance).
- Bundle generator → importable export (database, six datasets, charts, six dashboards with the doc's refresh
  intervals); `superset-init` imports it on every start, enables embedding, creates the guest role.
- **Verify:** after compose up, Superset API lists six dashboards each with an embedded UUID; every chart's data
  query returns 200; a guest token with RLS returns only the permitted site's rows.

### Phase 6 — Frontend
- Design tokens (one file) → Tailwind theme + CSS variables; dark default, light toggle; reduced
  transparency/motion fallbacks; Inter + JetBrains Mono.
- Component set: GlassCard, StatTile, HealthBadge, DataTable, SensorChart, RackView, PageHeader (+ shell:
  collapsible glass sidebar, top bar with global search, site filter, alerts bell, theme toggle, user menu).
- Screens: Login, Global overview (+ wall/full-screen mode), Site, Rack (SVG elevation), Server detail (live
  sensors with cross-fade, health per part, inventory, firmware, events, 24 h charts), Alerts (filters, ack,
  comments), Inventory (servers + parts, CSV export), Firmware compliance, Analytics (embedded Superset), Admin,
  Audit log. Role-aware navigation and actions. Every number shows unit and age.
- **Verify:** `tsc --noEmit`, ESLint, Vitest; manual run of every screen against the live stack, in both themes.

### Phase 7 — Quality
- pytest suites (collector adapters vs mockups, API, alert rules) — extended where Phase 2–4 left gaps.
- Vitest + RTL for HealthBadge, StatTile, DataTable, RackView, SensorChart wrapper, alerts ack flow.
- Playwright E2E: log in through Keycloak → open a server → acknowledge an alert.
- Load test: compose override with 500 simulated BMCs and two collectors; runner reports readings/s, ingest lag,
  live freshness and 30-day rollup query times against the design targets (pass/fail).
- GitHub Actions: lint, type checks, unit + adapter tests (with Timescale/Redis/DMTF mockup service containers),
  frontend build/tests, image builds, Trivy image scan, pip-audit / npm audit.
- **Verify:** everything above green locally; `docker compose config` valid; CI workflow lint-checked.

## 4. Definition of done (whole project)
- `docker compose up` from a clean clone brings up the full stack with data flowing and dashboards loaded.
- README covers architecture, one-command start, demo logins per role, onboarding a real BMC, tests, load test.
- No secrets in code; `.env.example` lists every variable; BMC credentials only ever read by the collector.
- Final summary lists what works, how to run it, what is stubbed, and what is left.
