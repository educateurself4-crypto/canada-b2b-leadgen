"""Assign a business to one of the required employee-size buckets.

Rules:
  * If we have a verified/exact count (from a source that reports actual
    headcount, e.g. an enrichment source that states "42 employees"),
    size_confidence = 'confirmed'.
  * Otherwise we estimate from indirect signals (director count range from
    the federal registry, industry norms, or leave unclassified) and mark
    size_confidence = 'estimated'. We never present an estimate as fact.
  * If there is no usable signal at all, size_category stays NULL rather
    than guessing — an unlabeled record is more honest than a fabricated
    bucket.
"""

BUCKETS = [
    (1, 4, "1-4"), (5, 9, "5-9"), (10, 19, "10-19"), (20, 49, "20-49"),
    (50, 99, "50-99"), (100, 199, "100-199"), (200, 499, "200-499"),
    (500, 999, "500-999"), (1000, None, "1000+"),
]


def bucket_for_count(count: int) -> str:
    for lo, hi, label in BUCKETS:
        if count >= lo and (hi is None or count <= hi):
            return label
    return None


def classify(employee_count_min, employee_count_max, exact_count=None):
    """Returns (size_category, size_confidence)."""
    if exact_count:
        return bucket_for_count(exact_count), "confirmed"

    if employee_count_min:
        # Use the midpoint of a min/max range as our best estimate.
        hi = employee_count_max or employee_count_min
        midpoint = (employee_count_min + hi) // 2
        return bucket_for_count(midpoint), "estimated"

    return None, "estimated"
