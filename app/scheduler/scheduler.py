"""Long-running scheduler process (runs inside the `scheduler` container).

Uses APScheduler so the whole thing is a single portable Python process —
no external cron dependency, works identically on any Ubuntu server via
Docker Compose. To add a new source, register it in the appropriate
connector module's SOURCE_REGISTRY:
  * app/connectors/ckan_open_data.py       — CKAN portals (Toronto, Ontario, Alberta, Montreal)
  * app/connectors/socrata_open_data.py    — Socrata portals (Calgary, Edmonton, Winnipeg)
  * app/connectors/opendatasoft.py         — Opendatasoft portals (Vancouver)
  * app/connectors/federal_corporations_canada.py — Federal registry (standalone)
Or add a new connector class for a non-standard source.
See docs/ADDING_SOURCES.md.
"""
import time
from apscheduler.schedulers.blocking import BlockingScheduler
from app.config import config
from app.logging_config import get_logger
from app.pipeline.orchestrator import run_connector
from app.connectors.federal_corporations_canada import FederalCorporationsCanadaConnector
from app.connectors.ckan_open_data import CkanOpenDataConnector, SOURCE_REGISTRY as CKAN_SOURCES
from app.connectors.socrata_open_data import SocrataOpenDataConnector, SOURCE_REGISTRY as SOCRATA_SOURCES
from app.connectors.opendatasoft import OpendatasoftConnector, SOURCE_REGISTRY as ODS_SOURCES

logger = get_logger(__name__)


def collect_federal():
    run_connector(FederalCorporationsCanadaConnector())


def collect_ckan_sources():
    for cfg in CKAN_SOURCES:
        run_connector(CkanOpenDataConnector(cfg))


def collect_socrata_sources():
    for cfg in SOCRATA_SOURCES:
        run_connector(SocrataOpenDataConnector(cfg))


def collect_opendatasoft_sources():
    for cfg in ODS_SOURCES:
        run_connector(OpendatasoftConnector(cfg))


def run_all_once():
    """Useful for `docker compose run scheduler python -m app.scheduler.scheduler --once`
    or scripts/run_pipeline.sh — runs every configured source one time."""
    collect_federal()
    collect_ckan_sources()
    collect_socrata_sources()
    collect_opendatasoft_sources()


def main():
    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(
        collect_federal, "interval",
        minutes=config.COLLECT_INTERVAL_MINUTES, id="collect_federal",
        next_run_time=None,  # don't fire instantly on boot; run_all_once handles first run
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

    logger.info(
        "Scheduler starting. Collect interval=%d min, refresh interval=%d min. "
        "Sources: %d federal, %d CKAN, %d Socrata, %d Opendatasoft",
        config.COLLECT_INTERVAL_MINUTES, config.REFRESH_INTERVAL_MINUTES,
        1, len(CKAN_SOURCES), len(SOCRATA_SOURCES), len(ODS_SOURCES),
    )

    # Run once immediately on first boot so the trial deployment has data
    # without waiting a full interval.
    run_all_once()

    scheduler.start()


if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        run_all_once()
    else:
        main()
