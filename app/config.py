"""Central configuration, loaded from environment (.env)."""
import os
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

load_dotenv()


class Config:
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql://leadgen:changeme@localhost:5432/leadgen",
    )

    SCRAPE_DELAY_SECONDS = float(os.getenv("SCRAPE_DELAY_SECONDS", "2"))
    USER_AGENT = os.getenv(
        "USER_AGENT", "CanadaB2BLeadGen/1.0 (contact: ops@yourcompany.example)"
    )
    RESPECT_ROBOTS_TXT = os.getenv("RESPECT_ROBOTS_TXT", "true").lower() == "true"

    COLLECT_INTERVAL_MINUTES = int(os.getenv("COLLECT_INTERVAL_MINUTES", "360"))
    REFRESH_INTERVAL_MINUTES = int(os.getenv("REFRESH_INTERVAL_MINUTES", "1440"))
    NEW_BUSINESS_SCAN_INTERVAL_MINUTES = int(
        os.getenv("NEW_BUSINESS_SCAN_INTERVAL_MINUTES", "60")
    )

    DASHBOARD_SECRET_KEY = os.getenv("DASHBOARD_SECRET_KEY", "dev-key-change-me")
    DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
    AUTOMATION_API_KEY = os.getenv("AUTOMATION_API_KEY", "dev-automation-key")

    EXPORT_DIR = os.getenv("EXPORT_DIR", "/app/exports")
    LOG_DIR = os.getenv("LOG_DIR", "/app/logs")


config = Config()
