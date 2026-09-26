"""Base class every source connector must implement.

A connector's only job is: fetch raw data from ONE permitted source and
yield normalized-ish dicts. It must NOT touch the database directly —
the orchestrator handles dedup/scoring/storage so every source goes
through the same pipeline.

Compliance contract for every connector:
  * Only call documented, public APIs / bulk downloads, or fetch pages
    that robots.txt permits.
  * Respect config.SCRAPE_DELAY_SECONDS between requests to the same host.
  * Never bypass logins, paywalls, CAPTCHAs or rate limits.
  * Always set source_name / source_kind / source_url on every record so
    provenance is preserved.
"""
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator, Optional
import requests
from app.config import config
from app.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class RawBusinessRecord:
    """Loosely-typed record a connector yields. Unknown fields are fine —
    normalize.py maps/cleans these into the businesses table shape."""
    legal_name: Optional[str] = None
    operating_name: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    address_line1: Optional[str] = None
    postal_code: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    industry: Optional[str] = None
    naics_code: Optional[str] = None
    corporation_number: Optional[str] = None
    business_number: Optional[str] = None
    incorporation_date: Optional[str] = None
    business_status: Optional[str] = None
    employee_count_min: Optional[int] = None
    employee_count_max: Optional[int] = None

    source_name: str = ""
    source_kind: str = "other"
    source_url: str = ""
    confidence: float = 0.6
    extra: dict = field(default_factory=dict)


class BaseConnector(ABC):
    source_name: str = "base"
    source_kind: str = "other"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT})

    def _get(self, url: str, **kwargs) -> requests.Response:
        resp = self.session.get(url, timeout=60, **kwargs)
        time.sleep(config.SCRAPE_DELAY_SECONDS)
        resp.raise_for_status()
        return resp

    @abstractmethod
    def fetch(self, **kwargs) -> Iterator[RawBusinessRecord]:
        """Yield RawBusinessRecord objects. Must be a generator so large
        sources (e.g. the 600k-row federal file) can stream instead of
        loading everything into memory."""
        raise NotImplementedError
