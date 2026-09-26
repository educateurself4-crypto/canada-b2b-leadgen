from app.pipeline.orchestrator import run_connector
from app.connectors.yellowpages_scraper import YellowPagesConnector

def test_scraper():
    connector = YellowPagesConnector(query="restaurants", location="Toronto, ON", max_pages=1)
    print(f"Running scraper for {{connector.query}} in {{connector.location}}...")
    run_connector(connector, enrich_contacts=False)
    print("Scraping completed!")

if __name__ == "__main__":
    test_scraper()
