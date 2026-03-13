"""Layer 2: Static output filters — SLA hallucination check, PII leak detection."""

import re
from dataclasses import dataclass, field

from app.guardrails.static_filters import check_output_pii

# SLA-related numbers/terms to validate against context
_TIME_PATTERN = re.compile(
    r"\b(\d+)\s*(minutes?|hours?|business\s+days?|days?)\b", re.IGNORECASE
)
_PERCENTAGE_PATTERN = re.compile(r"\b(\d+\.?\d*)\s*%\b")


@dataclass
class OutputValidation:
    passed: bool = True
    pii_leaks: list[dict] = field(default_factory=list)
    hallucinated_sla: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def validate_output(response: str, context_chunks: list[dict]) -> OutputValidation:
    result = OutputValidation()

    # Check for PII in output
    result.pii_leaks = check_output_pii(response)
    if result.pii_leaks:
        result.passed = False
        result.flags.append("PII detected in model output")

    # Check SLA numbers are grounded in context
    context_text = " ".join(c.get("text", "") for c in context_chunks)

    # Extract time values from response
    for match in _TIME_PATTERN.finditer(response):
        term = match.group(0)
        # Check if this time value appears in the retrieved context
        if term.lower() not in context_text.lower():
            # Also check just the number + unit loosely
            number = match.group(1)
            unit = match.group(2).lower()
            loose_pattern = re.compile(rf"\b{number}\s*{re.escape(unit)}", re.IGNORECASE)
            if not loose_pattern.search(context_text):
                result.hallucinated_sla.append(term)

    # Extract percentages from response
    for match in _PERCENTAGE_PATTERN.finditer(response):
        term = match.group(0)
        if term not in context_text:
            result.hallucinated_sla.append(term)

    if result.hallucinated_sla:
        result.flags.append(f"Possible hallucinated SLA values: {result.hallucinated_sla}")

    return result
