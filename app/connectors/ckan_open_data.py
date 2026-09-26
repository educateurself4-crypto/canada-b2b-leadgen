"""
Generic connector for CKAN-based Canadian open-data portals.

Most Canadian provincial and municipal open-data portals run on CKAN
(the same open-source platform, with a standard REST API at
/api/3/action/...). Confirmed CKAN portals include:

  * data.ontario.ca        (Ontario provincial open data — CKAN)
  * open.toronto.ca         (Toronto municipal open data — CKAN)
  * open.canada.ca          (Government of Canada open data — CKAN)
  * open.alberta.ca         (Alberta provincial open data — CKAN)
  * opendata.vancouver.ca   (Vancouver municipal open data — CKAN)
  * ... and most other major municipalities/provinces.

Rather than writing one bespoke scraper per city/province, this connector
is configured per-portal via a small dict (see SOURCE_REGISTRY at the
bottom), and reused for every CKAN portal. This is how the system scales
across "multiple provincial/local sources" and beyond, without new code
per city — new sources are added purely as config (see
docs/ADDING_SOURCES.md).

Each configured entry points at ONE dataset (a "package" in CKAN terms)
that is relevant to business intelligence: business licence registries,
new-business open-data feeds, or similar. Not every city publishes this;
the registry is a starting set to extend.

API used (documented, public, no key required on any of the portals above):
  GET {base}/api/3/action/package_show?id={dataset_id}
      -> resolves the dataset to its downloadable resource URLs (CSV/JSON)
  GET {resource_url}
      -> the actual data file

Licence: each portal publishes its own Open Government Licence variant
(Canada / Ontario / Toronto / etc.) — all permit reuse including for
commercial purposes with attribution. See docs/SOURCES_REPORT.md.
"""
import csv
import io
from dataclasses import dataclass
from typing import Iterator, Optional

from app.connectors.base import BaseConnector, RawBusinessRecord
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class CkanSourceConfig:
    key: str                 # internal source name, e.g. "toronto_business_licences"
    base_url: str             # e.g. "https://open.toronto.ca"
    dataset_id: str           # the CKAN package/dataset id or slug
    province: str              # 2-letter code this dataset covers
    source_kind: str = "municipal_open_data"
    field_map: Optional[dict] = None   # CSV column -> our field names (see below)


# --- Default column mapping used when a portal's CSV headers are not yet
# known ahead of time. Override per-source via `field_map` once you've
# inspected the actual CSV (see docs/ADDING_SOURCES.md). Left permissive
# (case-insensitive substring match) so it degrades gracefully.
DEFAULT_HEADER_HINTS = {
    "legal_name": ["legal name", "legal_name", "company", "operator name"],
    "operating_name": ["trade name", "operating name", "dba", "business name"],
    "address_line1": ["address", "street address", "location"],
    "city": ["city", "municipality"],
    "postal_code": ["postal code", "postal_code"],
    "phone": ["phone", "telephone"],
    "email": ["email"],
    "website": ["website", "url"],
    "industry": ["business type", "category", "licence type", "license type"],
    "naics_code": ["naics"],
    "incorporation_date": ["issued date", "start date", "date issued"],
    "business_status": ["status"],
}


