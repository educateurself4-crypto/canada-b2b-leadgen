# Canada B2B Business Data Automation System

A self-hosted, fully automated pipeline that collects, deduplicates, enriches,
scores, and serves Canadian business data for telecom B2B sales outreach — built
entirely on free government open data and public sources, with **$0 required
recurring cost**.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DATA COLLECTION LAYER                             │
│                                                                     │
│  Federal Registry ─┐                                                │
│  BC OrgBook ───────┤                                                │
│  CKAN Portals ─────┤── BaseConnector.fetch() → RawBusinessRecord   │
│  Socrata Portals ──┤                                                │
│  Opendatasoft ─────┤                                                │
│  YellowPages.ca ───┘                                                │
├─────────────────────────────────────────────────────────────────────┤
│                    PROCESSING PIPELINE                               │
│                                                                     │
│  normalize → dedup → upsert → classify_size → detect_new_biz      │
│       → enrich_contacts → score → log_job                          │
├─────────────────────────────────────────────────────────────────────┤
│                    DATA LAYER (PostgreSQL)                           │
│                                                                     │
│  businesses │ contacts │ business_field_sources │ business_identifiers│
│  new_business_events │ job_runs │ do_not_call_requests              │
├─────────────────────────────────────────────────────────────────────┤
│                    PRESENTATION LAYER                                │
│                                                                     │
│  Flask Dashboard (search/filter/export/DNC) │ REST API │ CSV Export │
└─────────────────────────────────────────────────────────────────────┘
```

## What's Implemented

| # | Deliverable | Status | Details |
|---|---|---|---|
| 1 | Working application (Docker Compose) | ✅ | `docker compose up -d` — 3 containers |
| 2 | PostgreSQL schema | ✅ | `db/schema.sql` — 7 tables + 2 views + indexes |
| 3 | Automated data collection | ✅ | 15+ source configs across 4 connector types |
| 4 | Federal-level source | ✅ | ISED Corporations Canada CSV + API enrichment |
| 5 | Provincial/local sources | ✅ | BC OrgBook, Ontario, Alberta, Toronto, Calgary, Edmonton, Vancouver, Montreal, Ottawa, Winnipeg, Halifax |
| 6 | New-business detection | ✅ | today/7d/30d + change tracking + BC OrgBook date filter |
| 7 | Employee-size classification | ✅ | 9 buckets, confirmed vs estimated labels |
| 8 | Contact/decision-maker enrichment | ✅ | Website scraping + Federal Corp API directors |
| 9 | Deduplication | ✅ | 5-key exact match + fuzzy fallback |
| 10 | Dashboard with filters | ✅ | Premium dark-theme UI, 10+ filters, sortable |
| 11 | CSV export | ✅ | With decision-maker contacts flattened |
| 12 | Automatic scheduled jobs | ✅ | APScheduler — collection, enrichment, refresh |
| 13 | Error logging | ✅ | `job_runs` table + file logs |
| 14 | Adding-sources documentation | ✅ | `docs/ADDING_SOURCES.md` |
| 15 | README | ✅ | This file |
| 16 | Clean code organization | ✅ | Modular connectors/pipeline/dashboard |
| 17 | Sources report | ✅ | `docs/SOURCES_REPORT.md` |

## Data Sources

| Source | Level | Type | Free? | Records |
|---|---|---|---|---|
| Corporations Canada (ISED CSV) | Federal | Bulk CSV | ✅ | ~640,000+ |
| ISED Federal Corp API | Federal | REST API | ✅ | Per-lookup |
| BC OrgBook | Provincial (BC) | REST API | ✅ | ~500,000+ |
| Ontario Licensed Businesses | Provincial (ON) | CKAN | ✅ | Varies |
| Alberta Licensed Businesses | Provincial (AB) | CKAN | ✅ | Varies |
| Toronto Business Licences | Municipal | CKAN | ✅ | ~80,000+ |
| Montreal Commercial Establishments | Municipal | CKAN | ✅ | Varies |
| Ottawa Business Licences | Municipal | CKAN | ✅ | Varies |
| Calgary Business Licences | Municipal | Socrata | ✅ | ~40,000+ |
| Edmonton Business Licences | Municipal | Socrata | ✅ | Varies |
| Winnipeg Business Licences | Municipal | Socrata | ✅ | Varies |
| Vancouver Business Licences | Municipal | Opendatasoft | ✅ | ~60,000+ |
| YellowPages.ca | Directory | Web scraper | ✅ | Supplementary |

## Quick Start

### Prerequisites
- Docker and Docker Compose installed
- Ubuntu 20.04+ (or any Linux with Docker)

### Deploy

```bash
git clone <this repo> canada-b2b-leadgen
cd canada-b2b-leadgen

