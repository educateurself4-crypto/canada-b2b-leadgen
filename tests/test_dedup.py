"""Unit tests for the pure-logic pieces (no DB needed for these).
Run with: pytest tests/
DB-dependent tests (dedup.find_existing_business, storage.*) need a live
Postgres and are intentionally left as integration tests to run against
the docker-compose `postgres` service — see docs/ARCHITECTURE.md."""
from app.pipeline import normalize
from app.pipeline.employee_classifier import classify, bucket_for_count
from app.pipeline import scoring


def test_normalize_postal_code():
    assert normalize.normalize_postal_code("m5h1a1") == "M5H 1A1"
    assert normalize.normalize_postal_code("M5H 1A1") == "M5H 1A1"
    assert normalize.normalize_postal_code("") is None


def test_normalize_province():
    assert normalize.normalize_province("Ontario") == "ON"
    assert normalize.normalize_province("on") == "ON"
    assert normalize.normalize_province(None) is None


def test_normalize_domain():
    assert normalize.normalize_domain("https://www.example.com/about") == "example.com"
    assert normalize.normalize_domain(None) is None


def test_bucket_for_count():
    assert bucket_for_count(1) == "1-4"
    assert bucket_for_count(4) == "1-4"
    assert bucket_for_count(5) == "5-9"
    assert bucket_for_count(1500) == "1000+"


def test_classify_estimated_vs_confirmed():
    cat, conf = classify(1, 10, exact_count=42)
    assert cat == "50-99" and conf == "confirmed"

    cat, conf = classify(5, 9)
    assert cat == "5-9" and conf == "estimated"

    cat, conf = classify(None, None)
    assert cat is None


def test_scoring_breakdown():
    business = {"phone": "+14165551234", "website": "example.com",
                "address_line1": "1 Main St", "postal_code": "M5H 1A1",
                "size_category": "10-19"}
    score, breakdown = scoring.score_business(business, contact_count=1, source_count=2, days_since_verified=10)
    assert score == 100.0  # every weighted factor is satisfied in this example
    assert breakdown["has_decision_maker"] is True
    assert scoring.is_lead_ready(score) is True
