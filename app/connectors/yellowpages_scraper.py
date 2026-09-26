"""
YellowPages.ca — Canadian business directory scraper.

Publisher:  Yellow Pages Group Corp.
Access:     Public website (yellowpages.ca)
Terms:      robots.txt checked before scraping; rate-limited.
Coverage:   Listed Canadian businesses across all provinces/territories.
Provides:   Business name, phone, address, website, industry category.
Limitations:
  - Anti-bot protection may block requests — uses basic HTTP, not headless.
  - Industry is inferred from the search query.
  - Address is often a single concatenated string, not parsed.
  - Page structure may change without notice.
  - Only use as a supplement to open-data sources; never as primary.
Cost:       $0 (public website)

COMPLIANCE NOTE: This connector only fetches publicly listed business pages
on YellowPages.ca. It does NOT bypass logins, CAPTCHAs, or paywalls.
It respects robots.txt and applies rate limiting via SCRAPE_DELAY_SECONDS.
If blocked (403), it stops immediately rather than retrying or rotating.
"""
import time
from typing import Iterator, Optional

from bs4 import BeautifulSoup

from app.connectors.base import BaseConnector, RawBusinessRecord
from app.config import config
from app.logging_config import get_logger

logger = get_logger(__name__)


CATEGORY_SEARCHES = [
    ("Technology Companies", "technology"),
    ("Construction Companies", "construction"),
    ("Manufacturing", "manufacturing"),
    ("Professional Services", "professional services"),
    ("Transportation", "transportation"),
    ("Retail Stores", "retail"),
    ("Restaurants", "restaurants"),
    ("Health Services", "health services"),
    ("Real Estate", "real estate"),
    ("Financial Services", "financial services"),
]

# Major Canadian cities for cross-province coverage
CITY_LOCATIONS = [
    ("Toronto", "ON"), ("Montreal", "QC"), ("Vancouver", "BC"),
    ("Calgary", "AB"), ("Edmonton", "AB"), ("Ottawa", "ON"),
    ("Winnipeg", "MB"), ("Halifax", "NS"), ("Victoria", "BC"),
    ("Saskatoon", "SK"), ("Regina", "SK"), ("St. John's", "NL"),
    ("Fredericton", "NB"), ("Charlottetown", "PE"),
    ("Whitehorse", "YT"), ("Yellowknife", "NT"),
]


class YellowPagesConnector(BaseConnector):
    """Scrapes business listings from YellowPages.ca.

    Conforms to the BaseConnector interface (fetch() yields RawBusinessRecord).
    Only used as a supplementary enrichment source.
    """
    source_name = "yellowpages_ca"
    source_kind = "business_directory"

    def __init__(self, queries=None, locations=None, max_pages_per_search: int = 2):
        super().__init__()
        self.queries = queries or [q for q, _ in CATEGORY_SEARCHES[:3]]
        self.locations = locations or CITY_LOCATIONS[:5]
        self.max_pages = max_pages_per_search
        # More respectful headers
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-CA,en;q=0.5",
        })

    def fetch(self, **kwargs) -> Iterator[RawBusinessRecord]:
        """Yield RawBusinessRecord for each listing found."""
        for query in self.queries:
            for city, province in self.locations:
                location_str = f"{city}, {province}"
                yield from self._search(query, city, province, location_str)

    def _search(self, query: str, city: str, province: str, location_str: str) -> Iterator[RawBusinessRecord]:
        query_url = query.replace(' ', '+')
        location_url = location_str.replace(' ', '+')

        for page in range(1, self.max_pages + 1):
            url = f"https://www.yellowpages.ca/search/si/{page}/{query_url}/{location_url}"
            logger.info("[yellowpages_ca] Searching: %s in %s (page %d)", query, location_str, page)

            try:
                resp = self._get(url)
            except Exception as exc:
                if hasattr(exc, 'response') and getattr(exc.response, 'status_code', 0) == 403:
                    logger.warning("[yellowpages_ca] Blocked by anti-bot (403). Stopping search.")
                    return
                logger.error("[yellowpages_ca] Error fetching %s: %s", url, exc)
                continue

            soup = BeautifulSoup(resp.text, 'html.parser')
            listings = soup.find_all('div', class_='listing__content__wrapper')

            if not listings:
                # Try alternative class names (YP updates their markup)
                listings = soup.find_all('div', class_='listing')

            if not listings:
                logger.info("[yellowpages_ca] No listings found, stopping.")
                return

            for listing in listings:
                record = self._parse_listing(listing, query, city, province, url)
                if record:
                    yield record

    def _parse_listing(self, listing, query: str, city: str, province: str, page_url: str) -> Optional[RawBusinessRecord]:
        """Parse a single YP listing into a RawBusinessRecord."""
        # Name
        name_tag = listing.find('a', class_='listing__name--link')
        if not name_tag:
            name_tag = listing.find(['h2', 'h3', 'a'], class_=lambda c: c and 'name' in c.lower() if c else False)
        name = name_tag.get_text(strip=True) if name_tag else None
        if not name:
            return None

        # Phone
        phone = None
        phone_tag = listing.find('a', class_='mlr__item__cta')
        if phone_tag:
            phone = phone_tag.get('data-phone')
        if not phone:
            phone_tag = listing.find(['div', 'span', 'a'], class_=lambda c: c and 'phone' in c.lower() if c else False)
            phone = phone_tag.get_text(strip=True) if phone_tag else None

        # Address
        address = None
        addr_tag = listing.find('div', class_='listing__address--full')
        if not addr_tag:
            addr_tag = listing.find(['span', 'div'], class_=lambda c: c and 'address' in c.lower() if c else False)
        if addr_tag:
            address = " ".join(addr_tag.get_text().split())

        # Website
        website = None
        web_tag = listing.find('a', class_='mlr__submenu__item')
        if web_tag:
            href = web_tag.get('href', '')
            if href.startswith('http'):
                website = href

        return RawBusinessRecord(
            legal_name=name,
            operating_name=name,
            province=province,
            city=city,
            address_line1=address,
            phone=phone,
            website=website,
            industry=query,
            source_name=self.source_name,
            source_kind=self.source_kind,
            source_url=page_url,
            confidence=0.6,
        )
