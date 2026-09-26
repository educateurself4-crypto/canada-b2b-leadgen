# Architecture

## Pipeline shape

```
 Connector.fetch()          one per source, yields RawBusinessRecord
        |
 normalize.normalize_record()   clean/standardize (phone->E.164, province
        |                        codes, postal code format, domain extraction)
 dedup.find_existing_business()  exact-key lookup first (corp #, domain,
        |                        phone, postal+name), fuzzy name fallback
        v
 storage.insert_business() / update_business()
        |                        never blind-overwrites; every field write
        |                        also logged to business_field_sources with
        |                        its own confidence + provenance
        v
 employee_classifier.classify()   buckets into the 9 required size ranges,
        |                          labels estimated vs confirmed
        v
 new_business_detector.record_events()  writes new_today/7d/30d or
        |                                recently_changed rows
        v
 enrichment.WebsiteContactEnrichment    (batched, separate pass) pulls
        |                               decision-maker contacts from the
        |                               business's own public site only
        v
 scoring.score_business()          recomputes quality_score + lead_ready
        |
 job_runs logging                  every run recorded: source, counts,
                                    errors, timestamps
```

All of this is orchestrated by `app/pipeline/orchestrator.py::run_connector`,
which any connector — present or future — plugs into identically. Adding a
source never means writing new dedup/scoring/classification logic; it only
means writing (or configuring) something that yields `RawBusinessRecord`s.

## Why Postgres + raw SQL instead of an ORM

The schema is stable and the team evaluating this is explicitly judging
code quality and the ability for others to extend it — plain, readable SQL
in `db/schema.sql` plus small parameterized queries is easier to audit,
diff, and hand off than an ORM abstraction layer for a project this size.
If the system grows substantially, introducing SQLAlchemy Core (not
necessarily the full ORM) is a reasonable next step without touching the
schema.

## Why CKAN as the scaling mechanism for provincial/local sources

Task requirement: "multiple provincial/local sources" and "a real
framework capable of expanding across all of Canada," not a demo tied to
one city. Most Canadian federal/provincial/municipal open-data portals run
the same open-source platform (CKAN) with the same REST API shape
(`/api/3/action/package_show`). Writing one generic, configurable
`CkanOpenDataConnector` and a `SOURCE_REGISTRY` list means every new
CKAN-based portal (there are dozens across Canada) is a ~5-line config
addition, not a new scraper. Non-CKAN sources (e.g. a province that only
publishes a proprietary registry search UI) get their own connector
subclassing `BaseConnector`, same as the federal one.

## Why source-history instead of overwrite-in-place

The client requirement is explicit: "Do not simply overwrite conflicting
information. Keep source history." `business_field_sources` stores every
value we've ever seen for every field, tagged by source and confidence;
`businesses` always reflects the currently-highest-confidence pick per
field. This means:
  * We can always explain why a phone number or address is what it is.
  * A bad/stale source doesn't silently corrupt a good record — it just
    loses the "current pick" comparison.
  * Multiple-source confirmation (used in the quality score) is a simple
    `COUNT(DISTINCT source_name)` query.

## Why the quality score is a transparent checklist, not a model

The call-centre team needs to trust and act on scores quickly. A weighted
checklist (`app/pipeline/scoring.py`) is auditable, tunable per business
priority (e.g. raise the weight on "decision-maker found" if that matters
more than "recently verified"), and needs no training data or ML
infrastructure — consistent with the $0-recurring-cost requirement.

## Scaling from trial to production

1. Add more `CkanSourceConfig` entries (Alberta, BC, Vancouver, Calgary,
   Winnipeg, etc. — see `docs/ADDING_SOURCES.md`).
2. Add provincial corporate-registry connectors for provinces with their
   own non-CKAN system (e.g. BC's OrgBook, Ontario's Business Registry) —
   each is a `BaseConnector` subclass, same pattern as the federal one.
3. Increase `enrich_recent_websites` batch size / run it as its own
   scheduled job once the businesses table is large, so enrichment doesn't
   compete with collection for time.
4. Move from the bundled Flask dev server to gunicorn + a reverse proxy
   (nginx/Caddy) for the dashboard once it's exposed beyond localhost/VPN.
5. Add a read-only Postgres role for CRM/dialer integration (see README).
