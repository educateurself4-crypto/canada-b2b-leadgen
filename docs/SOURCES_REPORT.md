# Sources Report

Per the assignment's deliverable #17: every source used or evaluated, what
it provides, its limitations, and its cost/permission status.

## Implemented and wired into the pipeline

### 1. Corporations Canada — Federal Corporations open data
- **Level:** Federal
- **Publisher:** Innovation, Science and Economic Development Canada (ISED)
- **Access:** Bulk XML download (`OPEN_DATA_SPLIT.zip`), updated daily;
  also a per-corporation lookup page for targeted refresh.
- **Dataset page:** https://open.canada.ca/data/en/dataset/0032ce54-c5dd-4b66-99a0-320a7b5e99f2
- **Licence:** Open Government Licence – Canada. Free, including
  commercial use, with attribution.
- **Provides:** Legal name, corporation number, business number (CRA
  BN9), registered address (street/city/province/postal code),
  incorporation date, status (active/dissolved/etc.), governing act,
  min/max director count.
- **Limitations:**
  - No director/officer *names* in the bulk file (only counts) — names
    require the per-corporation detail page, fetched only for targeted
    enrichment, not bulk collection.
  - No employee count, industry/NAICS, website, phone, or email at all —
    this source establishes legal identity + address only; everything
    else needs enrichment from other sources.
  - Only covers *federally incorporated* entities (CBCA, NFP Act,
    cooperatives, boards of trade) — most small/local Canadian businesses
    are provincially incorporated or unincorporated (sole
    proprietorships), so this alone significantly undercounts the
    addressable market. Provincial/municipal sources are required to
    reach those businesses (see below).
  - New incorporations typically take ~1-2 weeks to appear in the daily
    bulk file, so "new today" detection for federal entities specifically
    has that lag; provincial/municipal sources are often faster for
    hyper-fresh leads.
- **Cost:** $0.

### 2. Provincial / municipal open-data portals (CKAN-based)
- **Level:** Provincial and municipal
- **Access:** Standard CKAN REST API (`/api/3/action/package_show`),
  present on most Canadian government open-data portals.
- **Implemented for (pre-configured, see `app/connectors/ckan_open_data.py`):**
  - Ontario (`data.ontario.ca`) — licensed-business / registration
    datasets.
  - Toronto (`open.toronto.ca`) — business-licence dataset.
- **Licence:** Open Government Licence – Ontario / – Toronto (and
  equivalents for other provinces/cities). Free, commercial use
  permitted, attribution required.
- **Provides:** Varies per dataset — generally business/operator name,
  licence type (proxy for industry), address, and sometimes status/issue
  date. Does not generally include employee counts, corporation numbers,
  or private contact emails.
- **Limitations:**
  - Coverage is licence-based, not registration-based — only businesses
    that hold the specific licence type the dataset tracks appear (e.g.
    Toronto's business-licence dataset won't include every business in
    the city, only licensed categories).
  - Column names and update frequency vary by portal; the generic
    connector's `DEFAULT_HEADER_HINTS` needs per-source verification (see
    `docs/ADDING_SOURCES.md`) before being trusted at scale.
  - **This build could not live-verify exact dataset slugs and CSV
    headers** because this development container has no outbound network
    access. The dataset IDs in `SOURCE_REGISTRY` are documented
    best-effort matches and are flagged in-code as "verify slug on
    portal" — this is the single most important thing to check before
    scheduling in production.
- **Cost:** $0.
- **Scaling path:** the same connector works for every other CKAN portal
  in Canada (Alberta, BC, Vancouver, Calgary, Edmonton, Winnipeg, and
  most other major municipalities) — each is a config addition, not new
  code. See `docs/ADDING_SOURCES.md`.

### 3. Company website enrichment (decision-maker contacts)
- **Level:** Per-business
- **Access:** The business's own public website (About/Team/Contact/
  Leadership pages), checked against `robots.txt` before fetching.
- **Provides:** Names, titles, and sometimes emails/phone numbers for
  owners, GMs, IT managers, and similar publicly-listed roles — exactly
  the kind of self-published contact information the business intends to
  be found by.
- **Limitations:**
  - Coverage depends entirely on whether a business publishes a team/
    about page with real names — many small businesses don't.
  - Heuristic (regex/keyword) extraction, not NLP — will miss
    non-standard phrasing and occasionally mis-attribute a title to the
    wrong nearby name; every contact is stored with its exact source URL
    so the sales team can verify before using it.
- **Cost:** $0.

## Documented but NOT implemented (require payment, or would require
## bypassing access controls / terms of service — excluded per the
## assignment's compliance requirement)

### LinkedIn (company pages / employee search)
The single richest source of exactly the "manager / IT director /
procurement contact" data this project wants — but LinkedIn's Terms of
Service prohibit automated scraping, and its official data products
(Sales Navigator, Talent/Recruiter APIs) are paid. **Not built.** If the
business decides a paid tool is acceptable later, this is the highest-
value one to evaluate — but it was explicitly kept out of the core (free)
system per the assignment's cost requirement.

### Provincial corporate registries without open-data feeds
Several provinces (e.g. Ontario's own Business Registry beyond the CKAN
licence data, BC's formal registry beyond OrgBook, Quebec's REQ) expose
search-only web interfaces rather than bulk open data. These are
generally *permitted* to query for individual lookups (useful for
targeted enrichment/refresh of a specific business already in the
database) but are not efficient or reliably permitted for bulk crawling.
Recommended next step: implement each as a targeted, rate-limited,
single-record lookup connector (same shape as the federal per-corporation
detail page) used during the refresh stage, not the initial bulk
collection stage.

### Paid data providers (Apollo, ZoomInfo, Data Axle, Dun & Bradstreet, etc.)
Explicitly excluded per the assignment brief. Noted here only for
completeness: these would fill the biggest gap in this system — verified
employee counts and direct-dial decision-maker contacts at scale — at a
real recurring cost. Not a dependency of this system.

## Summary table

| Source | Level | Free? | Implemented? | Key gap it fills |
|---|---|---|---|---|
| Corporations Canada | Federal | Yes | Yes | Legal identity, address, status |
| Provincial/municipal CKAN portals | Prov/Municipal | Yes | Yes (2 configured, generic connector scales further) | Locally-incorporated & licensed businesses |
| Company website enrichment | Per-business | Yes | Yes | Decision-maker names/contacts |
| Provincial registry single-lookup APIs | Provincial | Yes | Documented, not yet built | Refresh/verification of individual records |
| LinkedIn | Cross-cutting | No (ToS + paid API) | Not built (excluded intentionally) | Richest decision-maker data |
| Apollo/ZoomInfo/Data Axle/D&B | Cross-cutting | No | Not built (excluded per brief) | Verified employee counts, direct dials |
