# GCC Data Center Monitoring Platform — Project Design

> Markdown transcription of `docs/GCC-Data-Center-Design.pdf` (24 pages). This file is the
> source of truth for scope, architecture, data model, API, metrics, alerting and security.
> Where the build had to interpret something, the choice is recorded in `/DECISIONS.md`.

## Overview

We are building one web application for the GCC that holds every data center, rack and server
we run, and watches 20 hardware health readings on each server through the Redfish API.

Without it, hardware data stays split across separate vendor consoles (Dell iDRAC, HPE iLO,
Lenovo XClarity), one server at a time. The platform brings it into one inventory, one set of
live readings, one alert stream and one set of dashboards.

### Goals

- Keep one inventory of sites, rooms, racks and servers, filled and kept current from the hardware itself.
- Monitor 15 to 20 hardware parameters (fan speed, temperatures, power and so on) on 100 to 500 servers, refreshed every minute.
- Alert the right team when a reading crosses a threshold or a part fails.
- Give teams trend, capacity and health analysis in Apache Superset.

### Proposed success measures

| Measure | Target |
|---|---|
| Servers reporting | At least 99% of onboarded servers report every 5 minutes |
| Data freshness | Live readings are under 2 minutes old |
| Alert delay | Alert raised within 2 minutes of a reading crossing its threshold |
| Dashboard speed | 30-day views load in under 3 seconds |
| Vendor coverage | Dell, HPE and Lenovo all supported at launch |

### Technology stack

| Layer | Choice |
|---|---|
| Hardware interface | DMTF Redfish (REST + JSON over HTTPS) |
| Collectors | Python, running on-prem |
| Backend | Python, FastAPI |
| Frontend | React |
| Database | PostgreSQL |
| Monitoring dashboards | Apache Superset |

## Scope and assumptions

Version 1 is read-only: it inventories and monitors 100 to 500 Dell, HPE and Lenovo servers,
with collectors on-prem and the application in the cloud.

### Decided

| Topic | Decision |
|---|---|
| Scale at launch | 100 to 500 servers |
| Server vendors | Dell (iDRAC), HPE (iLO), Lenovo (XClarity Controller) |
| Hosting | Hybrid: collectors on-prem in each data center, application in the cloud |
| Stack | FastAPI, React, PostgreSQL, Apache Superset |

### In scope for version 1

- Inventory of sites, rooms, racks, servers and their parts (CPUs, memory, drives, power supplies, fans, NICs, firmware).
- Collecting the 20 parameters in the next section from every server.
- Live views, history, alerts and notifications.
- Superset dashboards embedded in the app.
- Sign-in with company SSO and role-based access.
- Managing collectors and onboarding servers from the app.

### Out of scope for version 1

- Changing hardware: power actions, BIOS settings, firmware updates. These can come later behind approvals.
- Network switches, storage arrays, PDUs and cooling systems.
- Operating system and application monitoring.
- Automatic ticket creation in ITSM tools (planned for a later phase).

### Assumptions to confirm

| Assumption | Why it matters |
|---|---|
| Collectors can reach every BMC on port 443 | Without it, servers can't be polled |
| A read-only Redfish account can be created on every BMC | Keeps monitoring safe and separate from admin access |
| BMCs are iDRAC9, iLO 5 or later, and XCC | Older BMCs (iDRAC8, iLO 4) have partial Redfish support |
| Sensors are polled every 60 seconds | Sets data volume and BMC load |
| Raw readings kept 30 days, 5-minute rollups 13 months, hourly rollups 3 years | Sets storage size and cost |
| Notifications go to email and Microsoft Teams | Sets the first alert integrations |
| The cloud provider is AWS or Azure (to be chosen) | Affects database hosting and SSO setup |

## Users and roles

Five roles cover everyone; each comes from a company SSO group, so access is managed in one place.

