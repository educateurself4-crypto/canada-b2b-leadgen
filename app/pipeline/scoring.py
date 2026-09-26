"""Lead-quality / confidence score (0-100).

This is a transparent, tunable weighted checklist rather than a black-box
model — the whole point is that the call-centre team can trust and reason
about *why* a lead scored the way it did.
"""

WEIGHTS = {
    "has_verified_phone": 20,
    "has_website": 10,
    "has_verified_address": 15,
    "has_employee_info": 10,
    "has_decision_maker": 20,
    "recently_verified": 10,       # verified within last 90 days
    "multiple_sources": 15,        # confirmed by 2+ independent sources
}

LEAD_READY_THRESHOLD = 50  # businesses at/above this score surface as sales-ready


def score_business(business: dict, contact_count: int, source_count: int, days_since_verified) -> tuple:
    """business: dict of the businesses row (post-update).
    Returns (score: float, breakdown: dict)."""
    breakdown = {}

    breakdown["has_verified_phone"] = bool(business.get("phone"))
    breakdown["has_website"] = bool(business.get("website"))
    breakdown["has_verified_address"] = bool(business.get("address_line1") and business.get("postal_code"))
    breakdown["has_employee_info"] = bool(business.get("size_category"))
    breakdown["has_decision_maker"] = contact_count > 0
    breakdown["recently_verified"] = (days_since_verified is not None and days_since_verified <= 90)
    breakdown["multiple_sources"] = source_count >= 2

    score = sum(WEIGHTS[k] for k, hit in breakdown.items() if hit)
    return float(score), breakdown


def is_lead_ready(score: float) -> bool:
    return score >= LEAD_READY_THRESHOLD
