"""
Generic connector for Opendatasoft-based Canadian open-data portals.

The City of Vancouver (opendata.vancouver.ca) uses the Opendatasoft platform,
which provides a REST API (Explore API v2.1) with CSV export endpoints.

API used (documented, public, no key required for small-to-medium requests):
  GET {base}/api/explore/v2.1/catalog/datasets/{dataset_id}/exports/csv
      -> full dataset export as CSV

Licence: Open Government Licence – City of Vancouver (free, commercial use
permitted, attribution required — see docs/SOURCES_REPORT.md).
"""
import csv
import io
from dataclasses import dataclass
from typing import Iterator, Optional

from app.connectors.base import BaseConnector, RawBusinessRecord
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class OpendatasoftSourceConfig:
    key: str                  # internal source name
    base_url: str             # e.g. "https://opendata.vancouver.ca"
    dataset_id: str           # e.g. "business-licences"
    province: str             # 2-letter code
    source_kind: str = "municipal_open_data"
    field_map: Optional[dict] = None
    # Optional ODSQL filter applied server-side, e.g. "status='Issued'"
    where_filter: Optional[str] = None


DEFAULT_HEADER_HINTS = {
    "legal_name": ["legal name", "legal_name", "businessname", "company"],
    "operating_name": ["trade name", "tradename", "operating name", "dba",
                       "business name", "businesstradename"],
    "address_line1": ["address", "house", "street", "unit", "localarea"],
    "city": ["city", "municipality"],
    "postal_code": ["postal code", "postal_code", "postalcode"],
    "phone": ["phone", "telephone"],
    "email": ["email"],
    "website": ["website", "url"],
    "industry": ["business type", "category", "businesstype",
                 "businesssubtype", "type"],
    "naics_code": ["naics"],
    "incorporation_date": ["issueddate", "issued date", "folderyear",
                           "extractdate"],
    "business_status": ["status"],
}


class OpendatasoftConnector(BaseConnector):
    def __init__(self, source_cfg: OpendatasoftSourceConfig):
        super().__init__()
        self.cfg = source_cfg
        self.source_name = source_cfg.key
        self.source_kind = source_cfg.source_kind

    def _match_column(self, headers: list, our_field: str) -> Optional[str]:
        hints = (self.cfg.field_map or {}).get(our_field) or DEFAULT_HEADER_HINTS.get(our_field, [])
        headers_lower = {h.lower().strip(): h for h in headers}
        for hint in hints:
            for h_lower, h_original in headers_lower.items():
                if hint in h_lower:
                    return h_original
        return None

    def fetch(self, **kwargs) -> Iterator[RawBusinessRecord]:
        export_url = (
            f"{self.cfg.base_url}/api/explore/v2.1/catalog/datasets/"
            f"{self.cfg.dataset_id}/exports/csv"
        )
        params = {"delimiter": ",", "use_labels": "true"}
        if self.cfg.where_filter:
            params["where"] = self.cfg.where_filter

        logger.info("[%s] fetching CSV export: %s", self.cfg.key, export_url)

        try:
            resp = self._get(export_url, params=params)
        except Exception as exc:
            logger.error("[%s] failed to fetch export: %s", self.cfg.key, exc)
            return

        text = resp.content.decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []

        if not headers:
            logger.warning("[%s] empty CSV response", self.cfg.key)
            return

        col_map = {f: self._match_column(headers, f) for f in DEFAULT_HEADER_HINTS}
        logger.info("[%s] column mapping: %s", self.cfg.key,
                    {k: v for k, v in col_map.items() if v})

        for row in reader:
            def get(field_name):
                col = col_map.get(field_name)
                return row.get(col, "").strip() if col and row.get(col) else None

            yield RawBusinessRecord(
                legal_name=get("legal_name"),
                operating_name=get("operating_name"),
                province=self.cfg.province,
                city=get("city") or "Vancouver",
                address_line1=get("address_line1"),
                postal_code=get("postal_code"),
                phone=get("phone"),
                email=get("email"),
                website=get("website"),
                industry=get("industry"),
                naics_code=get("naics_code"),
                incorporation_date=get("incorporation_date"),
                business_status=self._normalize_status(get("business_status")),
                source_name=self.cfg.key,
                source_kind=self.cfg.source_kind,
                source_url=f"{self.cfg.base_url}/explore/dataset/{self.cfg.dataset_id}/",
                confidence=0.7,
            )

    def _normalize_status(self, raw_status: str) -> str:
        if not raw_status:
            return None
        s = raw_status.lower()
        if s in ("active", "issued", "valid", "open", "registered"):
            return "active"
        if s in ("inactive", "closed", "cancelled", "expired", "suspended"):
            return "inactive"
        if s in ("dissolved",):
            return "dissolved"
        return "unknown"

# ---------------------------------------------------------------------------
# SOURCE REGISTRY — add a new Opendatasoft-based source by adding one entry.
# ---------------------------------------------------------------------------
SOURCE_REGISTRY = [
    OpendatasoftSourceConfig(
        key="vancouver_business_licences",
        base_url="https://opendata.vancouver.ca",
        dataset_id="business-licences",
        province="BC",
        field_map={
            "operating_name": ["businessname", "business name", "tradename"],
            "address_line1": ["house", "street"],
            "industry": ["businesstype", "businesssubtype"],
            "incorporation_date": ["issueddate", "folderyear"],
            "business_status": ["status"],
        },
        where_filter="status='Issued'",
    ),
]