| Role | Who | Can do |
|---|---|---|
| Viewer | GCC leadership, stakeholders | See dashboards, inventory and health |
| NOC operator | 24x7 monitoring team | Everything a Viewer can, plus acknowledge and comment on alerts |
| DC engineer | Data center and hardware teams | Everything an Operator can, plus onboard servers, edit racks and positions, set maintenance windows |
| Platform admin | Platform team | Everything, plus users and roles, collectors, thresholds, alert routing, integrations |
| Analyst | Reporting and capacity planners | Build and edit Superset charts and dashboards |

Access can also be limited by site, so a team in one data center sees only its own servers. The
same site limit applies inside embedded Superset dashboards.

## Monitored hardware parameters

We collect 20 parameters per server: sensor readings every 60 seconds, health states every 5
minutes, firmware once a day.

Redfish has two layouts for sensors. Newer firmware uses `ThermalSubsystem`, `PowerSubsystem`
and `Sensors`; older firmware uses the `Thermal` and `Power` resources. The collector tries the
newer layout first and falls back to the older one. Paths below are relative to `/redfish/v1`.

| # | Parameter | Redfish source | Unit | Interval | Default alert |
|---|---|---|---|---|---|
| 1 | Inlet (ambient) temperature | Chassis `ThermalSubsystem/ThermalMetrics` or `Thermal.Temperatures` | °C | 60 s | Warning above 27, critical above 35 |
| 2 | Exhaust temperature | Same as above | °C | 60 s | BMC's own thresholds |
| 3 | CPU temperature, per CPU | Same as above (CPU context) | °C | 60 s | BMC's own thresholds |
| 4 | Memory (DIMM) temperature | Same as above (memory context) | °C | 60 s | BMC's own thresholds |
| 5 | Fan speed, per fan | Chassis `ThermalSubsystem/Fans` or `Thermal.Fans` | RPM or % | 60 s | Below BMC lower threshold |
| 6 | Fan health and redundancy | Fan `Status`, `Thermal.Redundancy` | State | 5 min | Not OK, or redundancy lost |
| 7 | Power draw | Chassis `PowerSubsystem` / `EnvironmentMetrics` or `Power.PowerControl` | W | 60 s | Above 90% of capacity or power cap |
| 8 | Power supply health | Chassis `PowerSubsystem/PowerSupplies` Status | State | 5 min | Not OK |
| 9 | Power supply input voltage | Power supply metrics or `LineInputVoltage` | V | 60 s | More than 10% from nominal |
| 10 | Power supply redundancy | `Power.Redundancy` or power subsystem | State | 5 min | Redundancy lost |
| 11 | Power state | Systems `PowerState` | On / Off | 60 s | Off outside a maintenance window |
| 12 | Overall system health | Systems `Status.HealthRollup` | State | 60 s | Warning or Critical |
| 13 | CPU health | Systems `Processors` Status | State | 5 min | Not OK |
| 14 | Memory health, per DIMM | Systems `Memory` Status | State | 5 min | Not OK |
| 15 | Drive health and wear | `Storage/.../Drives` Status, `PredictedMediaLifeLeftPercent` | State, % | 5 min | Not OK, or life left under 10% |
| 16 | RAID controller and volume health | `Storage` Status, `Volumes` | State | 5 min | Degraded |
| 17 | NIC link status | `EthernetInterfaces` `LinkStatus` | Up / Down | 5 min | Expected link is down |
| 18 | BMC reachable and healthy | Managers `Status` plus poll success | State | 60 s | 3 failed polls in a row |
| 19 | New system event log entries | `LogServices/.../Entries` | Events | 5 min | Any Critical entry |
| 20 | Firmware versions (BIOS, BMC, drives) | `UpdateService/FirmwareInventory` | Version | Daily | Differs from the approved baseline |

Thresholds default to the BMC's own limits (`UpperThresholdCritical` and similar) where it
reports them. Admins can override them per server model or per site. The inlet limits follow
the ASHRAE recommended range (up to 27 °C) and the common allowable limit (35 °C); facilities
should confirm them.

## Architecture

Collectors in each data center poll the servers and push data out to the cloud application; the
cloud never opens a connection into the data center.

