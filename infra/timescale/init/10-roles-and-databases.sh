#!/usr/bin/env bash
# Runs once, on first start of an empty data directory (docker-entrypoint-initdb.d).
# Creates the least-privilege login roles and the extra databases. Table-level grants are
# applied by the Alembic migrations, so they stay in sync with the schema.
#
#   gcc_owner (POSTGRES_USER)  owns the schema; used only by migrations
#   gcc_app                    app API, alert worker, scheduler
#   gcc_ingest                 ingest API: writes readings, health, events, inventory
#   gcc_superset_ro            Superset: SELECT on the reporting views only
set -euo pipefail

: "${GCC_APP_DB_PASSWORD:?}"
: "${GCC_INGEST_DB_PASSWORD:?}"
: "${GCC_SUPERSET_RO_DB_PASSWORD:?}"
: "${SUPERSET_META_DB_PASSWORD:?}"
: "${KEYCLOAK_DB_PASSWORD:?}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_pw="$GCC_APP_DB_PASSWORD" \
  -v ingest_pw="$GCC_INGEST_DB_PASSWORD" \
  -v ro_pw="$GCC_SUPERSET_RO_DB_PASSWORD" \
  -v meta_pw="$SUPERSET_META_DB_PASSWORD" \
  -v kc_pw="$KEYCLOAK_DB_PASSWORD" \
  -v dbname="$POSTGRES_DB" <<'EOSQL'
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE ROLE gcc_app LOGIN PASSWORD :'app_pw';
CREATE ROLE gcc_ingest LOGIN PASSWORD :'ingest_pw';
CREATE ROLE gcc_superset_ro LOGIN PASSWORD :'ro_pw';
ALTER ROLE gcc_superset_ro SET default_transaction_read_only = on;
ALTER ROLE gcc_superset_ro SET statement_timeout = '60s';

-- Superset's own metadata and Keycloak live in separate small databases.
CREATE ROLE superset_meta LOGIN PASSWORD :'meta_pw';
CREATE DATABASE superset_meta OWNER superset_meta;
CREATE ROLE keycloak LOGIN PASSWORD :'kc_pw';
CREATE DATABASE keycloak OWNER keycloak;

REVOKE ALL ON DATABASE superset_meta FROM PUBLIC;
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT CONNECT ON DATABASE :"dbname" TO gcc_app, gcc_ingest, gcc_superset_ro;
EOSQL
