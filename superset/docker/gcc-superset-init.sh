#!/usr/bin/env bash
# superset-init: migrate Superset's metadata DB, sync built-in roles, then run the idempotent GCC bootstrap
# (admin + embed users, bundle import, roles/RLS, embedding, weekly report). Safe on every start.
set -euo pipefail

attempt=1
until superset db upgrade; do
  if [ "$attempt" -ge 10 ]; then
    echo "superset db upgrade failed after $attempt attempts" >&2
    exit 1
  fi
  echo "metadata database not ready (attempt $attempt); retrying in 5 s" >&2
  attempt=$((attempt + 1))
  sleep 5
done

superset init
exec python /app/gcc/init_superset.py