# Configure environment
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, DASHBOARD_SECRET_KEY, USER_AGENT email

# Build and start
docker compose build
docker compose up -d postgres
# Wait ~10 seconds for Postgres healthcheck
docker compose up -d scheduler dashboard
```

### Access

- **Dashboard**: `http://<server-ip>:8080`
- **API**: `http://<server-ip>:8080/api/...` (requires `X-API-Key` header)

### Run pipeline manually

```bash
docker compose run --rm scheduler python -m app.scheduler.scheduler --once
```

## Redeploying on Another Server

```bash
scp -r canada-b2b-leadgen/ user@new-server:/opt/
ssh user@new-server
cd /opt/canada-b2b-leadgen
cp .env.example .env   # fill in secrets
docker compose up -d
```

To carry over existing data: `pg_dump` / `pg_restore` the Postgres volume.

## Repository Layout

```
db/schema.sql                     PostgreSQL schema (source of truth)
app/
├── config.py                     Central configuration (env-based)
├── db.py                         Database connection helper
├── logging_config.py             Logging setup
├── connectors/
│   ├── base.py                   BaseConnector + RawBusinessRecord
│   ├── federal_corporations_canada.py   ISED bulk CSV (federal)
│   ├── federal_corp_api.py       ISED per-corp API (director enrichment)
│   ├── bc_orgbook.py             BC OrgBook API (provincial)
│   ├── ckan_open_data.py         Generic CKAN connector + 10 configs
│   ├── socrata_open_data.py      Generic Socrata connector + 3 configs
│   ├── opendatasoft.py           Generic Opendatasoft connector + 1 config
│   └── yellowpages_scraper.py    YellowPages.ca scraper
├── pipeline/
│   ├── orchestrator.py           End-to-end pipeline: collect→store→score
│   ├── normalize.py              Phone/postal/province/domain normalization
│   ├── dedup.py                  5-key exact + fuzzy deduplication
│   ├── storage.py                Upsert with source-history tracking
│   ├── employee_classifier.py    9-bucket size classification
│   ├── enrichment.py             Website contact extraction
│   ├── new_business_detector.py  New/changed business events
│   └── scoring.py                Lead quality score (0-100)
├── scheduler/
│   └── scheduler.py              APScheduler: collection + enrichment + refresh
├── dashboard/
│   ├── app.py                    Flask app with API endpoints
│   └── templates/
│       ├── index.html            Main dashboard (dark theme)
│       └── detail.html           Business detail view
└── export/
    └── csv_export.py             CSV export with contacts

scripts/                          Operational scripts
tests/                            Unit tests
docs/                             Architecture, sources report, adding-sources guide
```

## API Endpoints

All API endpoints require `X-API-Key` header matching `AUTOMATION_API_KEY` in `.env`.

| Endpoint | Method | Description |
|---|---|---|
| `/api/leads/new?window=today\|7d\|30d` | GET | New leads by time window |
| `/api/stats` | GET | Dashboard statistics summary |
| `/api/jobs/recent` | GET | Recent pipeline job runs |
| `/api/business/<id>` | GET | Full business detail with contacts |
| `/api/trigger/<source_name>` | POST | Trigger a specific source collection |

## CRM/Dialer Integration

1. **CSV Import**: Dashboard export → CRM file import (scheduled or manual)
2. **Direct Postgres**: Read-only role on `sales_ready_leads` or `new_businesses_today` views
3. **REST API**: `/api/leads/new` endpoint returns JSON, ideal for webhooks
4. **Do-Not-Call**: Enforced at database + export layer — any integration path respects it

## Compliance

- Only publicly accessible data from documented APIs/bulk downloads
- No login bypass, CAPTCHA solving, or paywall circumvention
- `robots.txt` checked before website enrichment
- Rate limiting via `SCRAPE_DELAY_SECONDS`
- Descriptive `USER_AGENT` with contact email
- Do-Not-Call permanently suppressed at data layer
- All data sourced under Open Government Licences (Canada/provincial/municipal)

## Running Tests

```bash
pip install -r requirements.txt pytest
pytest tests/ -v
```

## Cost

| Component | Cost |
|---|---|
| All data sources | $0 (open government data + public APIs) |
| PostgreSQL | $0 (open source, self-hosted) |
| Application | $0 (Python, Flask, open source) |
| Server | Your existing infrastructure |
| **Total recurring** | **$0** |
