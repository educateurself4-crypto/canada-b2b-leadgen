#!/usr/bin/env bash
# Initializes the database schema. Docker Compose already does this
# automatically on first boot (via db/schema.sql mounted into
# /docker-entrypoint-initdb.d/), but this script is here for manual
# re-runs / non-Docker Postgres installs.
set -euo pipefail
: "${DATABASE_URL:?Set DATABASE_URL, e.g. postgresql://leadgen:changeme@localhost:5432/leadgen}"
psql "$DATABASE_URL" -f "$(dirname "$0")/../db/schema.sql"
echo "Schema applied."