Collectors send batches out over HTTPS port 443 with mutual TLS. BMC passwords stay in the
on-prem vault.

### A reading's path, end to end

1. The collector asks a server's BMC for its fan speeds over Redfish.
2. The vendor adapter turns the answer into rows like `fan_rpm, Fan 3, 2100`.
3. The collector sends a batch to the ingest API, which writes it to PostgreSQL.
4. The alert worker checks the new values against the rules and raises an alert if needed.
5. The app API pushes the value to any open browser page; Superset picks it up in the next 5-minute rollup.

## Data collection with Redfish

A small Python collector runs in each data center, polls the BMCs over Redfish, turns
vendor-specific answers into one common format, and pushes batches to the cloud.

### How the collector works

1. On start, it fetches its server list and settings from the cloud (`GET /ingest/v1/config`). The cloud never connects into the data center.
2. For each BMC it opens one Redfish session (`POST /redfish/v1/SessionService/Sessions`), keeps the `X-Auth-Token`, and logs in again on a 401.
3. On first contact it walks the tree from the service root and caches the paths it needs, following `@odata.id` links instead of hardcoding them.
4. It polls on three schedules: sensors every 60 seconds, health every 5 minutes, inventory and firmware once a day.
5. A vendor adapter maps each answer to our metric codes (for example `fan_rpm`, `inlet_temp_c`) and component names.
6. Every 10 to 15 seconds it sends a compressed batch to the ingest API. If the cloud is unreachable, batches wait in a local disk queue for up to 24 hours and are replayed in order.
7. It sends a heartbeat every 30 seconds, so the cloud knows it is alive.

### Rules that protect the BMCs

