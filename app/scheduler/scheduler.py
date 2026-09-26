"""Long-running scheduler process (runs inside the `scheduler` container).

Uses APScheduler so the whole thing is a single portable Python process —
no external cron dependency, works identically on any Ubuntu server via
Docker Compose. To add a new source, register it in the appropriate
connector module's SOURCE_REGISTRY:
  * app/connectors/ckan_open_data.py       — CKAN portals (Toronto, Ontario, Alberta, Montreal, Ottawa, etc.)
  * app/connectors/socrata_open_data.py    — Socrata portals (Calgary, Edmonton, Winnipeg)
  * app/connectors/opendatasoft.py         — Opendatasoft portals (Vancouver)
  * app/connectors/federal_corporations_canada.py — Federal registry (standalone)
  * app/connectors/bc_orgbook.py           — BC OrgBook API (BC corporate registry)
  * app/connectors/yellowpages_scraper.py  — YellowPages.ca directory
  * app/connectors/federal_corp_api.py     — Federal Corp API (targeted enrichment)
Or add a new connector class for a non-standard source.
See docs/ADDING_SOURCES.md.
"""
import sys
import time
from apscheduler.schedulers.blocking import BlockingScheduler
from app.config import config
from app.logging_config import get_logger
from app.pipeline.orchestrator import run_connector, enrich_recent_websites
from app.connectors.federal_corporations_canada import FederalCorporationsCanadaConnector
from app.connectors.ckan_open_data import CkanOpenDataConnector, SOURCE_REGISTRY as CKAN_SOURCES
from app.connectors.socrata_open_data import SocrataOpenDataConnector, SOURCE_REGISTRY as SOCRATA_SOURCES
from app.connectors.opendatasoft import OpendatasoftConnector, SOURCE_REGISTRY as ODS_SOURCES
from app.connectors.bc_orgbook import BCOrgBookConnector, BCOrgBookNewBusinessConnector
from app.connectors.federal_corp_api import FederalCorpAPIEnrichment
from app.connectors.yellowpages_scraper import YellowPagesConnector

logger = get_logger(__name__)


# ── Collector functions ────────────────────────────────────────────────

def collect_federal():
    """Ingest federal corporations from ISED bulk CSV."""
    logger.info("=== Starting Federal Corporations collection ===")
    run_connector(FederalCorporationsCanadaConnector(), enrich_contacts=False)


def collect_ckan_sources():
    """Ingest all configured CKAN open-data sources."""
    logger.info("=== Starting CKAN sources collection (%d sources) ===", len(CKAN_SOURCES))
    for cfg in CKAN_SOURCES:
        try:
            run_connector(CkanOpenDataConnector(cfg), enrich_contacts=False)
        except Exception as exc:
            logger.exception("CKAN source %s failed: %s", cfg.key, exc)


def collect_socrata_sources():
    """Ingest all configured Socrata open-data sources."""
    logger.info("=== Starting Socrata sources collection (%d sources) ===", len(SOCRATA_SOURCES))
    for cfg in SOCRATA_SOURCES:
        try:
            run_connector(SocrataOpenDataConnector(cfg), enrich_contacts=False)
        except Exception as exc:
            logger.exception("Socrata source %s failed: %s", cfg.key, exc)


def collect_opendatasoft_sources():
    """Ingest all configured Opendatasoft sources."""
    logger.info("=== Starting Opendatasoft sources collection (%d sources) ===", len(ODS_SOURCES))
    for cfg in ODS_SOURCES:
        try:
            run_connector(OpendatasoftConnector(cfg), enrich_contacts=False)
        except Exception as exc:
            logger.exception("Opendatasoft source %s failed: %s", cfg.key, exc)


def collect_bc_orgbook():
    """Ingest BC organizations from OrgBook API."""
    logger.info("=== Starting BC OrgBook collection ===")
    try:
        run_connector(BCOrgBookConnector(), enrich_contacts=False)
    except Exception as exc:
        logger.exception("BC OrgBook collection failed: %s", exc)


def detect_new_businesses_bc():
    """Check for newly registered BC businesses (last 7 days)."""
    logger.info("=== Detecting new BC businesses (OrgBook) ===")
    try:
        run_connector(BCOrgBookNewBusinessConnector(), enrich_contacts=False)
    except Exception as exc:
        logger.exception("BC OrgBook new-business detection failed: %s", exc)


def collect_yellowpages():
    """Supplementary: scrape YellowPages for additional business data."""
    logger.info("=== Starting YellowPages collection ===")
    try:
        yp = YellowPagesConnector(
            queries=["technology", "construction", "manufacturing"],
            locations=[("Toronto", "ON"), ("Vancouver", "BC"), ("Calgary", "AB")],
            max_pages_per_search=1,
        )
        run_connector(yp, enrich_contacts=False)
    except Exception as exc:
        logger.exception("YellowPages collection failed: %s", exc)


# ── Enrichment functions ───────────────────────────────────────────────

def enrich_federal_directors():
    """Look up director/officer names for federal corporations."""
    logger.info("=== Starting federal director enrichment ===")
    try:
        enricher = FederalCorpAPIEnrichment()
        enricher.enrich_batch(limit=50)
    except Exception as exc:
        logger.exception("Federal director enrichment failed: %s", exc)


