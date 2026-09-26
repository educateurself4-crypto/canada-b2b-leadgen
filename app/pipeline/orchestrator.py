"""Ties the whole pipeline together:
  collect -> normalize -> dedup/store -> classify size -> enrich contacts
  -> score -> log job run -> emit new-business events

Each stage is intentionally small and independently testable (see tests/).
"""
from datetime import datetime, timezone
from app.db import get_cursor
from app.pipeline import normalize, storage, scoring, new_business_detector
from app.pipeline.employee_classifier import classify as classify_size
from app.pipeline.enrichment import WebsiteContactEnrichment
from app.logging_config import get_logger

logger = get_logger(__name__)


def _log_job_start(cur, source_name, job_type):
    cur.execute(
        "INSERT INTO job_runs (source_name, job_type, status) VALUES (%s, %s, 'running') RETURNING id",
        (source_name, job_type),
    )
    return cur.fetchone()["id"]


def _log_job_finish(cur, job_id, status, collected, new, updated, errors, error_detail=None):
    cur.execute(
        """
        UPDATE job_runs SET status=%s, finished_at=now(), records_collected=%s,
            records_new=%s, records_updated=%s, errors_count=%s, error_detail=%s
        WHERE id=%s
        """,
        (status, collected, new, updated, errors, error_detail, job_id),
    )


def run_connector(connector, enrich_contacts: bool = True, **fetch_kwargs):
    """Runs one connector end-to-end: collect -> normalize -> store -> classify
    -> (optionally) enrich -> score -> log. Safe to call repeatedly/on a
    schedule; every record is upserted, not duplicated."""
    source_name = getattr(connector, "source_name", connector.__class__.__name__)

    with get_cursor() as (cur, conn):
        job_id = _log_job_start(cur, source_name, "collect")
    collected = new_count = updated_count = errors = 0

    try:
        for raw in connector.fetch(**fetch_kwargs):
            try:
                with get_cursor() as (cur, conn):
                    record = normalize.normalize_record(raw)
                    business_id, is_new, changed = storage.upsert_business(cur, record)
                    collected += 1
                    new_count += 1 if is_new else 0
                    updated_count += 1 if (not is_new and changed) else 0

                    size_cat, size_conf = classify_size(
                        record.get("employee_count_min"), record.get("employee_count_max")
                    )
                    if size_cat:
                        cur.execute(
                            "UPDATE businesses SET size_category=%s, size_confidence=%s WHERE id=%s",
                            (size_cat, size_conf, business_id),
                        )

                    new_business_detector.record_events(
                        cur, business_id, is_new, changed, record.get("incorporation_date")
                    )

                    _rescore(cur, business_id)
            except Exception as exc:
                errors += 1
                logger.exception("Failed to process record from %s: %s", source_name, exc)

        status = "success" if errors == 0 else "partial_failure"
    except Exception as exc:
        errors += 1
        status = "failed"
        logger.exception("Connector %s failed entirely: %s", source_name, exc)

    with get_cursor() as (cur, conn):
        _log_job_finish(cur, job_id, status, collected, new_count, updated_count, errors)

    logger.info(
        "[%s] collected=%d new=%d updated=%d errors=%d status=%s",
        source_name, collected, new_count, updated_count, errors, status,
    )

    if enrich_contacts:
        enrich_recent_websites(source_name)


def _rescore(cur, business_id):
    cur.execute("SELECT * FROM businesses WHERE id = %s", (business_id,))
    business = cur.fetchone()
    cur.execute("SELECT count(*) AS n FROM contacts WHERE business_id = %s AND is_active", (business_id,))
    contact_count = cur.fetchone()["n"]
    cur.execute(
        "SELECT count(DISTINCT source_name) AS n FROM business_field_sources WHERE business_id = %s",
        (business_id,),
    )
    source_count = cur.fetchone()["n"]
    days_since_verified = None
    if business.get("last_verified_at"):
        days_since_verified = (datetime.now(timezone.utc) - business["last_verified_at"]).days

    score, _breakdown = scoring.score_business(business, contact_count, source_count, days_since_verified)
    lead_ready = scoring.is_lead_ready(score)
    cur.execute(
        "UPDATE businesses SET quality_score=%s, lead_ready=%s WHERE id=%s",
        (score, lead_ready, business_id),
    )


def enrich_recent_websites(source_name: str, limit: int = 200):
    """Runs contact enrichment for businesses that have a website but no
    contacts yet. Kept as a bounded batch per call so a single pipeline run
    doesn't hammer hundreds of thousands of company sites at once."""
    enricher = WebsiteContactEnrichment()
    with get_cursor() as (cur, conn):
        cur.execute(
            """
            SELECT id, website FROM businesses
            WHERE website IS NOT NULL
              AND id NOT IN (SELECT DISTINCT business_id FROM contacts)
            ORDER BY last_updated_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        targets = cur.fetchall()

    for row in targets:
        try:
            contacts = enricher.enrich(row["website"])
        except Exception as exc:
            logger.warning("Enrichment failed for %s: %s", row["website"], exc)
            continue

        if not contacts:
            continue

        with get_cursor() as (cur, conn):
            for c in contacts:
                cur.execute(
                    """
                    INSERT INTO contacts (business_id, title_raw, role_category, email,
                                           phone, source_name, source_url, confidence)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (row["id"], c["title_raw"], c["role_category"], c.get("email"),
                     c.get("phone"), "company_website_enrichment", c["source_url"], c["confidence"]),
                )
            _rescore(cur, row["id"])
