"""Daily new-business detection: compares each freshly-collected record
against what we already know, and writes rows to new_business_events so
the dashboard / CRM can surface hot leads without re-deriving this logic.

Called once per orchestrator run, after storage.upsert_business for each
record (see orchestrator.py) — it inspects `is_new` / `changed_fields`
that upsert_business already computed and returns, and turns those into
the appropriate event rows.
"""
import json
from datetime import datetime, timedelta, timezone
from app.logging_config import get_logger

logger = get_logger(__name__)


def record_events(cur, business_id: str, is_new: bool, changed_fields: list, incorporation_date=None):
    if is_new:
        cur.execute(
            "INSERT INTO new_business_events (business_id, event_type, detail) VALUES (%s, 'new_today', %s)",
            (business_id, None),
        )
        # Also backfill 7d/30d windows based on incorporation_date if we have one,
        # so a business incorporated 3 days ago (but only just scraped today)
        # still shows correctly as "registered in the last 7 days".
        if incorporation_date:
            try:
                inc_date = incorporation_date if isinstance(incorporation_date, datetime) else \
                    datetime.fromisoformat(str(incorporation_date))
                age_days = (datetime.now(timezone.utc) - inc_date.replace(tzinfo=timezone.utc)).days
                if age_days <= 7:
                    cur.execute(
                        "INSERT INTO new_business_events (business_id, event_type) VALUES (%s, 'new_7d')",
                        (business_id,),
                    )
                if age_days <= 30:
                    cur.execute(
                        "INSERT INTO new_business_events (business_id, event_type) VALUES (%s, 'new_30d')",
                        (business_id,),
                    )
            except Exception:
                pass
        return

    if changed_fields:
        cur.execute(
            """
            INSERT INTO new_business_events (business_id, event_type, detail)
            VALUES (%s, 'recently_changed', %s::jsonb)
            """,
            (business_id, json.dumps({"changed_fields": changed_fields})),
        )


def rolling_window_counts(cur) -> dict:
    """Convenience aggregate for the dashboard home screen."""
    cur.execute(
        """
        SELECT event_type, count(*) AS n
        FROM new_business_events
        WHERE detected_at >= now() - interval '30 days'
        GROUP BY event_type
        """
    )
    return {row["event_type"]: row["n"] for row in cur.fetchall()}
