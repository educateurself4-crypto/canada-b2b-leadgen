# Canada B2B Business Data Automation System — Trial Build

A self-hosted pipeline that collects, deduplicates, enriches, scores, and
serves Canadian business data for telecom B2B sales outreach — built on
free government open data and public sources, with **$0 required
recurring cost**.

This is a **trial-round submission**: it proves the architecture end to
end (real federal source, a scalable multi-source connector pattern,
dedup, scoring, new-business detection, dashboard, scheduling, logging)
rather than a fully populated national database. See
`docs/SOURCES_REPORT.md` for exactly what's wired up vs. what's scaffolded
for you to extend, and `docs/ADDING_SOURCES.md` for how to add the next
source in under an hour.

## What's actually implemented

| Deliverable | Status |
|---|---|
| Working app on a server (Docker Compose) | ✅ |
| PostgreSQL schema with source history | ✅ `db/schema.sql` |
| Federal-level source | ✅ Corporations Canada open data (`app/connectors/federal_corporations_canada.py`) |
| Provincial/municipal sources | ✅ Generic CKAN connector + registry, pre-configured for Ontario + Toronto (`app/connectors/ckan_open_data.py`) — add more portals as one-line config entries |
| New-business detection (today/7d/30d + change tracking) | ✅ `app/pipeline/new_business_detector.py` |
| Employee-size classification | ✅ `app/pipeline/employee_classifier.py` (honest: labels estimates as estimates, leaves unknowns null) |
| Contact/decision-maker enrichment | ✅ From each business's own public website only (`app/pipeline/enrichment.py`) — LinkedIn/paid-directory scraping intentionally **not** built, see `docs/SOURCES_REPORT.md` |
| Deduplication | ✅ `app/pipeline/dedup.py` — exact keys first, fuzzy fallback |
| Source-history (no blind overwrite) | ✅ `business_field_sources` table + `app/pipeline/storage.py` |
| Lead-quality scoring | ✅ `app/pipeline/scoring.py` — transparent weighted checklist |
| Dashboard: search/filter/export | ✅ `app/dashboard/` (Flask, CSV export) |
| Scheduled automation | ✅ `app/scheduler/scheduler.py` (APScheduler, runs in its own container) |
| Logging (per-source job runs) | ✅ `job_runs` table, visible on the dashboard |
| Do-Not-Call suppression | ✅ `businesses.do_not_call` + audit trail table, enforced in exports |
| Portable / redeployable | ✅ Docker Compose, no host-specific paths |

## Quick start (Ubuntu server, Docker + Docker Compose installed)

```bash
git clone <this repo> canada-b2b-leadgen
cd canada-b2b-leadgen
cp .env.example .env
# edit .env: set a real POSTGRES_PASSWORD, DASHBOARD_SECRET_KEY, and a
# USER_AGENT string with a real contact email (courtesy to source hosts)

docker compose build
docker compose up -d postgres
# wait ~10s for postgres healthcheck, then:
docker compose up -d scheduler dashboard
```

The `scheduler` container runs every configured source once immediately
on boot, then on the interval set by `COLLECT_INTERVAL_MINUTES` in `.env`
(default: every 6 hours). The `dashboard` container serves the UI at
`http://<server-ip>:8080`.

To run the pipeline once manually (e.g. to sanity-check before scheduling):

```bash
docker compose run --rm scheduler python -m app.scheduler.scheduler --once
```

## Redeploying on a different Ubuntu server

Nothing is hard-coded to this machine. To move it:

```bash
scp -r canada-b2b-leadgen/ user@new-server:/opt/
ssh user@new-server
cd /opt/canada-b2b-leadgen
cp .env.example .env   # fill in secrets again
docker compose up -d
```

The Postgres data volume (`pgdata`) is the only thing you'd want to also
migrate (`pg_dump`/`pg_restore`, or copy the Docker volume) if you want to
carry over already-collected data rather than start fresh.

## Repository layout

```
db/schema.sql                     Postgres schema (source of truth)
app/config.py, db.py, logging_config.py   Shared plumbing
app/connectors/                   One module per source (or source family)
app/pipeline/                     normalize -> dedup -> storage -> classify
                                   -> enrich -> score -> new-business events
app/scheduler/                    APScheduler process (the "cron")
app/dashboard/                    Flask UI (search/filter/export)
app/export/                       CSV export logic (shared by dashboard + scripts)
scripts/                          One-off / manual operational scripts
docs/                             Architecture, source-adding guide, sources report
tests/                            Unit tests for pure-logic modules
```

## Running tests

```bash
pip install -r requirements.txt pytest
pytest tests/
```

## Connecting to a CRM/dialer later

The dashboard's export and the `sales_ready_leads` / `new_businesses_today`
Postgres views are the two integration points: either point the CRM's
importer at a scheduled CSV export, or connect it directly to Postgres
(read-only role recommended) and query those views. Because Do-Not-Call
suppression is enforced at the database/export layer (not just in the UI),
any integration path automatically respects it.

## Compliance notes (see docs/SOURCES_REPORT.md for full detail)

- Every connector only uses documented public APIs/bulk downloads, or
  fetches pages permitted by `robots.txt`.
- No login bypass, CAPTCHA solving, or paywall circumvention anywhere in
  this codebase.
- `SCRAPE_DELAY_SECONDS` and a descriptive `USER_AGENT` (with a real
  contact email) are applied to every outbound request — set these in
  `.env` before running in production.
- Do-Not-Call requests are permanently suppressed at the database and
  export layer, not just hidden in the UI.
