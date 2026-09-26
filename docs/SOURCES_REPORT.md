# Sources Report

Per the assignment's deliverable #17: every source used or evaluated, what
it provides, its limitations, and its cost/permission status.

## Implemented Sources — Fully Wired into the Pipeline

### 1. Corporations Canada — Federal Corporations (Bulk CSV)
- **Level:** Federal
- **Publisher:** Innovation, Science and Economic Development Canada (ISED)
- **Connector:** `app/connectors/federal_corporations_canada.py`
- **Access:** Bulk CSV download from CloudFront CDN, updated daily.
- **Dataset:** https://open.canada.ca/data/en/dataset/0032ce54-c5dd-4b66-99a0-320a7b5e99f2
- **Licence:** Open Government Licence – Canada. Free, commercial use, attribution.
- **Provides:** Legal name, corporation number, BN9, registered address,
  incorporation date, status, governing act, min/max director count.
- **Limitations:** No director names in bulk (only counts), no employee count,
  no industry/NAICS, no website/phone/email. Only federal incorporations.
- **Cost:** $0

### 2. Corporations Canada — Federal Corporation API (Enrichment)
- **Level:** Federal
- **Publisher:** ISED
- **Connector:** `app/connectors/federal_corp_api.py`
- **Access:** REST API at `apigateway-passerelledapi.ised-isde.canada.ca`
- **Licence:** Open Government Licence – Canada. Free.
- **Provides:** Director/officer names and titles for individual corporations.
- **Limitations:** Single-record lookup only (no bulk). Rate-limited. Used for
  targeted enrichment only, not initial collection.
- **Cost:** $0

### 3. BC OrgBook (BC Corporate Registry)
- **Level:** Provincial (British Columbia)
- **Publisher:** Government of British Columbia
- **Connector:** `app/connectors/bc_orgbook.py`
- **Access:** REST API at `orgbook.gov.bc.ca/api/v4/`
- **Licence:** BC Government Access Only Terms. Free, public API, no key.
- **Provides:** Legal name, DBA names, BC registration number, entity type,
  entity status, registration date. ~500,000+ active organizations.
- **Limitations:** No address, phone, email, or employee count. Good for
  establishing legal identity + status; enrichment needed from other sources.
- **New-business detection:** Supports date filtering via the API, enabling
  daily scans for newly registered BC businesses.
- **Cost:** $0

### 4. Provincial/Municipal CKAN Open-Data Portals (10 configs)
- **Level:** Provincial and municipal
- **Connector:** `app/connectors/ckan_open_data.py` (generic, config-driven)
- **Access:** Standard CKAN REST API (`/api/3/action/package_show`)
- **Implemented for:**
  | Source Key | Portal | Province | Coverage |
  |---|---|---|---|
  | ontario_licensed_businesses | data.ontario.ca | ON | Provincial licences |
  | toronto_business_licences | open.toronto.ca | ON | ~80,000+ licenced businesses |
  | alberta_licensed_businesses | open.alberta.ca | AB | Provincial licences |
  | montreal_commercial_establishments | donnees.montreal.ca | QC | Food establishments |
  | montreal_locaux_commerciaux | donnees.montreal.ca | QC | Commercial premises |
  | ottawa_business_licences | open.ottawa.ca | ON | Municipal licences |
  | halifax_business_registrations | catalogue.hrm.opendata.arcgis.com | NS | Municipal licences |
  | brampton_business_directory | geohub.brampton.ca | ON | Business directory |
  | manitoba_business_listings | geoportal.gov.mb.ca | MB | Provincial listings |
- **Licence:** Open Government Licence (Canada/Ontario/Toronto/Alberta/etc.)
  Free, commercial use, attribution required.
- **Provides:** Varies by dataset — generally business name, licence type (industry
  proxy), address, sometimes status and issue date.
- **Limitations:** Coverage is licence-based, not registration-based. Column names
  vary; auto-detection with `DEFAULT_HEADER_HINTS` + custom `field_map`.
  Dataset IDs should be verified on each portal before production.
- **Scaling:** Same connector works for any CKAN portal. Adding a new city/province
  is a ~5-line config entry, not new code.
