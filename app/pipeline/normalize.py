"""Normalize raw connector output into clean, comparable values."""
import re
import phonenumbers
import tldextract
from app.connectors.base import RawBusinessRecord

PROVINCE_CODES = {
    "ALBERTA": "AB", "BRITISH COLUMBIA": "BC", "MANITOBA": "MB",
    "NEW BRUNSWICK": "NB", "NEWFOUNDLAND AND LABRADOR": "NL",
    "NOVA SCOTIA": "NS", "NORTHWEST TERRITORIES": "NT", "NUNAVUT": "NU",
    "ONTARIO": "ON", "PRINCE EDWARD ISLAND": "PE", "QUEBEC": "QC",
    "SASKATCHEWAN": "SK", "YUKON": "YT",
}


def normalize_province(value: str) -> str:
    if not value:
        return None
    v = value.strip().upper()
    if len(v) == 2:
        return v
    return PROVINCE_CODES.get(v, v[:2])


def normalize_postal_code(value: str) -> str:
    if not value:
        return None
    v = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    if len(v) == 6:
        return f"{v[:3]} {v[3:]}"
    return value.strip().upper() or None


def normalize_phone(value: str, default_region: str = "CA") -> str:
    if not value:
        return None
    try:
        parsed = phonenumbers.parse(value, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    return None


def normalize_domain(website: str) -> str:
    if not website:
        return None
    ext = tldextract.extract(website)
    if not ext.domain:
        return None
    return ".".join(part for part in [ext.domain, ext.suffix] if part).lower()


def normalize_name(value: str) -> str:
    if not value:
        return None
    v = re.sub(r"\s+", " ", value.strip())
    return v


def normalize_record(raw: RawBusinessRecord) -> dict:
    """Turn a RawBusinessRecord into a dict matching the `businesses` table
    columns (still un-deduped — that happens in dedup.py)."""
    return {
        "legal_name": normalize_name(raw.legal_name),
        "operating_name": normalize_name(raw.operating_name),
        "province": normalize_province(raw.province),
        "city": normalize_name(raw.city),
        "address_line1": normalize_name(raw.address_line1),
        "postal_code": normalize_postal_code(raw.postal_code),
        "website": raw.website.strip().lower() if raw.website else None,
        "domain": normalize_domain(raw.website),
        "phone": normalize_phone(raw.phone),
        "email": raw.email.strip().lower() if raw.email else None,
        "industry": normalize_name(raw.industry),
        "naics_code": raw.naics_code.strip() if raw.naics_code else None,
        "corporation_number": raw.corporation_number.strip() if raw.corporation_number else None,
        "business_number": raw.business_number.strip() if raw.business_number else None,
        "incorporation_date": raw.incorporation_date,
        "business_status": (raw.business_status or "unknown").lower(),
        "employee_count_min": raw.employee_count_min,
        "employee_count_max": raw.employee_count_max,
        "source_name": raw.source_name,
        "source_kind": raw.source_kind,
        "source_url": raw.source_url,
        "confidence": raw.confidence,
    }
