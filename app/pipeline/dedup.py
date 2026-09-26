"""Deduplication: decide whether a normalized record matches an existing
business, or is a new one. Uses the business_identifiers table as an index
of cheap, exact keys first (fast path), then falls back to fuzzy name+city
matching (slow path) only when no exact key hits.

Priority order of match strength (first hit wins):
  1. corporation_number   (government-issued, near-certain)
  2. domain                (company website — strong signal)
  3. phone                 (normalized E.164 — strong signal)
  4. postal_code + normalized legal/operating name (good signal)
  5. fuzzy trigram match on name, same city/province, similarity >= 0.85
"""
from rapidfuzz import fuzz
from app.db import get_cursor
from app.logging_config import get_logger

logger = get_logger(__name__)

FUZZY_THRESHOLD = 87  # rapidfuzz token_sort_ratio, 0-100


def _lookup_by_key(cur, key_type: str, key_value: str):
    if not key_value:
        return None
    cur.execute(
        "SELECT business_id FROM business_identifiers WHERE key_type = %s AND key_value = %s LIMIT 1",
        (key_type, key_value),
    )
    row = cur.fetchone()
    return row["business_id"] if row else None


def _fuzzy_lookup(cur, name: str, city: str, province: str):
    if not name:
        return None
    cur.execute(
        """
        SELECT id, legal_name, operating_name
        FROM businesses
        WHERE province = %s AND city = %s
        LIMIT 500
        """,
        (province, city),
    )
    candidates = cur.fetchall()
    best_id, best_score = None, 0
    for c in candidates:
        for cand_name in (c["legal_name"], c["operating_name"]):
            if not cand_name:
                continue
            score = fuzz.token_sort_ratio(name.lower(), cand_name.lower())
            if score > best_score:
                best_score, best_id = score, c["id"]
    if best_score >= FUZZY_THRESHOLD:
        return best_id
    return None


def find_existing_business(cur, record: dict):
    """Returns an existing business_id if this record matches a known
    business, else None (meaning: create a new one)."""
    name_for_key = (record.get("legal_name") or record.get("operating_name") or "").strip().lower()
    postal_name_key = f"{record.get('postal_code','')}|{name_for_key}" if record.get("postal_code") else None

    for key_type, key_value in [
        ("corp_number", record.get("corporation_number")),
        ("domain", record.get("domain")),
        ("phone", record.get("phone")),
        ("postal_name", postal_name_key),
    ]:
        match = _lookup_by_key(cur, key_type, key_value)
        if match:
            return match

    return _fuzzy_lookup(cur, name_for_key, record.get("city"), record.get("province"))


def register_identifiers(cur, business_id: str, record: dict):
    """Insert any new dedup keys for this business (idempotent via UNIQUE
    constraint + ON CONFLICT DO NOTHING)."""
    name_for_key = (record.get("legal_name") or record.get("operating_name") or "").strip().lower()
    postal_name_key = f"{record.get('postal_code','')}|{name_for_key}" if record.get("postal_code") else None

    keys = [
        ("corp_number", record.get("corporation_number")),
        ("domain", record.get("domain")),
        ("phone", record.get("phone")),
        ("postal_name", postal_name_key),
        ("name_hash", name_for_key or None),
    ]
    for key_type, key_value in keys:
        if not key_value:
            continue
        cur.execute(
            """
            INSERT INTO business_identifiers (business_id, key_type, key_value)
            VALUES (%s, %s, %s)
            ON CONFLICT (key_type, key_value, business_id) DO NOTHING
            """,
            (business_id, key_type, key_value),
        )