- **Cost:** $0

### 5. Socrata Open-Data Portals (3 configs)
- **Level:** Municipal
- **Connector:** `app/connectors/socrata_open_data.py` (generic, config-driven)
- **Access:** SODA API with CSV export (`/resource/{id}.csv`)
- **Implemented for:**
  | Source Key | Portal | Province |
  |---|---|---|
  | calgary_business_licences | data.calgary.ca | AB |
  | edmonton_business_licences | data.edmonton.ca | AB |
  | winnipeg_business_licences | data.winnipeg.ca | MB |
- **Licence:** Open Data Licence (Calgary/Edmonton/Winnipeg). Free, commercial use.
- **Provides:** Business name, address, licence type, status, issue date.
- **Limitations:** Similar to CKAN — licence-based coverage, column auto-detection.
- **Cost:** $0

### 6. Opendatasoft Portal — Vancouver
- **Level:** Municipal (Vancouver)
- **Connector:** `app/connectors/opendatasoft.py`
- **Access:** Explore API v2.1 CSV export
- **Licence:** Open Government Licence – City of Vancouver. Free.
- **Provides:** Business name, address, business type/subtype, issued date, status.
  ~60,000+ business licences.
- **Cost:** $0

### 7. YellowPages.ca (Supplementary)
- **Level:** National directory
- **Connector:** `app/connectors/yellowpages_scraper.py`
- **Access:** Public website, robots.txt-compliant scraping.
- **Licence:** Public directory listings. Scraping is rate-limited and
  respects robots.txt. Used only as supplementary enrichment.
- **Provides:** Business name, phone, address, website, industry category.
- **Limitations:** Anti-bot protection may block requests. Industry inferred
  from search query. Less reliable than government sources. Supplementary only.
- **Cost:** $0

### 8. Company Website Enrichment (Decision-Maker Contacts)
- **Level:** Per-business
- **Connector:** `app/pipeline/enrichment.py`
- **Access:** Business's own public website (/about, /team, /contact pages).
  Checks robots.txt before fetching.
- **Provides:** Names, titles, emails, phone numbers for owners, GMs, IT
  managers, and other publicly-listed roles.
- **Limitations:** Coverage depends on whether the business publishes a
  team/about page. Heuristic extraction (regex), not NLP.
- **Cost:** $0

## Documented but NOT Implemented

### LinkedIn
Richest source of decision-maker data, but Terms of Service prohibit automated
scraping. Official APIs (Sales Navigator) are paid. **Not built per cost requirement.**

### Provincial Registries Without Open-Data Feeds
Ontario's full Business Registry, BC's formal registry (beyond OrgBook),
Quebec's REQ — expose search-only web interfaces. Suitable for targeted
single-record lookups during refresh, not bulk collection.

### Paid Data Providers
Apollo, ZoomInfo, Data Axle, Dun & Bradstreet — explicitly excluded per brief.
Would fill the biggest gap (verified employee counts, direct-dial contacts).

## Summary

| Source | Level | Free? | Implemented? | Key Gap It Fills |
|---|---|---|---|---|
| Corporations Canada (CSV) | Federal | ✅ | ✅ | Legal identity, address, status |
| Corporations Canada (API) | Federal | ✅ | ✅ | Director/officer names |
| BC OrgBook | Provincial | ✅ | ✅ | BC corporate registry, new-biz detection |
| CKAN Portals (10 configs) | Prov/Municipal | ✅ | ✅ | Licensed businesses across Canada |
| Socrata Portals (3 configs) | Municipal | ✅ | ✅ | AB/MB municipal licences |
| Opendatasoft (Vancouver) | Municipal | ✅ | ✅ | Vancouver business licences |
| YellowPages.ca | National | ✅ | ✅ | Phone, website, industry supplementation |
| Website Enrichment | Per-business | ✅ | ✅ | Decision-maker contacts |
| LinkedIn | Cross-cutting | ❌ (ToS) | ❌ | Best decision-maker data |
| Paid providers | Cross-cutting | ❌ | ❌ | Verified headcounts, direct dials |
