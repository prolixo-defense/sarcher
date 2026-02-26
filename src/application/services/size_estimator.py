"""
Company size band estimation from multiple signals.

Priority:
1. Explicit employee_count (from enrichment APIs or SAM.gov)
2. Apollo organization data
3. Regex extraction from page text / snippets
4. Falls back to "unknown"
"""
from __future__ import annotations

import re
from typing import Any


def classify_size_band(count: int | None) -> str:
    """Classify an employee count into a size band label."""
    if count is None or count <= 0:
        return "unknown"
    if count < 50:
        return "small"
    if count < 500:
        return "mid-market"
    return "enterprise"


# Patterns that capture a number associated with employee-count language.
_EMPLOYEE_PATTERNS = [
    # LinkedIn-style "51-200 employees" (MUST be before single-number patterns)
    re.compile(r"(\d[\d,]*)\s*-\s*(\d[\d,]*)\s*employees", re.I),
    # "200 employees", "200+ employees", "over 200 employees"
    re.compile(r"(?:over|more\s+than|approximately|about|~)?\s*(\d[\d,]*)\+?\s*employees", re.I),
    # "team of 50", "a team of 200+"
    re.compile(r"team\s+of\s+(\d[\d,]*)\+?", re.I),
    # "50+ staff", "200 staff members"
    re.compile(r"(\d[\d,]*)\+?\s*staff(?:\s+members)?", re.I),
    # "workforce of 150"
    re.compile(r"workforce\s+of\s+(\d[\d,]*)\+?", re.I),
    # "50-200 people", "100 people"
    re.compile(r"(\d[\d,]*)\s*(?:-\s*\d[\d,]*)?\s+people", re.I),
    # "employs 300", "employing 300+"
    re.compile(r"employ(?:s|ing)\s+(\d[\d,]*)\+?", re.I),
]


def estimate_employee_count_from_text(text: str) -> int | None:
    """
    Extract employee count from freeform text using regex patterns.

    For range patterns (e.g. "51-200 employees"), returns the midpoint.
    Returns None if no match found.
    """
    if not text:
        return None

    for pattern in _EMPLOYEE_PATTERNS:
        match = pattern.search(text)
        if match:
            groups = match.groups()
            if len(groups) == 2 and groups[1] is not None:
                # Range pattern — use midpoint
                low = int(groups[0].replace(",", ""))
                high = int(groups[1].replace(",", ""))
                return (low + high) // 2
            else:
                return int(groups[0].replace(",", ""))

    return None


def estimate_size_band(
    employee_count: int | None = None,
    snippet_text: str | None = None,
    apollo_data: dict[str, Any] | None = None,
) -> tuple[str, int | None]:
    """
    Estimate company size band from multiple signals.

    Returns (band, estimated_count) where band is one of:
    "small", "mid-market", "enterprise", "unknown"

    Priority: explicit count > Apollo org data > snippet text regex > unknown.
    """
    # 1. Explicit employee count
    if employee_count and employee_count > 0:
        return classify_size_band(employee_count), employee_count

    # 2. Apollo organization data
    if apollo_data:
        apollo_count = apollo_data.get("estimated_num_employees")
        if apollo_count and isinstance(apollo_count, (int, float)) and apollo_count > 0:
            count = int(apollo_count)
            return classify_size_band(count), count

    # 3. Snippet / page text regex
    if snippet_text:
        text_count = estimate_employee_count_from_text(snippet_text)
        if text_count and text_count > 0:
            return classify_size_band(text_count), text_count

    return "unknown", None
