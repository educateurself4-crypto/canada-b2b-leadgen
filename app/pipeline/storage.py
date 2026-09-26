"""Upsert logic: given a normalized record + dedup match (or None), either
insert a new business or merge into an existing one WITHOUT blindly
overwriting fields — every field write also gets logged to
business_field_sources, and the businesses row is only updated when the
new source has confidence >= the field's currently-recorded confidence,
OR the field is currently empty.
"""
from app.pipeline import dedup
from app.logging_config import get_logger

logger = get_logger(__name__)

# Which businesses-table columns are eligible for the "don't overwrite a
# better source with a worse one" merge logic.
MERGE_FIELDS = [
    "legal_name", "operating_name", "province", "city", "address_line1",
    "postal_code", "website", "domain", "phone", "email", "industry",
    "naics_code", "corporation_number", "business_number",
    "incorporation_date", "business_status",
]


def _current_field_confidence(cur, business_id, field_name):
    cur.execute(
        """
        SELECT confidence FROM business_field_sources
        WHERE business_id = %s AND field_name = %s AND is_current_pick = TRUE
        LIMIT 1
        """,
        (business_id, field_name),
    )
    row = cur.fetchone()
    return row["confidence"] if row else None


def _write_field_source(cur, business_id, field_name, field_value, record):
    if field_value in (None, ""):
        return
    cur.execute(
        """
        UPDATE business_field_sources SET is_current_pick = FALSE
        WHERE business_id = %s AND field_name = %s
        """,
        (business_id, field_name),
    )
    cur.execute(
        """
        INSERT INTO business_field_sources
            (business_id, field_name, field_value, source_name, source_kind,
             source_url, confidence, is_current_pick)
        VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
        """,
        (business_id, field_name, str(field_value), record["source_name"],
         record["source_kind"], record.get("source_url"), record["confidence"]),
    )


def insert_business(cur, record: dict) -> str:
    cur.execute(
        """
        INSERT INTO businesses (
            legal_name, operating_name, province, city, address_line1,
            postal_code, website, domain, phone, email, industry,
            naics_code, corporation_number, business_number,
            incorporation_date, business_status, last_verified_at
        ) VALUES (%(legal_name)s, %(operating_name)s, %(province)s, %(city)s,
            %(address_line1)s, %(postal_code)s, %(website)s, %(domain)s,
            %(phone)s, %(email)s, %(industry)s, %(naics_code)s,
            %(corporation_number)s, %(business_number)s,
            %(incorporation_date)s, %(business_status)s, now())
        RETURNING id
        """,
        record,
    )
    business_id = cur.fetchone()["id"]

    for field in MERGE_FIELDS:
        _write_field_source(cur, business_id, field, record.get(field), record)

    dedup.register_identifiers(cur, business_id, record)
    return business_id


def update_business(cur, business_id: str, record: dict) -> list:
    """Merge a new record into an existing business. Returns list of
    field names that actually changed (for change-detection events)."""
    changed_fields = []
    updates = {}

    for field in MERGE_FIELDS:
        new_value = record.get(field)
        if new_value in (None, ""):
            continue
        current_conf = _current_field_confidence(cur, business_id, field)
        if current_conf is None or record["confidence"] >= current_conf:
            cur.execute(f"SELECT {field} FROM businesses WHERE id = %s", (business_id,))
            existing_value = cur.fetchone()[field]
            if str(existing_value or "") != str(new_value):
                changed_fields.append(field)
                updates[field] = new_value
            _write_field_source(cur, business_id, field, new_value, record)

    if updates:
        set_clause = ", ".join(f"{k} = %({k})s" for k in updates)
        updates["id"] = business_id
        cur.execute(
            f"UPDATE businesses SET {set_clause}, last_updated_at = now() WHERE id = %(id)s",
            updates,
        )

    cur.execute("UPDATE businesses SET last_verified_at = now() WHERE id = %s", (business_id,))
    dedup.register_identifiers(cur, business_id, record)
    return changed_fields


def upsert_business(cur, record: dict):
    """Returns (business_id, is_new: bool, changed_fields: list)."""
    existing_id = dedup.find_existing_business(cur, record)
    if existing_id:
        changed = update_business(cur, existing_id, record)
        return existing_id, False, changed
    new_id = insert_business(cur, record)
    return new_id, True, []