class CkanOpenDataConnector(BaseConnector):
    def __init__(self, source_cfg: CkanSourceConfig):
        super().__init__()
        self.cfg = source_cfg
        self.source_name = source_cfg.key
        self.source_kind = source_cfg.source_kind

    def _resolve_resource_urls(self) -> list:
        url = f"{self.cfg.base_url}/api/3/action/package_show"
        resp = self._get(url, params={"id": self.cfg.dataset_id})
        payload = resp.json()
        resources = payload.get("result", {}).get("resources", [])
        # Prefer CSV resources; fall back to anything downloadable.
        csv_urls = [r["url"] for r in resources if (r.get("format", "").lower() == "csv")]
        return csv_urls or [r["url"] for r in resources if r.get("url")]

    def _match_column(self, headers: list, field: str) -> Optional[str]:
        hints = (self.cfg.field_map or {}).get(field) or DEFAULT_HEADER_HINTS.get(field, [])
        headers_lower = {h.lower(): h for h in headers}
        for hint in hints:
            for h_lower, h_original in headers_lower.items():
                if hint in h_lower:
                    return h_original
        return None

    def fetch(self, **kwargs) -> Iterator[RawBusinessRecord]:
        try:
            resource_urls = self._resolve_resource_urls()
        except Exception as exc:
            logger.error("[%s] failed to resolve dataset resources: %s", self.cfg.key, exc)
            return

        for resource_url in resource_urls:
            logger.info("[%s] fetching resource: %s", self.cfg.key, resource_url)
            try:
                resp = self._get(resource_url)
            except Exception as exc:
                logger.error("[%s] failed to fetch resource %s: %s", self.cfg.key, resource_url, exc)
                continue

            try:
                text = resp.content.decode("utf-8-sig", errors="replace")
                reader = csv.DictReader(io.StringIO(text))
                headers = reader.fieldnames or []
                col_map = {f: self._match_column(headers, f) for f in DEFAULT_HEADER_HINTS}

                for row in reader:
                    def get(field):
                        col = col_map.get(field)
                        return row.get(col, "").strip() if col and row.get(col) else None

                    yield RawBusinessRecord(
                        legal_name=get("legal_name"),
                        operating_name=get("operating_name"),
                        province=self.cfg.province,
                        city=get("city"),
                        address_line1=get("address_line1"),
                        postal_code=get("postal_code"),
                        phone=get("phone"),
                        email=get("email"),
                        website=get("website"),
                        industry=get("industry"),
                        naics_code=get("naics_code"),
                        incorporation_date=get("incorporation_date"),
                        business_status=get("business_status"),
                        source_name=self.cfg.key,
                        source_kind=self.cfg.source_kind,
                        source_url=resource_url,
                        confidence=0.7,
                    )
            except Exception as exc:
                logger.error("[%s] failed to parse resource %s: %s", self.cfg.key, resource_url, exc)
                continue


# ---------------------------------------------------------------------------
# SOURCE REGISTRY — add a new provincial/municipal source by adding one
# entry here (no new code needed for any CKAN-based portal).
# Verify each dataset_id against the live portal before first production run
# (see docs/ADDING_SOURCES.md for the verification checklist).
# ---------------------------------------------------------------------------
SOURCE_REGISTRY = [
    CkanSourceConfig(
        key="ontario_licensed_businesses",
        base_url="https://data.ontario.ca",
        dataset_id="select-licence-and-registration-data",  # verify slug on portal
        province="ON",
        source_kind="provincial_registry",
    ),
    CkanSourceConfig(
        key="toronto_business_licences",
        base_url="https://ckan0.cf.opendata.inter.prod-toronto.ca",
        dataset_id="municipal-licensing-and-standards-business-licences-and-permits",
        province="ON",
    ),
    CkanSourceConfig(
        key="alberta_licensed_businesses",
        base_url="https://open.alberta.ca",
        dataset_id="licensed-businesses-charities-and-fundraisers",
        province="AB",
        source_kind="provincial_registry",
    ),
    CkanSourceConfig(
        key="montreal_commercial_establishments",
        base_url="https://donnees.montreal.ca",
        dataset_id="etablissements-alimentaires",
        province="QC",
        field_map={
            "legal_name": ["nom_etablissement", "establishment name", "name"],
            "operating_name": ["dba", "trade name"],
            "address_line1": ["adresse", "address"],
            "city": ["ville", "city"],
            "postal_code": ["code_postal", "postal code"],
        },
    ),
    CkanSourceConfig(
        key="montreal_locaux_commerciaux",
        base_url="https://donnees.montreal.ca",
        dataset_id="locaux-commerciaux",
        province="QC",
        field_map={
            "legal_name": ["nom_entreprise", "company", "nom"],
            "operating_name": ["enseigne", "trade name"],
            "address_line1": ["adresse", "address", "suite_adresse"],
            "city": ["ville", "city"],
            "industry": ["type_usage", "categorie", "category"],
        },
    ),
]

