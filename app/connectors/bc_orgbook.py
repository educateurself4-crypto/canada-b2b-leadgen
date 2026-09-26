"""
BC OrgBook (orgbook.gov.bc.ca) — British Columbia corporate registry.

Publisher:  Government of British Columbia
API:        OrgBook BC REST API (Aries VCR Indy Catalyst)
Docs:       https://bcgov.github.io/orgbook-bc-api-docs/
Base URL:   https://orgbook.gov.bc.ca/api/v4/
Licence:    Access Only (BC Government Terms) — free, public, no API key.
Coverage:   500,000+ active BC-registered organizations: corporations, societies,
            cooperatives, extraprovincial companies, sole proprietors, partnerships.
Provides:   Legal name, DBA/assumed names, BC registration number, entity type,
            entity status (active/historical), registration date.
Limitations:
  - No address, phone, email, employee count, or industry/NAICS.
  - Good for establishing legal identity + status + registration date;
    address/contact enrichment must come from other sources.
  - API returns JSON, paginated (max 100 per page).
"""
import time
from datetime import datetime, timedelta, timezone
from typing import Iterator, Optional

from app.connectors.base import BaseConnector, RawBusinessRecord
from app.logging_config import get_logger

logger = get_logger(__name__)

API_BASE = "https://orgbook.gov.bc.ca/api/v4"

# Map OrgBook entity status values to our status enum
STATUS_MAP = {
    "ACT": "active",
    "HIS": "dissolved",
    "active": "active",
    "historical": "dissolved",
}

# Map OrgBook entity types to a human-readable industry hint
ENTITY_TYPE_MAP = {
    "BC": "BC Company",
    "S": "BC Society",
    "CP": "BC Cooperative",
    "SP": "BC Sole Proprietorship",
    "GP": "BC General Partnership",
    "LP": "BC Limited Partnership",
    "XCP": "Extraprovincial Cooperative",
    "XS": "Extraprovincial Society",
    "A": "Extraprovincial Company",
    "LLC": "Limited Liability Company",
    "XP": "Extraprovincial Limited Partnership",
}


class BCOrgBookConnector(BaseConnector):
    """Paginated connector for BC OrgBook API v4.

    Fetches organizations in pages of 100. Supports optional date-range
    filtering to detect newly registered businesses.
    """
    source_name = "bc_orgbook"
    source_kind = "provincial_registry"

    def fetch(
        self,
        page_size: int = 100,
        max_pages: int = 50,
        registered_after: Optional[str] = None,
        **kwargs,
    ) -> Iterator[RawBusinessRecord]:
        """Yield BC organizations from OrgBook API.

        Args:
            page_size: Number of results per API page (max 100).
            max_pages: Safety cap on pages to fetch per run.
            registered_after: ISO date string (YYYY-MM-DD) — only return
                organizations registered on or after this date. Useful for
                new-business detection.
        """
        page = 1
        total_yielded = 0

        while page <= max_pages:
            params = {
                "page_size": min(page_size, 100),
                "page": page,
                "inactive": "false",  # only active orgs by default
                "revoked": "false",
            }

            url = f"{API_BASE}/search/topic"
            logger.info("[bc_orgbook] Fetching page %d: %s", page, url)

            try:
                resp = self._get(url, params=params)
                data = resp.json()
            except Exception as exc:
                logger.error("[bc_orgbook] Failed to fetch page %d: %s", page, exc)
                return

            results = data.get("results", [])
            if not results:
                logger.info("[bc_orgbook] No more results at page %d, done.", page)
                return

            for item in results:
                try:
                    record = self._parse_topic(item)
                    if record is None:
                        continue

                    # Date filter (client-side) if specified
                    if registered_after and record.incorporation_date:
                        try:
                            inc = datetime.fromisoformat(str(record.incorporation_date))
                            cutoff = datetime.fromisoformat(registered_after)
                            if inc < cutoff:
                                continue
                        except (ValueError, TypeError):
                            pass

                    total_yielded += 1
                    yield record
                except Exception as exc:
                    logger.warning("[bc_orgbook] Failed to parse topic: %s", exc)
                    continue

            # Check if there are more pages
            total_available = data.get("total", 0)
            if page * page_size >= total_available:
                logger.info(
                    "[bc_orgbook] Reached end of results (%d total). Yielded %d.",
                    total_available, total_yielded,
                )
                return

            page += 1

        logger.info("[bc_orgbook] Reached max_pages=%d. Yielded %d.", max_pages, total_yielded)

    def _parse_topic(self, topic: dict) -> Optional[RawBusinessRecord]:
        """Parse a single OrgBook topic (organization) into a RawBusinessRecord."""
        names = topic.get("names", [])
        if not names:
            return None

        # First name with type "entity_name" is the legal name
        legal_name = None
        operating_name = None
        for name_entry in names:
            name_type = name_entry.get("type", "")
            text = (name_entry.get("text") or "").strip()
            if not text:
                continue
            if name_type == "entity_name" and not legal_name:
                legal_name = text
            elif name_type in ("assumed_name", "trade_name", "doing_business_as"):
                operating_name = text

        if not legal_name:
            # Fallback: use first available name
            legal_name = names[0].get("text", "").strip()
            if not legal_name:
                return None

        # Source ID for dedup
        source_id = topic.get("source_id", "")

        # Status
        raw_status = (topic.get("inactive") or False)
        status = "dissolved" if raw_status else "active"

        # Entity type
        entity_type = topic.get("type", "")
        industry_hint = ENTITY_TYPE_MAP.get(entity_type, entity_type)

        # Registration date (from the earliest credential effective_date)
        inc_date = None
        for attr in topic.get("attributes", []):
            if attr.get("type") in ("entity_status_effective", "registration_date", "effective_date"):
                val = attr.get("value", "")
                if val:
                    inc_date = val[:10]  # YYYY-MM-DD
                    break

        return RawBusinessRecord(
            legal_name=legal_name,
            operating_name=operating_name,
            province="BC",
            corporation_number=source_id or None,
            business_status=status,
            incorporation_date=inc_date,
            industry=industry_hint or None,
            source_name=self.source_name,
            source_kind=self.source_kind,
            source_url=f"https://orgbook.gov.bc.ca/entity/{source_id}" if source_id else API_BASE,
            confidence=0.85,
        )


class BCOrgBookNewBusinessConnector(BCOrgBookConnector):
    """Specialized connector that only fetches recently registered BC
    organizations — used for daily new-business detection."""
    source_name = "bc_orgbook_new"

    def fetch(self, days_back: int = 7, **kwargs) -> Iterator[RawBusinessRecord]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        logger.info("[bc_orgbook_new] Fetching organizations registered after %s", cutoff)
        yield from super().fetch(registered_after=cutoff, max_pages=100, **kwargs)
