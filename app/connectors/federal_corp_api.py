"""
Federal Corporation detail enrichment via the ISED Corporations Canada API.

Publisher:  Innovation, Science and Economic Development Canada (ISED)
API:        https://apigateway-passerelledapi.ised-isde.canada.ca/corporations/api/v1/
Docs:       https://ised-isde.canada.ca/site/api-catalogue/en
Licence:    Open Government Licence – Canada (free, commercial use, attribution required)
Coverage:   Individual corporation lookups by corporation number or BN9.
Provides:   Directors/officers (names, addresses), registered office address,
            detailed status, governing act, annual return status.
Limitations:
  - Single-record lookup only — no bulk endpoint. Must be used for
    targeted enrichment of businesses already in the database.
  - Rate limited — respect delays between requests.
  - Not all corps have director names publicly accessible.
Cost:       $0

This connector is NOT used for initial bulk collection (that's the CSV connector).
It's used by the enrichment pipeline to look up director/officer names for
businesses we already have, adding them as contacts.
"""
import re
from typing import Optional

from app.connectors.base import BaseConnector
from app.db import get_cursor
from app.logging_config import get_logger

logger = get_logger(__name__)

API_BASE = "https://apigateway-passerelledapi.ised-isde.canada.ca/corporations/api/v1"

# Map raw titles to our contact_role enum
TITLE_ROLE_MAP = {
    "president": "president",
    "director": "other_decision_maker",
    "secretary": "other_decision_maker",
    "treasurer": "other_decision_maker",
    "vice-president": "other_decision_maker",
    "vp": "other_decision_maker",
    "ceo": "president",
    "chief executive officer": "president",
    "managing director": "general_manager",
    "general manager": "general_manager",
    "founder": "founder",
    "owner": "owner",
    "officer": "other_decision_maker",
}


def _classify_title(title_raw: str) -> str:
    """Map a raw director/officer title to our contact_role enum."""
    if not title_raw:
        return "other_decision_maker"
    t = title_raw.lower().strip()
    for keyword, role in TITLE_ROLE_MAP.items():
        if keyword in t:
            return role
    return "other_decision_maker"


class FederalCorpAPIEnrichment(BaseConnector):
    """Targeted enrichment: looks up a specific federal corporation by
    its corporation number or BN9 to retrieve director/officer names
    and adds them as contacts."""
    source_name = "corporations_canada_api"
    source_kind = "federal_registry"

    def fetch(self, **kwargs):
        # This connector is not used for bulk fetching
        yield from []

    def enrich_corporation(self, corp_number: str) -> list:
        """Look up a single corporation by number and return a list of
        contact dicts ready to be inserted into the contacts table."""
        if not corp_number:
            return []

        # Clean the corp number (remove any non-numeric chars)
        clean_num = re.sub(r"[^0-9]", "", corp_number)
        if not clean_num:
            return []

        url = f"{API_BASE}/corporations/{clean_num}.json"
        try:
            resp = self._get(url)
            data = resp.json()
        except Exception as exc:
            logger.debug("Federal API lookup failed for %s: %s", corp_number, exc)
            return []

        corp_data = data.get("corporation", data)
        directors = corp_data.get("directors", [])

        contacts = []
        for d in directors:
            first = (d.get("firstName") or d.get("first_name") or "").strip()
            middle = (d.get("middleName") or d.get("middle_name") or "").strip()
            last = (d.get("lastName") or d.get("last_name") or "").strip()
            title_raw = (d.get("title") or d.get("officer_type") or "Director").strip()

            full_name = " ".join(part for part in [first, middle, last] if part)
            if not full_name:
                continue

            contacts.append({
                "full_name": full_name,
                "title_raw": title_raw,
                "role_category": _classify_title(title_raw),
                "email": None,
                "phone": None,
                "source_url": f"https://www.ic.gc.ca/app/scr/cc/CorporationsCanada/fdrlCrpDtls.html?corpId={clean_num}",
                "confidence": 0.8,
            })

        return contacts

    def enrich_batch(self, limit: int = 50):
        """Look up directors for federal corporations in our database that
        don't have contacts yet. Bounded by `limit` to avoid hammering."""
        with get_cursor() as (cur, conn):
            cur.execute(
                """
                SELECT id, corporation_number FROM businesses
                WHERE corporation_number IS NOT NULL
                  AND id NOT IN (
                      SELECT DISTINCT business_id FROM contacts
                      WHERE source_name = 'corporations_canada_api'
                  )
                ORDER BY quality_score DESC
                LIMIT %s
                """,
                (limit,),
            )
            targets = cur.fetchall()

        enriched = 0
        for row in targets:
            contacts = self.enrich_corporation(row["corporation_number"])
            if not contacts:
                continue

            with get_cursor() as (cur, conn):
                for c in contacts:
                    cur.execute(
                        """
                        INSERT INTO contacts (business_id, full_name, title_raw,
                                              role_category, email, phone,
                                              source_name, source_url, confidence)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            row["id"], c["full_name"], c["title_raw"],
                            c["role_category"], c["email"], c["phone"],
                            self.source_name, c["source_url"], c["confidence"],
                        ),
                    )
                enriched += 1

        logger.info(
            "[federal_api_enrichment] Enriched %d/%d corporations with director info",
            enriched, len(targets),
        )
        return enriched
