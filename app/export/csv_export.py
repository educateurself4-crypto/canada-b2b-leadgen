"""CSV export used by the dashboard's "Export selected" button."""
import csv
import io
from app.db import get_cursor

EXPORT_COLUMNS = [
    "legal_name", "operating_name", "province", "city", "address_line1",
    "postal_code", "website", "phone", "email", "industry", "naics_code",
    "size_category", "size_confidence", "business_status",
    "incorporation_date", "quality_score", "lead_ready", "do_not_call",
    "first_seen_at", "last_verified_at",
]


def export_businesses_csv(filters: dict) -> str:
    """filters: dict of column -> value (all optional). Returns CSV text."""
    where_clauses, params = [], []

    if filters.get("search"):
        where_clauses.append("(legal_name ILIKE %s OR operating_name ILIKE %s)")
        params.extend([f"%{filters['search']}%", f"%{filters['search']}%"])

    if filters.get("province"):
        where_clauses.append("province ILIKE %s")
        params.append(f"%{filters['province']}%")
    if filters.get("city"):
        where_clauses.append("city ILIKE %s")
        params.append(f"%{filters['city']}%")
    if filters.get("industry"):
        where_clauses.append("industry ILIKE %s")
        params.append(f"%{filters['industry']}%")
    if filters.get("size_category"):
        where_clauses.append("size_category = %s")
        params.append(filters["size_category"])

    if filters.get("min_quality_score"):
        where_clauses.append("quality_score >= %s")
        params.append(filters["min_quality_score"])
    if filters.get("phone_available"):
        where_clauses.append("phone IS NOT NULL")
    if filters.get("email_available"):
        where_clauses.append("email IS NOT NULL")
    if filters.get("new_only"):
        where_clauses.append(
            "id IN (SELECT business_id FROM new_business_events WHERE event_type IN ('new_today','new_7d','new_30d'))"
        )
    if filters.get("decision_maker_available"):
        where_clauses.append("id IN (SELECT business_id FROM contacts WHERE is_active)")
    # Suppressed numbers must never be exported for calling campaigns.
    where_clauses.append("do_not_call = FALSE")

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    with get_cursor() as (cur, conn):
        cur.execute(f"SELECT {', '.join(EXPORT_COLUMNS)} FROM businesses {where_sql} ORDER BY quality_score DESC", params)
        rows = cur.fetchall()

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue()
