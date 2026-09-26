#!/usr/bin/env bash
# Initialize the database schema manually (useful if not using docker-entrypoint)
# Usage: bash scripts/init_db.sh
set -e

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-leadgen}"
DB_USER="${POSTGRES_USER:-leadgen}"

echo "=== Initializing database schema ==="
echo "Host: $DB_HOST:$DB_PORT  Database: $DB_NAME  User: $DB_USER"

PGPASSWORD="${POSTGRES_PASSWORD:-changeme}" psql \
    -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
    -f db/schema.sql

echo "=== Schema initialized successfully ==="