def enrich_website_contacts():
    """Scrape decision-maker info from business websites."""
    logger.info("=== Starting website contact enrichment ===")
    try:
        enrich_recent_websites("scheduled_enrichment", limit=100)
    except Exception as exc:
        logger.exception("Website contact enrichment failed: %s", exc)


# ── Refresh function ──────────────────────────────────────────────────

def refresh_stale_records():
    """Re-verify businesses that haven't been checked in a while.
    Runs the pipeline again for records older than 30 days, limiting
    to a manageable batch per run."""
    logger.info("=== Starting stale record refresh ===")
    from app.db import get_cursor
    from app.pipeline import scoring

    with get_cursor() as (cur, conn):
        # Update verification timestamp and re-score stale records
        cur.execute(
            """
            UPDATE businesses SET last_verified_at = now()
            WHERE last_verified_at < now() - interval '30 days'
              AND business_status = 'active'
            RETURNING id
            """,
        )
        stale_ids = [row["id"] for row in cur.fetchall()]

    logger.info("Marked %d stale records for re-scoring", len(stale_ids))

    # Re-score each in small batches
    from app.pipeline.orchestrator import _rescore
    batch_size = 200
    for i in range(0, len(stale_ids), batch_size):
        batch = stale_ids[i:i + batch_size]
        with get_cursor() as (cur, conn):
            for bid in batch:
                try:
                    _rescore(cur, bid)
                except Exception:
                    pass


# ── Orchestration ──────────────────────────────────────────────────────

def run_all_once():
    """Useful for `docker compose run scheduler python -m app.scheduler.scheduler --once`
    or scripts/run_pipeline.sh — runs every configured source one time."""
    logger.info("======== STARTING FULL PIPELINE RUN ========")

    # Stage 1: Collect from all sources
    collect_federal()
    collect_ckan_sources()
    collect_socrata_sources()
    collect_opendatasoft_sources()
    collect_bc_orgbook()

    # Stage 2: Enrichment
    enrich_federal_directors()
    enrich_website_contacts()

    # Stage 3: New-business detection
    detect_new_businesses_bc()

    logger.info("======== FULL PIPELINE RUN COMPLETE ========")


def main():
    scheduler = BlockingScheduler(timezone="UTC")

    # --- Primary collection jobs (every COLLECT_INTERVAL_MINUTES) ---
    scheduler.add_job(
        collect_federal, "interval",
        minutes=config.COLLECT_INTERVAL_MINUTES, id="collect_federal",
        next_run_time=None,
    )
    scheduler.add_job(
        collect_ckan_sources, "interval",
        minutes=config.COLLECT_INTERVAL_MINUTES, id="collect_ckan",
        next_run_time=None,
    )
    scheduler.add_job(
        collect_socrata_sources, "interval",
        minutes=config.COLLECT_INTERVAL_MINUTES, id="collect_socrata",
        next_run_time=None,
    )
    scheduler.add_job(
        collect_opendatasoft_sources, "interval",
        minutes=config.COLLECT_INTERVAL_MINUTES, id="collect_opendatasoft",
        next_run_time=None,
    )
    scheduler.add_job(
        collect_bc_orgbook, "interval",
        minutes=config.COLLECT_INTERVAL_MINUTES, id="collect_bc_orgbook",
        next_run_time=None,
    )

    # --- New-business detection (more frequent) ---
    scheduler.add_job(
        detect_new_businesses_bc, "interval",
        minutes=config.NEW_BUSINESS_SCAN_INTERVAL_MINUTES, id="new_biz_bc",
        next_run_time=None,
    )

    # --- Enrichment jobs (run after collection, staggered) ---
    scheduler.add_job(
        enrich_federal_directors, "interval",
        minutes=config.COLLECT_INTERVAL_MINUTES + 30, id="enrich_directors",
        next_run_time=None,
    )
    scheduler.add_job(
        enrich_website_contacts, "interval",
        minutes=config.COLLECT_INTERVAL_MINUTES + 60, id="enrich_websites",
        next_run_time=None,
    )

    # --- Stale record refresh (daily) ---
    scheduler.add_job(
        refresh_stale_records, "interval",
        minutes=config.REFRESH_INTERVAL_MINUTES, id="refresh_stale",
        next_run_time=None,
    )

    # --- Supplementary: YellowPages (weekly — less critical source) ---
    scheduler.add_job(
        collect_yellowpages, "interval",
        minutes=10080,  # weekly
        id="collect_yellowpages",
        next_run_time=None,
    )

    total_sources = 1 + len(CKAN_SOURCES) + len(SOCRATA_SOURCES) + len(ODS_SOURCES) + 1  # +1 for BC OrgBook
    logger.info(
        "Scheduler starting. Collect interval=%d min, refresh interval=%d min, "
        "new-biz scan interval=%d min. "
        "Sources: 1 federal, %d CKAN, %d Socrata, %d Opendatasoft, 1 BC OrgBook, "
        "1 YellowPages. Total=%d",
        config.COLLECT_INTERVAL_MINUTES, config.REFRESH_INTERVAL_MINUTES,
        config.NEW_BUSINESS_SCAN_INTERVAL_MINUTES,
        len(CKAN_SOURCES), len(SOCRATA_SOURCES), len(ODS_SOURCES), total_sources + 1,
    )

    # Run once immediately on first boot so the trial deployment has data
    run_all_once()

    scheduler.start()


if __name__ == "__main__":
    if "--once" in sys.argv:
        run_all_once()
    else:
        main()
