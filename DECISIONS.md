# Decisions

Choices made where the design doc ([docs/DESIGN.md](docs/DESIGN.md)) is silent, ambiguous, or where the build
brief overrides it. Each entry: the decision, and why. Newest entries are appended per phase.

## Project setup

**D1. `docs/DESIGN.md` is a transcription of the PDF.** The brief names `docs/DESIGN.md` as the source of truth,
but only `GCC Data Center .pdf` existed. It was moved to `docs/GCC-Data-Center-Design.pdf` and transcribed
verbatim to Markdown so it can be grepped and diffed. The "[embed: node/…]" Gantt chart on the delivery-plan page
was an image placeholder in the PDF and carries no extra information.

**D2. `docker compose up` from the repo root.** The brief puts compose in `infra/` but wants a one-command start.
A root `compose.yaml` uses Compose `include:` to pull in `infra/docker-compose.yml`, so both work.

**D3. Dev defaults instead of a required `.env`.** Compose files reference every secret as `${VAR:-dev-value}`
so a clean clone starts without copying `.env.example`. Dev values are obviously fake and only valid for the local
containers. The backend refuses to start with `APP_ENV=prod` if any known dev value is still in use.

**D4. Host ports avoid ones in use on the build machine.** Superset on 8090 (8088 was taken), simulator control
API on 9100 (9000 was taken), Redis not published (6379 was taken). All host ports are overridable in `.env`.

**D5. Python 3.12 is provided by `uv`.** Each Python package has its own `pyproject.toml` and lock; containers use
`python:3.12-slim`.

## Architecture

**D6. No read replica in dev.** The doc has Superset read from a read replica. Locally Superset connects to the
primary through the read-only `gcc_superset_ro` user; its URI is a single setting (`SUPERSET_ANALYTICS_DB_URI`)
that points at the replica in staging/prod.

**D7. Collector ↔ ingest contract is duplicated, then pinned by a shared fixture.** Collector (on-prem) and
backend (cloud) deploy separately, so each owns its Pydantic models. `docs/contracts/ingest-batch.example.json` is
produced by the collector's test suite and validated by the backend's, so drift fails CI.

**D8. Ingest auth: shared token in dev, client-certificate identity in prod.** Uvicorn cannot expose the peer
certificate to the app, so in prod mTLS is terminated by nginx/ingress (`infra/nginx/ingest-mtls.conf`), which
forwards the verified certificate's fingerprint and subject. The ingest API trusts these headers only from
configured proxy addresses and matches the fingerprint against `collectors.cert_fingerprint`. Dev uses
`INGEST_AUTH_MODE=token` with a shared token plus the collector's name.

