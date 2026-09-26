"""Tests for the normalize module — covers phone, postal code, province, domain,
and full record normalization."""
import pytest
from app.pipeline.normalize import (
    normalize_phone, normalize_postal_code, normalize_province,
    normalize_domain, normalize_name, normalize_record,
)
from app.connectors.base import RawBusinessRecord


class TestNormalizePhone:
    def test_valid_ca_number(self):
        assert normalize_phone("416-555-1234") == "+14165551234"

    def test_valid_with_country_code(self):
        assert normalize_phone("+1 (604) 555-0199") == "+16045550199"

    def test_valid_ten_digits(self):
        assert normalize_phone("9055551234") == "+19055551234"

    def test_invalid_returns_none(self):
        assert normalize_phone("123") is None

    def test_none_input(self):
        assert normalize_phone(None) is None

    def test_empty_string(self):
        assert normalize_phone("") is None


class TestNormalizePostalCode:
    def test_six_chars(self):
        assert normalize_postal_code("m5v2t6") == "M5V 2T6"

    def test_with_space(self):
        assert normalize_postal_code("K1A 0B1") == "K1A 0B1"

    def test_with_dash(self):
        assert normalize_postal_code("H2X-1Y4") == "H2X 1Y4"

    def test_none_input(self):
        assert normalize_postal_code(None) is None

    def test_empty_string(self):
        assert normalize_postal_code("") is None


class TestNormalizeProvince:
    def test_two_letter_code(self):
        assert normalize_province("ON") == "ON"

    def test_full_name(self):
        assert normalize_province("Ontario") == "ON"
        assert normalize_province("BRITISH COLUMBIA") == "BC"
        assert normalize_province("quebec") == "QC"

    def test_none(self):
        assert normalize_province(None) is None
        assert normalize_province("") is None


class TestNormalizeDomain:
    def test_full_url(self):
        assert normalize_domain("https://www.example.com/about") == "example.com"

    def test_bare_domain(self):
        assert normalize_domain("example.ca") == "example.ca"

    def test_none(self):
        assert normalize_domain(None) is None


class TestNormalizeName:
    def test_trims_whitespace(self):
        assert normalize_name("  Acme  Corp  ") == "Acme Corp"

    def test_none(self):
        assert normalize_name(None) is None


class TestNormalizeRecord:
    def test_full_record(self):
        raw = RawBusinessRecord(
            legal_name="Acme Inc.",
            province="Ontario",
            city="Toronto",
            postal_code="m5v2t6",
            phone="416-555-1234",
            website="https://www.acme.ca",
            source_name="test",
            source_kind="other",
        )
        result = normalize_record(raw)
        assert result["province"] == "ON"
        assert result["postal_code"] == "M5V 2T6"
        assert result["phone"] == "+14165551234"
        assert result["domain"] == "acme.ca"
        assert result["legal_name"] == "Acme Inc."


class TestEmployeeClassifier:
    def test_buckets(self):
        from app.pipeline.employee_classifier import classify, bucket_for_count

        assert bucket_for_count(1) == "1-4"
        assert bucket_for_count(4) == "1-4"
        assert bucket_for_count(5) == "5-9"
        assert bucket_for_count(50) == "50-99"
        assert bucket_for_count(100) == "100-199"
        assert bucket_for_count(500) == "500-999"
        assert bucket_for_count(1000) == "1000+"
        assert bucket_for_count(5000) == "1000+"

    def test_classify_exact(self):
        from app.pipeline.employee_classifier import classify
        cat, conf = classify(None, None, exact_count=42)
        assert cat == "20-49"
        assert conf == "confirmed"

    def test_classify_range(self):
        from app.pipeline.employee_classifier import classify
        cat, conf = classify(10, 20)
        assert cat == "10-19"  # midpoint = 15
        assert conf == "estimated"

    def test_classify_none(self):
        from app.pipeline.employee_classifier import classify
        cat, conf = classify(None, None)
        assert cat is None


class TestScoring:
    def test_full_score(self):
        from app.pipeline.scoring import score_business, is_lead_ready

        biz = {
            "phone": "+14165551234",
            "website": "https://acme.ca",
            "address_line1": "123 Main St",
            "postal_code": "M5V 2T6",
            "size_category": "20-49",
        }
        score, breakdown = score_business(biz, contact_count=1, source_count=3, days_since_verified=5)
        assert score == 100  # all criteria met
        assert is_lead_ready(score) is True

    def test_minimal_score(self):
        from app.pipeline.scoring import score_business, is_lead_ready

        biz = {}
        score, breakdown = score_business(biz, contact_count=0, source_count=1, days_since_verified=None)
        assert score == 0
        assert is_lead_ready(score) is False

    def test_partial_score(self):
        from app.pipeline.scoring import score_business

        biz = {"phone": "+14165551234", "website": "https://acme.ca"}
        score, _ = score_business(biz, contact_count=0, source_count=1, days_since_verified=30)
        assert score == 40  # phone(20) + website(10) + recent(10)
