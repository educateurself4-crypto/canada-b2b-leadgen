"""
Generic connector for Socrata-based Canadian open-data portals.

Several major Canadian cities host their open data on the Socrata platform
(data.calgary.ca, data.edmonton.ca, data.winnipeg.ca, etc.) which exposes
datasets via the SODA (Socrata Open Data API) and CSV export endpoints.

Rather than one scraper per city, this connector is configured per-portal
via a small dataclass (see SOURCE_REGISTRY at the bottom) and reused for
every Socrata portal. New sources are added purely as config.

API used (documented, public, no key required):
  GET {base}/resource/{dataset_id}.csv?$limit=50000&$offset=0
      -> paginates through the full dataset as CSV rows

Licence: each portal publishes its own Open Government Licence variant
(Calgary / Edmonton / Winnipeg / etc.) — all permit reuse including for
commercial purposes with attribution. See docs/SOURCES_REPORT.md.
"""
import csv
import io
from dataclasses import dataclass, field
from typing import Iterator, Optional

from app.connectors.base import BaseConnector, RawBusinessRecord
from app.logging_config import get_logger

logger = get_logger(__name__)

# Socrata API enforces a max of 50k rows per request; we page through.
SOCRATA_PAGE_SIZE = 50000


@dataclass
class SocrataSourceConfig:
    key: str                  # internal source name, e.g. "calgary_business_licences"
    base_url: str             # e.g. "https://data.calgary.ca"
    dataset_id: str           # the Socrata 4x4 identifier, e.g. "ed4p-nj59"
    province: str             # 2-letter code this dataset covers
    source_kind: str = "municipal_open_data"
    field_map: Optional[dict] = None  # column -> our field names


# Default header hints — case-insensitive substring matching, same pattern
# as the CKAN connector so column auto-detection works across portals.
DEFAULT_HEADER_HINTS = {
    "legal_name": ["legal name", "legal_name", "company", "licencee"],
    "operating_name": ["trade name", "trading name", "tradename", "operating name",
                       "dba", "business name"],
    "address_line1": ["address", "street address", "location", "business_address",
                      "house_no", "street_name"],
    "city": ["city", "municipality", "community"],
    "postal_code": ["postal code", "postal_code", "postalcode"],
    "phone": ["phone", "telephone"],
    "email": ["email"],
    "website": ["website", "url"],
    "industry": ["business type", "category", "licence type", "license type",
                 "licencetype", "licence_type", "industry"],
    "naics_code": ["naics"],
    "incorporation_date": ["issued date", "start date", "date issued",
                           "issuedate", "licenceissuedate", "creation_date"],
    "business_status": ["status", "licence_status", "licencestatus"],
}


class SocrataOpenDataConnector(BaseConnector):
    def __init__(self, source_cfg: SocrataSourceConfig):
        super().__init__()
        self.cfg = source_cfg
        self.source_name = source_cfg.key
        self.source_kind = source_cfg.source_kind

    def _match_column(self, headers: list, our_field: str) -> Optional[str]:
        """Find which CSV column maps to one of our normalized field names."""
        hints = (self.cfg.field_map or {}).get(our_field) or DEFAULT_HEADER_HINTS.get(our_field, [])
        headers_lower = {h.lower().strip(): h for h in headers}
        for hint in hints:
            for h_lower, h_original in headers_lower.items():
                if hint in h_lower:
                    return h_original
        return None

    def fetch(self, **kwargs) -> Iterator[RawBusinessRecord]:
        offset = 0
        col_map = None

        while True:
            csv_url = (
                f"{self.cfg.base_url}/resource/{self.cfg.dataset_id}.csv"
                f"?$limit={SOCRATA_PAGE_SIZE}&$offset={offset}"
            )
            logger.info("[%s] fetching offset=%d: %s", self.cfg.key, offset, csv_url)

            try:
                resp = self._get(csv_url)
            except Exception as exc:
                logger.error("[%s] failed to fetch page at offset %d: %s",
                             self.cfg.key, offset, exc)
                return

            text = resp.content.decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(text))
            headers = reader.fieldnames or []

            if not headers:
                logger.warning("[%s] empty response at offset %d, stopping", self.cfg.key, offset)
                return

            # Build column map once from the first page's headers
            if col_map is None:
                col_map = {f: self._match_column(headers, f) for f in DEFAULT_HEADER_HINTS}
                logger.info("[%s] column mapping: %s", self.cfg.key,
                            {k: v for k, v in col_map.items() if v})

            row_count = 0
            for row in reader:
                row_count += 1

                def get(field_name):
                    col = col_map.get(field_name)
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
                    source_url=f"{self.cfg.base_url}/resource/{self.cfg.dataset_id}",
                    confidence=0.7,
                )

            # If fewer rows than page size, we've reached the end
            if row_count < SOCRATA_PAGE_SIZE:
                logger.info("[%s] last page (got %d rows), done", self.cfg.key, row_count)
                return

            offset += SOCRATA_PAGE_SIZE


# ---------------------------------------------------------------------------
# SOURCE REGISTRY — add a new Socrata-based source by adding one entry here.
# Verify each dataset_id (4x4 identifier) on the portal before production.
# ---------------------------------------------------------------------------
SOURCE_REGISTRY = [
    SocrataSourceConfig(
        key="calgary_business_licences",
        base_url="https://data.calgary.ca",
        dataset_id="ed4p-nj59",
        province="AB",
        field_map={
            "operating_name": ["tradename", "trade name"],
            "address_line1": ["address"],
            "industry": ["licencetype", "licence type"],
            "incorporation_date": ["licenceissuedate", "creation_date"],
            "business_status": ["licencestatus", "status"],
        },
    ),
    SocrataSourceConfig(
        key="edmonton_business_licences",
        base_url="https://data.edmonton.ca",
        dataset_id="qhi4-bdpu",
        province="AB",
        field_map={
            "operating_name": ["trade name", "trading name", "business name"],
            "address_line1": ["address", "location"],
            "industry": ["category", "business type"],
            "incorporation_date": ["issue date", "date issued"],
            "business_status": ["status"],
        },
    ),
    SocrataSourceConfig(
        key="winnipeg_business_licences",
        base_url="https://data.winnipeg.ca",
        dataset_id="vbya-nf3g",  # verify on portal — search "Business Licenses"
        province="MB",
        field_map={
            "operating_name": ["business name", "trade name"],
            "address_line1": ["address", "location"],
            "industry": ["licence type", "category"],
            "incorporation_date": ["issue date"],
            "business_status": ["status"],
        },
    ),
]
