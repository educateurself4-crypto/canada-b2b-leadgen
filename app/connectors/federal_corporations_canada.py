"""
Federal source: Corporations Canada — Federal Corporations open dataset.

Publisher:  Innovation, Science and Economic Development Canada (ISED)
Dataset:    https://open.canada.ca/data/en/dataset/0032ce54-c5dd-4b66-99a0-320a7b5e99f2
Licence:    Open Government Licence – Canada (free, commercial use permitted,
            attribution required — see docs/SOURCES_REPORT.md)
Coverage:   ~640,000+ active & inactive federal corporations (CBCA business corporations,
            NFP Act / CCA-II not-for-profits, cooperatives, boards of trade).
"""
import csv
import io
import requests
from typing import Iterator, Optional

from app.connectors.base import BaseConnector, RawBusinessRecord
from app.logging_config import get_logger

logger = get_logger(__name__)

# Direct CSV endpoints published by ISED on open.canada.ca (via CloudFront CDN)
FEDERAL_CSV_ENDPOINTS = [
    ("Active Business Corporations (CBCA)", "https://d4bf66bykfyaf.cloudfront.net/corporations-active-cbca-en.csv"),
    ("Other Active Corporations (Non-CBCA)", "https://d4bf66bykfyaf.cloudfront.net/corporations-active-non-cbca-en.csv"),
]

STATUS_MAP = {
    "active": "active",
    "actif": "active",
    "dissolved": "dissolved",
    "dissoute": "dissolved",
    "amalgamated": "dissolved",
    "inactive": "inactive",
}


class FederalCorporationsCanadaConnector(BaseConnector):
    source_name = "corporations_canada_federal"
    source_kind = "federal_registry"

    def fetch(self, province_filter: Optional[str] = None, include_inactive: bool = False) -> Iterator[RawBusinessRecord]:
        endpoints = list(FEDERAL_CSV_ENDPOINTS)
        if include_inactive:
            endpoints.extend([
                ("Inactive Business Corporations", "https://d4bf66bykfyaf.cloudfront.net/corporations-inactive-or-dissolved-cbca-en.csv"),
                ("Other Inactive Corporations", "https://d4bf66bykfyaf.cloudfront.net/corporations-inactive-or-dissolved-non-cbca-en.csv"),
            ])

        for idx, (label, url) in enumerate(endpoints):
            logger.info("Downloading federal corporations CSV [%s]: %s", label, url)
            tmp_csv_path = f"/tmp/federal_corps_{idx}.csv"
            try:
                # Fast download to local file first so long DB inserts don't hold open HTTP connections
                with requests.get(url, stream=True, timeout=60) as r:
                    r.raise_for_status()
                    with open(tmp_csv_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)

                logger.info("Download finished for [%s]. Processing CSV records...", label)
                count = 0
                with open(tmp_csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        province = (row.get("Province/territory") or "").strip()
                        if province_filter and province and province.upper() != province_filter.upper():
                            continue

                        legal_name = (row.get("Corporate name - form 1") or row.get("Corporate name - form 2") or "").strip()
                        if not legal_name:
                            continue

                        raw_status = (row.get("Status") or "").strip().lower()
                        corp_num = (row.get("Corporation number") or "").strip()
                        bn = (row.get("Business number (BN)") or "").strip()
                        inc_date = (row.get("Anniversary date") or "").strip()

                        street1 = (row.get("Street") or "").strip()
                        street2 = (row.get("Street 2") or "").strip()
                        address = f"{street1} {street2}".strip() if street2 else street1

                        city = (row.get("City/town") or "").strip()
                        postal = (row.get("Postal code") or "").strip()

                        min_dir = (row.get("Minimum number of directors") or "").strip()
                        max_dir = (row.get("Maximum number of directors") or "").strip()
                        emp_min = int(min_dir) if min_dir.isdigit() else None
                        emp_max = int(max_dir) if max_dir.isdigit() else None

                        record = RawBusinessRecord(
                            legal_name=legal_name,
                            operating_name=None,
                            province=province,
                            city=city,
                            address_line1=address,
                            postal_code=postal,
                            corporation_number=corp_num or None,
                            business_number=bn or None,
                            incorporation_date=inc_date or None,
                            business_status=STATUS_MAP.get(raw_status, raw_status or "active"),
                            employee_count_min=emp_min,
                            employee_count_max=emp_max,
                            source_name=self.source_name,
                            source_kind=self.source_kind,
                            source_url=url,
                            confidence=0.9,
                        )
                        count += 1
                        yield record

                logger.info("Successfully processed %d records from [%s]", count, label)
            except Exception as exc:
                logger.error("Failed fetching/processing federal corporations [%s]: %s", label, exc)
            finally:
                import os
                if os.path.exists(tmp_csv_path):
                    try:
                        os.remove(tmp_csv_path)
                    except Exception:
                        pass

