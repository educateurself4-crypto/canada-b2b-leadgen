"""Contact / decision-maker enrichment from a business's OWN public website.

Scope and compliance boundaries (read before extending this module):
  * This module only fetches pages that belong to the business itself
    (its own domain) — e.g. /about, /team, /contact, /leadership,
    /our-team, /staff. These are pages the business has chosen to
    publish publicly for exactly this purpose (being found/contacted).
  * It checks robots.txt for the target domain before fetching anything
    and skips the domain entirely if disallowed.
  * It does NOT scrape LinkedIn, Facebook, or other third-party platforms
    — those have contractual anti-scraping terms and generally require
    their official (often paid) APIs. This is intentionally left as a
    documented gap (see docs/SOURCES_REPORT.md) rather than worked
    around, per the compliance requirement to respect access controls
    and terms of service.
  * It never attempts logins, CAPTCHA solving, or any access-control
    bypass.
  * Every contact found is tagged with source_url = the exact page it
    came from, so the call-centre team can verify context before using
    it.

Extraction approach: lightweight heuristics (regex + keyword proximity),
not a general NLP model — the trial's goal is to prove the pipeline shape;
swapping in a stronger extractor (e.g. a small local NER model) is a drop-
in replacement for `_extract_contacts_from_html` without redesigning the
architecture.
"""
import re
import urllib.robotparser as robotparser
from urllib.parse import urljoin, urlparse

from app.connectors.base import BaseConnector
from app.logging_config import get_logger

logger = get_logger(__name__)

CANDIDATE_PATHS = [
    "/about", "/about-us", "/team", "/our-team", "/leadership",
    "/contact", "/contact-us", "/staff", "/management",
]

TITLE_ROLE_MAP = {
    "owner": "owner", "founder": "founder", "co-founder": "founder",
    "president": "president", "general manager": "general_manager",
    "gm": "general_manager", "office manager": "office_manager",
    "operations manager": "operations_manager", "ops manager": "operations_manager",
    "it manager": "it_manager", "it director": "it_director",
    "director of it": "it_director", "procurement": "procurement",
    "purchasing manager": "procurement",
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}")


_robots_cache: dict[str, robotparser.RobotFileParser | None] = {}


def _robots_allows(session, domain: str, path: str) -> bool:
    if domain not in _robots_cache:
        rp = robotparser.RobotFileParser()
        try:
            rp.set_url(f"https://{domain}/robots.txt")
            rp.read()
            _robots_cache[domain] = rp
        except Exception:
            # If robots.txt is unreachable/unparseable, cache None so we
            # don't retry on every path. Default to allow (conservative
            # for the small, generally-public candidate paths above).
            _robots_cache[domain] = None

    rp = _robots_cache[domain]
    if rp is None:
        return True
    return rp.can_fetch(session.headers.get("User-Agent", "*"), path)


def _extract_contacts_from_html(html: str, page_url: str) -> list:
    contacts = []
    lower = html.lower()
    for phrase, role in TITLE_ROLE_MAP.items():
        idx = lower.find(phrase)
        if idx == -1:
            continue
        window = html[max(0, idx - 200): idx + 200]
        email_match = EMAIL_RE.search(window)
        phone_match = PHONE_RE.search(window)
        contacts.append({
            "title_raw": phrase,
            "role_category": role,
            "email": email_match.group(0).lower() if email_match else None,
            "phone": phone_match.group(0) if phone_match else None,
            "source_url": page_url,
            "confidence": 0.5,
        })
    return contacts


class WebsiteContactEnrichment(BaseConnector):
    source_name = "company_website_enrichment"
    source_kind = "company_website"

    def fetch(self, **kwargs):
        yield from []

    def enrich(self, website: str) -> list:
        if not website:
            return []
        parsed = urlparse(website if website.startswith("http") else f"https://{website}")
        domain = parsed.netloc or parsed.path
        results = []

        for path in CANDIDATE_PATHS:
            if not _robots_allows(self.session, domain, path):
                continue
            url = urljoin(f"https://{domain}", path)
            try:
                resp = self._get(url)
            except Exception:
                continue
            results.extend(_extract_contacts_from_html(resp.text, url))

        # de-dup within this single enrichment pass
        seen = set()
        deduped = []
        for c in results:
            key = (c.get("role_category"), c.get("email"))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(c)
        return deduped
