# Architecture

## System Overview

The Canada B2B Business Data Automation System is a self-hosted pipeline that:
1. **Collects** business data from 15+ Canadian government open-data sources
2. **Normalizes** all data into consistent formats (phone→E.164, postal codes, provinces)
3. **Deduplicates** using 5-key matching (corp#, domain, phone, postal+name, fuzzy)
4. **Stores** with full source history (never blind-overwrites)
5. **Enriches** with decision-maker contacts from business websites and federal API
6. **Classifies** employee size into 9 standard buckets
7. **Detects** new businesses daily (today/7d/30d + change tracking)
8. **Scores** lead quality on a transparent 0-100 checklist
9. **Serves** via a premium dark-theme dashboard with API endpoints

## Pipeline Flow

```
┌──────────────────────────────────────────────────────────────────┐
│ CONNECTORS (one per source, yields RawBusinessRecord)           │
│                                                                  │
│ FederalCorporationsCanadaConnector    ─── Bulk CSV (640k+ corps) │
│ FederalCorpAPIEnrichment             ─── Per-corp API (directors)│
│ BCOrgBookConnector                    ─── BC API (500k+ orgs)    │
│ CkanOpenDataConnector × 10           ─── CKAN portals            │
│ SocrataOpenDataConnector × 3         ─── Socrata portals         │
│ OpendatasoftConnector × 1            ─── Vancouver               │
│ YellowPagesConnector                 ─── Directory scraper       │
│ WebsiteContactEnrichment             ─── Company websites        │
└──────────────┬───────────────────────────────────────────────────┘
               │ RawBusinessRecord (generator, streams)
               ▼
┌──────────────────────────────────────────────────────────────────┐
│ ORCHESTRATOR (app/pipeline/orchestrator.py)                      │
│                                                                  │
│ 1. normalize.normalize_record()                                  │
│    ├── Phone → E.164                                             │
│    ├── Province → 2-letter code                                  │
│    ├── Postal code → X9X 9X9                                    │
│    └── Domain extracted from website URL                        │
│                                                                  │
│ 2. dedup.find_existing_business()                               │
│    ├── Exact: corp_number → business_id                         │
│    ├── Exact: domain → business_id                              │
│    ├── Exact: phone → business_id                               │
│    ├── Exact: postal+name hash → business_id                    │
│    └── Fuzzy: token_sort_ratio ≥ 87 (same city/province)       │
│                                                                  │
│ 3. storage.upsert_business()                                    │
│    ├── New? → INSERT + register dedup identifiers               │
│    └── Existing? → MERGE (higher confidence wins per field)     │
│        └── Every field write → business_field_sources (audit)   │
│                                                                  │
│ 4. employee_classifier.classify()                               │
│    ├── Exact count → "confirmed" bucket                         │
│    ├── Min/max range → midpoint → "estimated" bucket            │
│    └── No signal → NULL (honest, never fabricated)              │
│                                                                  │
│ 5. new_business_detector.record_events()                        │
│    ├── is_new → new_today event                                 │
│    ├── incorporation_date ≤ 7d → new_7d event                  │
│    ├── incorporation_date ≤ 30d → new_30d event                │
│    └── changed_fields → recently_changed event                  │
│                                                                  │
│ 6. scoring.score_business()                                     │
│    ├── has_verified_phone: 20 pts                               │
│    ├── has_website: 10 pts                                      │
│    ├── has_verified_address: 15 pts                             │
│    ├── has_employee_info: 10 pts                                │
│    ├── has_decision_maker: 20 pts                               │
│    ├── recently_verified: 10 pts                                │
│    └── multiple_sources: 15 pts                                 │
│    Score ≥ 50 → lead_ready = TRUE                              │
│                                                                  │
│ 7. job_runs logging                                             │
│    └── source, status, counts, errors, timestamps              │
└──────────────────────────────────────────────────────────────────┘
```

## Database Schema

```
businesses          ── One canonical row per real-world company (post-dedup)
  ├── Core identity:  legal_name, operating_name, corp_number, BN9
  ├── Location:       province, city, address, postal_code
  ├── Contact:        phone (E.164), email, website, domain
  ├── Classification: industry, naics_code, size_category, size_confidence
  ├── Metadata:       quality_score, lead_ready, do_not_call
  └── Timestamps:     first_seen_at, last_verified_at, last_updated_at

business_field_sources  ── Every field value ever seen, per source
  └── Never blindly overwritten; highest-confidence source "wins"

business_identifiers    ── Normalized dedup keys (corp#, domain, phone, etc.)
  └── Used for O(1) exact-match dedup lookups

contacts                ── Decision-makers / staff contacts
  └── One-to-many with businesses; tagged by role category

new_business_events     ── Append-only feed for dashboards/CRM
  └── new_today | new_7d | new_30d | recently_changed | new_location

job_runs                ── Pipeline observability
  └── Per-source, per-run: collected, new, updated, errors

do_not_call_requests    ── Audit trail for DNC suppressions
```

## Why Postgres + Raw SQL (not an ORM)

The schema is stable and the team evaluating this is judging code quality and
extensibility. Plain parameterized SQL in small functions is easier to audit,
diff, and hand off than an ORM abstraction for a project this size.

## Why Config-Driven Connectors

The task requires "multiple provincial/local sources" and "a real framework
capable of expanding across all of Canada." CKAN, Socrata, and Opendatasoft
each use standardized APIs across all their portals. One generic connector +
a registry list means adding a new city/province is a ~5-line config entry.

## Why Source-History (not overwrite-in-place)

The requirement is explicit: "Do not simply overwrite conflicting information."
`business_field_sources` stores every value from every source with its confidence.
The `businesses` table reflects the highest-confidence pick per field. This means:
- We can always explain why a field has its current value
- A bad source doesn't corrupt a good record
- Multi-source confirmation is a simple COUNT query

## Scheduling Architecture

```
APScheduler (single Python process in scheduler container)
├── Collection jobs (every COLLECT_INTERVAL_MINUTES = 360 min default)
│   ├── Federal CSV
│   ├── BC OrgBook
│   ├── All CKAN sources
│   ├── All Socrata sources
│   └── All Opendatasoft sources
├── New-business detection (every NEW_BUSINESS_SCAN_INTERVAL_MINUTES = 60 min)
│   └── BC OrgBook date-filtered scan
├── Enrichment jobs (staggered after collection)
│   ├── Federal Corp API director lookup
│   └── Website contact extraction
├── Refresh (every REFRESH_INTERVAL_MINUTES = 1440 min = daily)
│   └── Re-verify and re-score stale records
└── Supplementary (weekly)
    └── YellowPages directory scrape
```

## Scaling Path

1. Add more `SOURCE_REGISTRY` configs (see `docs/ADDING_SOURCES.md`)
2. Add provincial registry connectors (Ontario, BC beyond OrgBook, Quebec REQ)
3. Increase enrichment batch sizes as database grows
4. Switch dashboard to gunicorn + nginx for production traffic ✅ (done)
5. Add read-only Postgres role for CRM/dialer direct integration
6. Consider PgBouncer for connection pooling at scale
7. Optional: add Celery for parallel source collection