- At most one request in flight per BMC; BMCs are small computers and slow down or hang under load.
- Around 50 BMCs polled in parallel per collector, with a 20-second timeout and backoff on errors.
- Use `$expand` to fetch collections in one call where the BMC supports it (the service root's `ProtocolFeaturesSupported` says so).
- Skip a cycle rather than queue a backlog when a BMC is slow.

### High availability

Each site runs two collectors. Servers are split between them; if one stops sending
heartbeats, the other takes over its share.

### Vendor differences

The collector has one shared Redfish client and one thin adapter per vendor. Adding Supermicro
or another vendor later means writing one new adapter.

| Vendor | BMC | Usual system ID | Notes |
|---|---|---|---|
| Dell | iDRAC9 (iDRAC8 partial) | `System.Embedded.1` | Extra data under `Oem.Dell`; streaming telemetry needs a higher iDRAC license |
| HPE | iLO 5, iLO 6 (iLO 4 partial) | `1` | Extra data under `Oem.Hpe`; some features need an iLO Advanced license |
| Lenovo | XClarity Controller (XCC, XCC2) | `1` | Extra data under `Oem.Lenovo`; some features need a higher XCC license |

IDs are discovered from the `Systems` and `Chassis` collections, never assumed. Sensor names
also differ by vendor ("System Board Inlet Temp", "01-Inlet Ambient", "Ambient Temp"), so each
adapter has a mapping table from vendor names to our metric codes.

### Testing without real hardware

The DMTF Redfish Mockup Server can replay saved responses from real Dell, HPE and Lenovo
servers. We run it in CI and in dev, so every adapter is tested on every commit.

## Data model

PostgreSQL holds everything; the high-volume readings go in a TimescaleDB hypertable (a
PostgreSQL extension), and everything else in normal tables.

### Tables

| Table | Holds | Key columns |
|---|---|---|
| `sites` | Data centers | name, city, country, timezone |
| `rooms` | Halls or rooms in a site | site_id, name |
| `racks` | Racks | room_id, name, row, height_u |
| `servers` | One row per server | rack_id, position_u, vendor, model, serial, bmc_host, collector_id, status |
| `components` | CPUs, DIMMs, drives, PSUs, fans, NICs | server_id, type, name, model, serial, capacity |
| `collectors` | On-prem collectors | site_id, name, version, last_heartbeat |
| `metric_definitions` | The 20 parameters | code, name, unit, interval, type |
| `thresholds` | Alert limits | metric_code, scope (global, model, site, server), warning, critical |
| `readings` | Every sensor reading (hypertable) | time, server_id, metric_code, component, value, status |
| `latest_readings` | Last value per sensor, for fast live views | server_id, metric_code, component, value, time |
| `health_status` | Current health per server and part | server_id, component, health, since |
| `events` | System event log entries | server_id, time, severity, message, message_id |
| `alert_rules` | What raises an alert | metric_code, condition, duration, severity, route |
| `alerts` | Raised alerts and their history | rule_id, server_id, state, severity, opened_at, acked_by, resolved_at |
| `maintenance_windows` | Planned work that mutes alerts | scope, starts_at, ends_at, reason |
| `firmware_inventory` | Installed firmware | server_id, component, version, collected_at |
| `firmware_baselines` | Approved versions per model | vendor, model, component, version |
| `audit_log` | Who changed what | user, action, object, before, after, time |

BMC passwords are never stored here. The `servers` table only says which collector polls the server.

### The readings table

```sql
CREATE TABLE readings (
  time        timestamptz      NOT NULL,
  server_id   integer          NOT NULL REFERENCES servers(id),
  metric_code smallint         NOT NULL REFERENCES metric_definitions(id),
  component   text             NOT NULL DEFAULT '',   -- e.g. 'Fan 3', 'CPU1'
  value       double precision,
  status      text                                    -- OK, Warning, Critical
);
SELECT create_hypertable('readings', 'time', chunk_time_interval => interval '1 day');
CREATE INDEX ON readings (server_id, metric_code, time DESC);
```

### Rollups and retention

| Data | Built by | Kept for |
|---|---|---|
| Raw readings | Collector | 30 days, compressed after 7 days |
| 5-minute average, min, max | Continuous aggregate | 13 months |
| 1-hour average, min, max | Continuous aggregate | 3 years |
| Events, alerts, audit log | Application | 3 years |

Superset and long-range charts read the rollups, never raw data older than a day.

### Hosting decision

Compression and continuous aggregates are TimescaleDB features, and not every managed
PostgreSQL service offers them (AWS RDS, for example, does not offer TimescaleDB). We choose
one of three options in the setup phase:

1. Self-managed PostgreSQL with TimescaleDB on cloud VMs or Kubernetes.
2. Timescale's own managed cloud service.
3. A managed PostgreSQL service with native partitioning (`pg_partman`) and our own rollup jobs.

## Backend

The backend is one Python codebase with FastAPI, deployed as four services that scale separately.

| Service | Job |
|---|---|
| Ingest API | Receives batches and heartbeats from collectors over mutual TLS, validates them and writes them with PostgreSQL `COPY` |
| App API | Everything the React app needs: inventory, live data, history, alerts, admin, Superset guest tokens |
| Alert worker | Checks rules against new readings, opens and closes alerts, sends notifications |
| Scheduler | Timed jobs: missing-data checks, firmware compliance, report emails, cleanup |

### Libraries

- FastAPI with Pydantic v2 for request and response models.
- SQLAlchemy 2 (async) with asyncpg; Alembic for schema migrations.
- Celery with Redis for background jobs. Superset already needs Celery and Redis, so we run one set.
- WebSockets for pushing live readings to open browser pages.

### Main endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/ingest/v1/config` | Collector fetches its server list and settings |
| POST | `/ingest/v1/batches` | Collector sends a batch of readings, health and events |
| POST | `/ingest/v1/heartbeat` | Collector reports it is alive |
| GET | `/api/v1/sites` | Sites with server counts and health summary |
| GET | `/api/v1/racks/{id}` | Rack with servers in position order |
| GET | `/api/v1/servers` | Server list with filters: site, vendor, model, health |
| GET | `/api/v1/servers/{id}` | Server detail: inventory, latest readings, health |
| GET | `/api/v1/servers/{id}/readings` | History for one metric: `metric`, `from`, `to`, `step` |
| WS | `/api/v1/live` | Live readings for the servers a page is showing |
| POST | `/api/v1/servers` | Onboard a server (BMC address, rack, position, collector) |
| PATCH | `/api/v1/servers/{id}` | Edit a server's rack, position or status |
| GET | `/api/v1/alerts` | Alerts with filters: state, severity, site |
| POST | `/api/v1/alerts/{id}/ack` | Acknowledge an alert |
| GET, PUT | `/api/v1/alert-rules` | Read and change alert rules |
| GET, PUT | `/api/v1/thresholds` | Read and change thresholds |
| GET | `/api/v1/firmware/compliance` | Servers whose firmware differs from the baseline |
| POST | `/api/v1/superset/guest-token` | Short-lived token for an embedded dashboard |
| GET | `/api/v1/audit` | Audit log |

### Conventions

- Versioned paths (`/v1`); OpenAPI docs generated by FastAPI.
- Cursor pagination on lists.
- Errors in the RFC 9457 problem-details format.
- Every request carries an SSO access token; each endpoint checks role and site access.

## Frontend

The React app is where people work day to day: live status, inventory, alerts and admin, with
Superset dashboards embedded for trends.

### Screens

| Screen | Shows | Main users |
|---|---|---|
| Global overview | All sites with server counts, health, open alerts, total power draw | Everyone |
| Site view | Rooms and racks, colored by worst health | NOC, DC engineers |
| Rack view | Rack elevation with each server in its U position, health and inlet temperature | DC engineers |
| Server detail | Live sensors (updating every minute), health per part, inventory, firmware, event log, 24-hour charts | NOC, DC engineers |
| Alerts | Open and past alerts, filters, acknowledge, comments | NOC |
| Inventory | Searchable list of servers and parts, export to CSV | DC engineers, analysts |
| Firmware compliance | Servers off the approved baseline | DC engineers |
| Analytics | Embedded Superset dashboards | Everyone |
| Admin | Sites, racks, server onboarding, collectors, thresholds, alert rules and routing, maintenance windows | Admins, DC engineers |
| Audit log | Who changed what and when | Admins |

### Technology

- React with TypeScript, built with Vite.
- React Router for pages; TanStack Query for API calls and caching.
- One component library (MUI or Ant Design; team choice in setup).
- ECharts or Recharts for live charts on the server page.
- `@superset-ui/embedded-sdk` to embed Superset dashboards.
- OIDC sign-in with the company identity provider (MSAL for Entra ID, or `oidc-client-ts`).
- Live updates over the `/api/v1/live` WebSocket.

### Design rules

- Health is always shown as a word and a color, never color alone.
- Every number shows its unit and how old it is (for example "41 °C, 30 s ago").
- Pages work on a laptop and a tablet; the NOC wall screen uses the global overview in full-screen mode.

## Monitoring with Apache Superset

Superset handles trends, comparisons and capacity analysis; the React app handles live status
and alerts, because Superset is built for analysis rather than second-by-second views or
stateful alerting.

### How it connects

- Superset reads from a PostgreSQL read replica through a read-only database user, so heavy queries never slow down ingest.
- It sees only a set of SQL views over the rollups, not the raw tables.
- Its own metadata (charts, dashboards, users) lives in a separate small PostgreSQL database.

### Datasets (views)

| View | Contents |
|---|---|
| `v_readings_5m` | 5-minute average, min, max per server, metric and part, with site, rack, vendor, model |
| `v_readings_1h` | Same at 1-hour grain, for long ranges |
| `v_server_health` | Current health per server and part |
| `v_alerts` | Alerts with open, acknowledge and resolve times |
| `v_inventory` | Servers and parts |
| `v_firmware_compliance` | Installed versus approved firmware |

### Dashboards

| Dashboard | Shows | Refresh |
|---|---|---|
| Data center overview | Health by site, open alerts, power and temperature summary | 5 min |
| Thermal | Inlet and exhaust temperature by site, room and rack; hot spots; fan speeds | 5 min |
| Power and capacity | Power draw by site and rack, peaks, headroom against capacity | 15 min |
| Hardware health | Failed and degraded parts, drive wear, top problem models | 15 min |
| Alerts | Alert counts, time to acknowledge, time to resolve, noisiest rules | 15 min |
| Inventory and firmware | Servers by vendor and model, firmware compliance | Daily |

### Embedding in the app

The React app embeds dashboards with the Superset embedded SDK. FastAPI asks Superset for a
guest token (valid 5 minutes) with row-level security for the user's sites, so users never sign
in to Superset separately. Analysts who build charts use Superset directly with SSO.

### Scheduled reports

Superset's alerts and reports feature sends scheduled summaries, such as a weekly capacity
report by email. Real-time alerting stays in the backend (next section).

### What Superset needs to run

A web server, Celery workers and a beat scheduler, Redis for cache and queues, and its metadata
database. We pin one Superset version and upgrade on purpose.

## Alerting

Our own alert worker raises alerts within 2 minutes of a problem and tracks each one from open
to resolved.

### Rule types

| Type | Fires when | Example |
|---|---|---|
| Threshold | A value stays past a limit for a set time | Inlet temperature above 35 °C for 3 minutes |
| State | A health state is not OK | Power supply reports Warning |
| Missing data | A server or collector goes quiet | No readings for 3 polls; collector heartbeat missing for 2 minutes |
| Event | A new critical event log entry arrives | "Temperature threshold exceeded" |
| Compliance | Checked daily | BIOS version differs from the baseline |

### How alerts behave

- One alert per server, metric and part; repeats update it instead of creating new ones.
- A value must stay bad for the rule's duration before it fires, and good for the same time before it resolves. This stops flapping.
- States: open, acknowledged, resolved. Every change is logged with who and when.
- Maintenance windows mute alerts for the servers, racks or sites they cover.
- Severities: Critical, Warning, Info.

### Routing

- Routes are set per site and severity, for example Critical alerts for one site go to that site's Teams channel and on-call email.
- Version 1 sends email and Microsoft Teams messages.
- A later phase adds ServiceNow or Jira tickets.
- Proposed escalation: a Critical alert not acknowledged in 15 minutes goes to the next contact.

## Security

BMC credentials never leave the data center, every connection is encrypted, and every user
action goes through SSO and role checks.

| Area | Control |
|---|---|
| BMC accounts | A dedicated read-only Redfish account on every BMC, separate from admin accounts; passwords rotated every 90 days |
| BMC credentials | Stored only on-prem in a secrets vault (for example HashiCorp Vault) that the collectors read; the cloud never holds them |
| BMC certificates | Replace self-signed BMC certificates with company CA certificates, or pin each one; certificate checks stay on in production |
| Collector to cloud | Outbound HTTPS on port 443 only; mutual TLS with a client certificate per collector; ingest accepts known collectors only |
| Network | Collectors sit on the management network; BMCs are never reachable from the internet |
| User sign-in | Company SSO over OIDC with MFA from the identity provider; roles from SSO groups |
| API | Token checked on every request; role and site checks per endpoint; rate limits |
| Database | Separate least-privilege users: ingest writes readings only, Superset reads views only; encryption at rest and in transit; encrypted backups |
| Superset | Guest tokens valid 5 minutes; row-level security by site; admin pages for admins only |
| Audit | Log sign-ins, asset changes, threshold and rule changes, alert actions |
| Supply chain | Dependency and container image scanning in CI; secrets in the cloud secret manager, never in code |
| Future write actions | Power or firmware actions would use a separate operator account, an approval step and full audit |

## Sizing and performance

At 500 servers the platform takes in about 20,000 readings a minute, which one collector pair
and a single PostgreSQL server handle comfortably. These are starting estimates to confirm in
the load test.

| Item | Estimate at 500 servers | How we got it |
|---|---|---|
| Readings per server per minute | About 40 | 20 parameters, several with many sensors (around 10 temperatures, 6 fans, 2 power supplies) |
| Readings per minute | About 20,000 (330 a second) | 40 × 500 |
| Readings per day | About 29 million | 20,000 × 1,440 |
| Raw storage per day | About 2 to 3 GB before compression | About 90 bytes per row with index |
| Raw storage for 30 days | About 60 to 90 GB before compression | Compression typically cuts this by 80 to 90% |
| Redfish calls | About 2,000 to 3,000 a minute in total | 4 to 6 calls per server per minute |
| Load on each BMC | At most 6 calls a minute | Well within what BMCs handle |

### Starting machine sizes

| Component | Size |
|---|---|
| Collector (2 per site) | 2 vCPU, 4 GB RAM, 50 GB disk for the offline buffer |
| Ingest API | 2 replicas, 1 vCPU and 2 GB each |
| App API | 2 replicas, 1 vCPU and 2 GB each |
| Alert worker and scheduler | 1 vCPU, 2 GB |
| PostgreSQL primary | 4 vCPU, 16 GB RAM, 500 GB storage |
| PostgreSQL read replica | Same as primary |
| Superset (web, workers, Redis) | 4 vCPU, 8 GB in total |

### Load test

Before go-live we simulate 500 BMCs with Redfish mockup servers and check: ingest keeps up with
no growing lag, live pages stay under 2 minutes old, and 30-day dashboards load in under 3 seconds.

### Growth

The same design should reach about 2,000 servers by adding collectors and a larger database.
Beyond that, we would add a message queue between ingest and the database.

## Deployment and operations

Everything ships as Docker images: the cloud side runs on Kubernetes, and each data center runs
two collector VMs.

### Cloud side

- Kubernetes (EKS on AWS or AKS on Azure) runs the ingest API, app API, alert worker, scheduler, Superset and Redis.
- The React app is built to static files and served from a CDN or an nginx container.
- PostgreSQL runs as chosen in the hosting decision, with a read replica.
- All infrastructure is defined in Terraform.

### On-prem side

- Two Linux VMs per site run the collector container.
- Each collector needs only its site ID, its client certificate and access to the vault.
- Collectors update by pulling a pinned image version, rolled out one collector at a time.

### Environments

| Environment | Purpose | Hardware data from |
|---|---|---|
| Dev | Local work with Docker Compose | DMTF Redfish mockup servers with Dell, HPE and Lenovo samples |
| Staging | Full test in the cloud before release | A lab collector polling a few real servers of each vendor |
| Production | Live | All onboarded servers |

### CI/CD

1. On every pull request: lint (ruff, ESLint), type checks (mypy, tsc), unit tests (pytest, Vitest), adapter tests against mockups, image and dependency scans.
2. On merge to main: build images, run Alembic migrations, deploy to staging.
3. On a release tag with approval: deploy to production.

### Watching the platform itself

- Metrics and traces through OpenTelemetry into the cloud's monitoring service.
- Key signals: ingest lag, readings per second, collector heartbeats, poll errors by vendor, API response times.
- Backups: daily full backup plus point-in-time recovery; a restore test every month.

## Delivery plan

We propose five phases over about 16 weeks, with a gate after data collection, after
hardening, and at go-live. Each gate is a go or no-go check; the next phase starts only when
its criteria are met.

| Phase | Delivers | Done when |
|---|---|---|
| Setup | BMC inventory with firmware versions, read-only accounts, network access for collectors, lab servers of each vendor, repo, CI, mockup servers, hosting decision | Collector VMs can reach a test BMC at each site |
| Collect data | Collector with Dell, HPE and Lenovo adapters, all 20 parameters, ingest API, database schema and rollups | Gate 1: data from all three vendors lands in PostgreSQL every minute |
| Build the app | React screens, app API, SSO and roles, onboarding, Superset datasets and dashboards embedded | Teams can find any server and see its live and historical health |
| Alerts, harden | Alert rules, routing to email and Teams, maintenance windows, security review, load test at 500 simulated servers | Gate 2: load test meets the sizing targets; security review passed |
| Pilot, roll out | One site live, feedback fixes, runbooks and training, then remaining sites | Go-live: pilot site signs off, all sites onboarded |
