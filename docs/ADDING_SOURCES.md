# Adding a new data source

## Case A: another CKAN-based open-data portal (most provinces/cities)

Most Canadian open-data portals (provincial and municipal) run CKAN. To
check: visit `https://<portal-domain>/api/3/action/package_list` — if you
get back a JSON list of dataset slugs, it's CKAN and you can use the
generic connector.

Steps:
1. Browse the portal's catalogue in your browser, search for "business
   licence", "business registry", or "corporations", and open the dataset
   you want. Copy the URL slug (the last path segment).
2. Confirm the dataset has a downloadable CSV resource (check the
   dataset page).
3. Add an entry to `SOURCE_REGISTRY` in
   `app/connectors/ckan_open_data.py`:

```python
CkanSourceConfig(
    key="vancouver_business_licences",
    base_url="https://opendata.vancouver.ca",
    dataset_id="business-licences",   # the slug you copied
    province="BC",
),
```

4. Fetch the CSV once manually (`curl` the resource URL from the dataset
   page) and check its column headers against `DEFAULT_HEADER_HINTS` in
   the same file. If headers don't match (e.g. French column names, or an
   unusual naming convention), pass a custom `field_map` in the
   `CkanSourceConfig` entry — same shape as `DEFAULT_HEADER_HINTS`, but
   only for the fields that need overriding.
5. Run it once in isolation to sanity check before scheduling:

```python
from app.connectors.ckan_open_data import CkanOpenDataConnector, SOURCE_REGISTRY
from app.pipeline.orchestrator import run_connector

cfg = next(c for c in SOURCE_REGISTRY if c.key == "vancouver_business_licences")
run_connector(CkanOpenDataConnector(cfg), enrich_contacts=False)
```

6. Once satisfied, it's already picked up automatically by
   `collect_ckan_sources()` in `app/scheduler/scheduler.py` — no scheduler
   changes needed.

## Case B: a non-CKAN source (custom API, different bulk format, etc.)

1. Create `app/connectors/<your_source>.py`.
2. Subclass `BaseConnector` (see `app/connectors/base.py`).
3. Implement `fetch()` as a **generator** that yields `RawBusinessRecord`
   objects — set `source_name`, `source_kind`, and `source_url` on every
   record for provenance.
4. Use `self._get(url)` for HTTP requests — it already applies the
   configured delay and User-Agent.
5. Add a job to `app/scheduler/scheduler.py` calling
   `run_connector(YourConnector())` on whatever interval makes sense for
   that source's update frequency.
6. Write at least one unit test for any parsing/normalization logic you
   added, in `tests/`.

## Verifying a federal/provincial registry's exact field names

`app/connectors/federal_corporations_canada.py` documents this in its
module docstring: the XML tag names in `CORP_XML_TAGS` are the best
available documented mapping but should be verified against one freshly
downloaded sample before the connector is scheduled in production,
because this repository was built without live network access to
confirm them against the current file. The connector is defensive (a
missing tag becomes `None`, it doesn't raise), so an unverified mapping
fails safe — you just get fewer populated fields, not bad data — but
verifying first avoids wasted collection runs.

## Adding a new employee-size signal

If you find a source that reports real headcounts (e.g. a business
directory listing "50-100 employees"), pass it through as
`employee_count_min` / `employee_count_max` on the `RawBusinessRecord`,
or as an exact `exact_count` directly into
`app/pipeline/employee_classifier.classify()` if you have a true single
number. Do not invent a range from unrelated signals (like revenue) —
the requirement is explicit that unverified estimates must be clearly
labeled, and a bucket with no real signal should stay `NULL`.