**D9. Collector HA by cloud-side assignment.** `servers.collector_id` is the preferred collector. `GET
/ingest/v1/config` returns a collector's own servers plus an even share of servers whose preferred collector has
missed heartbeats for 90 s (deterministic split by server id across the site's live collectors). Collectors
refresh config every 60 s, so failover takes ≤ 2.5 minutes and reverses automatically.

## Data model

**D10. Supporting tables beyond the doc's list.** `alert_activity` (every state change, comment and notification —
"every change is logged with who and when"), `alert_routes` (per-site, per-severity routing), `bmc_thresholds`
(limits reported by each BMC per sensor), `users` (who has signed in, with roles/sites from the token; managed in
the IdP), `app_settings` (small key/value flags). Servers also carry `site_id` (kept equal to the rack's site) so
site scoping and RLS are a single indexed column.

**D11. Metric codes.** Some of the 20 parameters need more than one series. `metric_definitions` has a
`parameter_no` (1–20) and one row per code: e.g. parameter 5 → `fan_rpm` and `fan_pct`; 6 → `fan_health`,
`fan_redundancy`; 7 → `power_w`, `power_capacity_w`, `power_limit_w`; 15 → `drive_health`, `drive_life_pct`;
16 → `storage_health`, `volume_health`; 18 → `bmc_health`, `bmc_reachable`. State readings are stored in
`readings` too (value 0 = OK, 1 = Warning, 2 = Critical; links 1 = Up / 0 = Down; power 1 = On / 0 = Off) with the
raw state in `status`, so Superset can chart state history.

**D12. Threshold precedence: server > site > model > global > BMC.** Admin overrides always win; the doc's explicit
defaults (inlet 27/35, power 90 % of capacity, PSU voltage 10 % from nominal, drive life < 10 %) are seeded as
global rows; metrics whose default is "BMC's own thresholds" have no global row, so the BMC-reported limits in
`bmc_thresholds` apply.

**D13. Component naming.** Server-level single sensors (inlet, power draw, power state, system health, BMC) use
component `''` as in the doc's DDL; per-part metrics use the adapter's normalized name ("CPU1", "Fan 3",
"PSU 1", "DIMM A1", "Disk 0"). Names are stable per server across polls, which is what history and alert dedupe
need; they are not forced to be identical across vendors.

## Alerting

**D14. Window-based evaluation instead of in-memory timers.** For a rule with duration *d*, the worker reads the
server's samples for that metric/part over the last *d*: it opens (or escalates) when every sample in the window
is bad at that severity, and resolves when every sample is good. Mixed windows keep the current state. This is
stateless across worker restarts, needs no extra state table, and is exactly the doc's anti-flap rule. Windows
must contain ≥ 2 samples spanning ≥ 80 % of *d* to count.

**D15. Dedupe key.** One non-resolved alert per `(server, metric, component)` (collector alerts: per collector),
enforced by a partial unique index on `alerts.dedupe_key WHERE state <> 'resolved'`. A recurrence after
resolution opens a new alert.

**D16. Maintenance windows mute, they don't hide.** Alerts for covered servers/racks/sites are still recorded
but flagged `muted` and never notified or escalated; the "power off" rule does not fire at all inside a window
(the doc says "Off outside a maintenance window").

**D17. Event and compliance alerts.** Event alerts (critical SEL entries) dedupe per server + message ID and
auto-resolve 24 h after the last occurrence, or when resolved by an operator. Compliance alerts resolve when the
daily check finds the firmware back on baseline.

**D18. Routing model.** `alert_rules.route` is a team key (`hardware`, `facilities`, `platform`). `alert_routes`
map (route key, site or all sites, minimum severity, escalation level) → channel (email list or Teams webhook).
Teams webhook URLs are encrypted at rest (Fernet, key from env). Escalation: a Critical alert not acknowledged
in 15 minutes is sent to level-1 routes.

**D19. NIC "expected link".** A NIC port is expected to be up if it was up when first inventoried; that flag is
stored on the component (admins can change it). Only expected links raise "link down" alerts.

## Security / auth

**D20. Keycloak in dev, any OIDC IdP in prod.** Roles come from groups `gcc-viewer`, `gcc-noc-operator`,
`gcc-dc-engineer`, `gcc-platform-admin`, `gcc-analyst` (mapping configurable). Site limits come from groups
`gcc-site-<CODE>`; users with no site group see all sites. The API validates the access token's signature (JWKS),
issuer, audience and expiry on every request.

**D21. Analyst permissions.** Analysts get Viewer access in the app (they are main users of Inventory) plus
editing rights in Superset (Alpha role via SSO). Only Platform admins see Audit log and admin-only settings.

**D22. User management is read-only in the app.** The doc says roles come from SSO groups "so access is managed in
one place". Admin → Users lists who has signed in with their roles and sites; assignments change in the IdP.

**D23. WebSocket auth by first message.** Browsers cannot set headers on WebSockets; putting tokens in the URL leaks
them to logs. The client sends `{"type":"auth","token":…}` as its first message (5 s deadline).

## Frontend

**D24. Custom Tailwind component set instead of MUI/Ant Design.** The doc leaves the library to the team; the brief
specifies a glassmorphism design system with Tailwind and a named component set, which a heavy component library
would fight. ECharts (doc lists ECharts or Recharts) for charts; `oidc-client-ts` for sign-in.

**D25. Placeholder logo.** No logo file was provided; `frontend/src/assets/logo.svg` is a simple mark in the brand
colours. Replace it with the official asset.

## Simulated hardware

**D26. Vendor-style mockups are authored, not copied.** Captured vendor mockups are not reliably available or
licensed for redistribution. `gcc-generate-mockups` (`mockups/src/gcc_redfish_sim/generate.py`) writes DMTF-format
trees that follow each vendor's documented conventions (resource IDs, sensor names, Oem sections, which layout each
firmware generation uses). The DMTF Redfish Mockup Server serves them unchanged; the dynamic simulator uses them as
templates. Layout split differs from the plan to match real firmware: Dell iDRAC9 serves both the newer
ThermalSubsystem/PowerSubsystem/Sensors layout and legacy Thermal/Power, HPE iLO 5 legacy only, Lenovo XCC2 newer
only. The adapter tests still cover legacy-only, newer-only and both.

**D27. One simulator process, one port per virtual BMC.** Redfish links are absolute paths, so BMCs cannot share a
port behind a path prefix. The simulator listens on `base_port + i` for each BMC; in dev `bmc_host` values look
like `bmc-simulator:20001`, and the scheme defaults to HTTPS unless the host is given as `http://…`.
