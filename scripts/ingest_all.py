"""
Script to ingest business data from all federal, provincial, and municipal sources into PostgreSQL database.
"""
import sys
from app.db import get_conn
from app.pipeline.orchestrator import run_connector
from app.connectors.federal_corporations_canada import FederalCorporationsCanadaConnector
from app.connectors.ckan_open_data import CkanOpenDataConnector, SOURCE_REGISTRY as CKAN_SOURCES
from app.connectors.socrata_open_data import SocrataOpenDataConnector, SOURCE_REGISTRY as SOCRATA_SOURCES
from app.connectors.opendatasoft import OpendatasoftConnector, SOURCE_REGISTRY as ODS_SOURCES
from app.logging_config import get_logger

logger = get_logger("ingest_all")

def get_db_stats():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS total FROM businesses")
            total = cur.fetchone()["total"]
            cur.execute("SELECT source_key, count(*) AS cnt FROM businesses GROUP BY source_key ORDER BY cnt DESC")
            by_source = cur.fetchall()
            return total, by_source

def main():
    logger.info("==========================================")
    logger.info("Starting Full Canada B2B Business Ingestion")
    logger.info("==========================================")

    initial_total, initial_sources = get_db_stats()
    logger.info("Initial Total Businesses in DB: %d", initial_total)
    for row in initial_sources:
        logger.info("  - %s: %d", row["source_key"], row["cnt"])

    # 1. Federal Corporations
    logger.info("\n--- Ingesting Federal Corporations (ISED Canada) ---")
    try:
        run_connector(FederalCorporationsCanadaConnector(), enrich_contacts=False)
    except Exception as exc:
        logger.exception("Failed federal ingestion: %s", exc)

    # 2. CKAN Sources (Ontario, Toronto, Alberta, Montreal)
    logger.info("\n--- Ingesting CKAN Sources (%d sources) ---", len(CKAN_SOURCES))
    for cfg in CKAN_SOURCES:
        logger.info("Running CKAN source: %s", cfg.key)
        try:
            run_connector(CkanOpenDataConnector(cfg), enrich_contacts=False)
        except Exception as exc:
            logger.exception("Failed CKAN source %s: %s", cfg.key, exc)

    # 3. Socrata Sources (Calgary, Edmonton, Winnipeg)
    logger.info("\n--- Ingesting Socrata Sources (%d sources) ---", len(SOCRATA_SOURCES))
    for cfg in SOCRATA_SOURCES:
        logger.info("Running Socrata source: %s", cfg.key)
        try:
            run_connector(SocrataOpenDataConnector(cfg), enrich_contacts=False)
        except Exception as exc:
            logger.exception("Failed Socrata source %s: %s", cfg.key, exc)

    # 4. Opendatasoft Sources (Vancouver)
    logger.info("\n--- Ingesting Opendatasoft Sources (%d sources) ---", len(ODS_SOURCES))
    for cfg in ODS_SOURCES:
        logger.info("Running Opendatasoft source: %s", cfg.key)
        try:
            run_connector(OpendatasoftConnector(cfg), enrich_contacts=False)
        except Exception as exc:
            logger.exception("Failed Opendatasoft source %s: %s", cfg.key, exc)

    final_total, final_sources = get_db_stats()
    logger.info("\n==========================================")
    logger.info("Ingestion Complete!")
    logger.info("Final Total Businesses in DB: %d (+%d new records added)", final_total, final_total - initial_total)
    for row in final_sources:
        logger.info("  - %s: %d", row["source_key"], row["cnt"])
    logger.info("==========================================")

if __name__ == "__main__":
    main()
