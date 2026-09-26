# Adding a New Data Source

This guide covers how to add any new Canadian data source to the system.
The architecture is designed so that most sources require only configuration,
not new code.

## Decision Tree: Which Connector to Use

```
Is the source a CKAN portal?
  └── Yes → Add config to ckan_open_data.py SOURCE_REGISTRY (Case A)

Is the source a Socrata portal?
  └── Yes → Add config to socrata_open_data.py SOURCE_REGISTRY (Case B)

Is the source an Opendatasoft portal?
  └── Yes → Add config to opendatasoft.py SOURCE_REGISTRY (Case C)

Does it have a REST API returning JSON/CSV?
  └── Yes → Create a new connector subclassing BaseConnector (Case D)

Is it a webpage that must be scraped?
  └── Yes → Create a scraper connector like yellowpages_scraper.py (Case E)
```

## Case A: CKAN Portal (most provinces/cities)

Most Canadian open-data portals run CKAN. Quick check: visit
`https://<portal>/api/3/action/package_list` — if you get JSON back, it's CKAN.

### Steps:

1. Browse the portal, search for "business licence" / "business registry".
2. Open the dataset page, copy the URL slug.
3. Check the dataset has a CSV resource.
4. Add an entry to `SOURCE_REGISTRY` in `app/connectors/ckan_open_data.py`:

```python
CkanSourceConfig(
    key="<city>_business_licences",         # unique internal name
    base_url="https://<portal-domain>",     # portal root URL
    dataset_id="<slug-from-url>",           # dataset slug
    province="<XX>",                        # 2-letter province code
),
```

5. Download the CSV once manually and verify column headers match
   `DEFAULT_HEADER_HINTS`. If not, add a custom `field_map`:

```python
CkanSourceConfig(
    key="<city>_business_licences",
    base_url="https://<portal-domain>",
    dataset_id="<slug>",
    province="<XX>",
    field_map={
        "legal_name": ["actual_column_name", "alternative_name"],
        "address_line1": ["address_col"],
    },
),
```

6. Test it once in isolation:

```python
from app.connectors.ckan_open_data import CkanOpenDataConnector, SOURCE_REGISTRY
from app.pipeline.orchestrator import run_connector

cfg = next(c for c in SOURCE_REGISTRY if c.key == "<your_key>")
run_connector(CkanOpenDataConnector(cfg), enrich_contacts=False)
```

7. Done! The scheduler picks it up automatically via `collect_ckan_sources()`.

## Case B: Socrata Portal

Socrata portals use 4-character dataset IDs (e.g., `ed4p-nj59`).

Same pattern as CKAN — add to `SOURCE_REGISTRY` in
`app/connectors/socrata_open_data.py`:

```python
SocrataSourceConfig(
    key="<city>_business_licences",
    base_url="https://data.<city>.ca",
    dataset_id="<4x4-id>",
    province="<XX>",
),
```

## Case C: Opendatasoft Portal

Same pattern — add to `SOURCE_REGISTRY` in `app/connectors/opendatasoft.py`.

## Case D: Custom API Connector

1. Create `app/connectors/<your_source>.py`
2. Subclass `BaseConnector` (see `app/connectors/base.py`)
3. Implement `fetch()` as a **generator** yielding `RawBusinessRecord` objects
4. Set `source_name`, `source_kind`, `source_url` on every record
5. Use `self._get(url)` for HTTP requests (applies delay + User-Agent)
6. Add to `app/scheduler/scheduler.py`:

```python
from app.connectors.your_source import YourConnector

def collect_your_source():
    run_connector(YourConnector())

# In main():
scheduler.add_job(collect_your_source, "interval",
    minutes=config.COLLECT_INTERVAL_MINUTES, id="collect_your_source")
```

7. Write at least one unit test in `tests/`.

## Case E: Web Scraper

Same as Case D, but:
- Check `robots.txt` before scraping
- Use `self._get()` which enforces `SCRAPE_DELAY_SECONDS`
- Set lower confidence (0.5-0.6) since web scraping is less reliable
- Never bypass logins, CAPTCHAs, or paywalls

## Adding Employee-Size Signals

If a source reports headcounts:
- Pass as `employee_count_min` / `employee_count_max` on `RawBusinessRecord`
- For exact counts, call `employee_classifier.classify(exact_count=N)` directly
- Never invent ranges from unrelated signals (revenue, etc.)
- An unlabeled record is more honest than a fabricated bucket

## Verification Checklist Before Production

Before scheduling a new source:

- [ ] Dataset ID/slug verified against the live portal
- [ ] CSV downloaded and column headers inspected
- [ ] `field_map` configured for non-standard headers
- [ ] One test run with `run_connector(connector, enrich_contacts=False)`
- [ ] Records appear correctly in the dashboard
- [ ] No error in `job_runs` table
- [ ] Source added to `docs/SOURCES_REPORT.md`
- [ ] Licence/terms confirmed (free? commercial use?)

## Known CKAN Portals in Canada (ready to add)

| Portal | URL | Province | Status |
|---|---|---|---|
| Government of Canada | open.canada.ca | Federal | ✅ In use |
| Ontario | data.ontario.ca | ON | ✅ Configured |
| Alberta | open.alberta.ca | AB | ✅ Configured |
| British Columbia | catalogue.data.gov.bc.ca | BC | Ready to add |
| Quebec | donneesquebec.ca | QC | Ready to add |
| New Brunswick | open.canada.ca/data/en | NB | Check datasets |
| Newfoundland | opendata.gov.nl.ca | NL | Ready to add |
| Saskatchewan | publications.saskatchewan.ca | SK | ISC-managed, limited |
| Manitoba | geoportal.gov.mb.ca | MB | ✅ Configured |
| Toronto | open.toronto.ca | ON | ✅ Configured |
| Montreal | donnees.montreal.ca | QC | ✅ Configured |
| Vancouver | opendata.vancouver.ca | BC | ✅ Configured |
| Calgary | data.calgary.ca | AB | ✅ Configured |
| Edmonton | data.edmonton.ca | AB | ✅ Configured |
| Ottawa | open.ottawa.ca | ON | ✅ Configured |
| Winnipeg | data.winnipeg.ca | MB | ✅ Configured |
| Halifax | catalogue.hrm.opendata.arcgis.com | NS | ✅ Configured |
| Hamilton | open.hamilton.ca | ON | Ready to add |
| Kitchener | open.kitchener.ca | ON | Ready to add |
| London | data.london.ca | ON | Ready to add |
| Waterloo | data.waterloo.ca | ON | Ready to add |
