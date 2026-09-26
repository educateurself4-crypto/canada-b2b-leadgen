"""CSV export used by the dashboard's "Export" button and the API.

Includes both business fields and any associated decision-maker contacts,
flattened into one row per business (comma-separated contacts).
"""
import csv
import io
from app.db import get_cursor

EXPORT_COLUMNS = [
    "legal_name", "operating_name", "province", "city", "address_line1",
    "postal_code", "website", "phone", "email", "industry", "naics_code",
    "size_category", "size_confidence", "business_status",
    "incorporation_date", "quality_score", "lead_ready",
    "first_seen_at", "last_verified_at",
    # Contact columns (flattened)
    "decision_makers", "contact_emails", "contact_phones",
]


def export_businesses_csv(filters: dict) -> str:
    """filters: dict of column -> value (all optional). Returns CSV text.

    Every export automatically excludes do_not_call=TRUE businesses —
    this is enforced here at the data layer, not just in the UI, so
    any integration path (API, scheduled file, CRM import) respects it.
    """
    where_clauses, params = [], []

    if filters.get("search"):
        where_clauses.append("(b.legal_name ILIKE %s OR b.operating_name ILIKE %s)")
        params.extend([f"%{filters['search']}%", f"%{filters['search']}%"])

    if filters.get("province"):
        where_clauses.append("b.province = %s")
        params.append(filters["province"])
    if filters.get("city"):
        where_clauses.append("b.city ILIKE %s")
        params.append(f"%{filters['city']}%")
    if filters.get("industry"):
        where_clauses.append("b.industry ILIKE %s")
        params.append(f"%{filters['industry']}%")
    if filters.get("size_category"):
        where_clauses.append("b.size_category = %s")
        params.append(filters["size_category"])

    if filters.get("min_quality_score"):
        where_clauses.append("b.quality_score >= %s")
        params.append(filters["min_quality_score"])
    if filters.get("phone_available"):
        where_clauses.append("b.phone IS NOT NULL")
    if filters.get("email_available"):
        where_clauses.append("b.email IS NOT NULL")
    if filters.get("new_only"):
        where_clauses.append(
            "b.id IN (SELECT business_id FROM new_business_events WHERE event_type IN ('new_today','new_7d','new_30d'))"
        )
    if filters.get("decision_maker_available"):
        where_clauses.append("b.id IN (SELECT business_id FROM contacts WHERE is_active)")

    # Do-not-call records must NEVER be exported for calling campaigns
    where_clauses.append("b.do_not_call = FALSE")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with get_cursor() as (cur, conn):
        # Main business query
        cur.execute(
            f"""SELECT b.id, b.legal_name, b.operating_name, b.province, b.city,
                       b.address_line1, b.postal_code, b.website, b.phone, b.email,
                       b.industry, b.naics_code, b.size_category, b.size_confidence,
                       b.business_status, b.incorporation_date, b.quality_score,
                       b.lead_ready, b.first_seen_at, b.last_verified_at
                FROM businesses b {where_sql}
                ORDER BY b.quality_score DESC""",
            params,
        )
        rows = cur.fetchall()

        # Batch-fetch contacts for all exported businesses
        if rows:
            business_ids = [r["id"] for r in rows]
            placeholders = ",".join(["%s"] * len(business_ids))
            cur.execute(
                f"""SELECT business_id, full_name, title_raw, role_category, email, phone
                    FROM contacts
                    WHERE business_id IN ({placeholders}) AND is_active
                    ORDER BY business_id, confidence DESC""",
                business_ids,
            )
            contacts_raw = cur.fetchall()
        else:
            contacts_raw = []

    # Group contacts by business_id
    contacts_by_biz = {}
    for c in contacts_raw:
        bid = c["business_id"]
        contacts_by_biz.setdefault(bid, []).append(c)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()

    for row in rows:
        biz_contacts = contacts_by_biz.get(row["id"], [])

        # Flatten contacts into comma-separated strings
        dm_names = "; ".join(
            f"{c['full_name'] or c['title_raw']} ({c['role_category']})"
            for c in biz_contacts if c.get("full_name") or c.get("title_raw")
        )
        dm_emails = "; ".join(c["email"] for c in biz_contacts if c.get("email"))
        dm_phones = "; ".join(c["phone"] for c in biz_contacts if c.get("phone"))

        writer.writerow({
            "legal_name": row["legal_name"],
            "operating_name": row["operating_name"],
            "province": row["province"],
            "city": row["city"],
            "address_line1": row["address_line1"],
            "postal_code": row["postal_code"],
            "website": row["website"],
            "phone": row["phone"],
            "email": row["email"],
            "industry": row["industry"],
            "naics_code": row["naics_code"],
            "size_category": row["size_category"],
            "size_confidence": row["size_confidence"],
            "business_status": row["business_status"],
            "incorporation_date": row["incorporation_date"],
            "quality_score": row["quality_score"],
            "lead_ready": row["lead_ready"],
            "first_seen_at": row["first_seen_at"],
            "last_verified_at": row["last_verified_at"],
            "decision_makers": dm_names,
            "contact_emails": dm_emails,
            "contact_phones": dm_phones,
        })

    return buf.getvalue()
