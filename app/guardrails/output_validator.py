"""Layer 2: Static output filters — SLA hallucination check, PII leak detection."""

import re
from dataclasses import dataclass, field
from typing import Optional

from app.guardrails.static_filters import _PII_PATTERNS, check_output_pii

# SLA-related numbers/terms to validate against context
_TIME_PATTERN = re.compile(
    r"\b(\d+)\s*(minutes?|hours?|business\s+days?|days?)\b", re.IGNORECASE
)
_PERCENTAGE_PATTERN = re.compile(r"\b(\d+\.?\d*)\s*%\b")


@dataclass
class OutputValidation:
    passed: bool = True
    pii_leaks: list = field(default_factory=list)
    authorized_disclosures: list = field(default_factory=list)
    hallucinated_sla: list = field(default_factory=list)
    flags: list = field(default_factory=list)


def validate_output(
    response: str,
    context_chunks: list,
    tool_results: Optional[list] = None,
) -> OutputValidation:
    result = OutputValidation()

    # Grounding corpus: retrieved KB chunks + raw tool results.
    # Tool results (check_sla, lookup_asset, ...) are authoritative database
    # output, so values quoted from them are grounded, not hallucinated.
    tool_text = " ".join(str(t) for t in (tool_results or []))
    context_text = " ".join(c.get("text", "") for c in context_chunks)
    grounding_text = context_text + " " + tool_text

    # PII values present in tool results are authorized disclosures
    # (e.g. an employee email returned by lookup_asset), not leaks.
    authorized_values = set()
    for pattern in _PII_PATTERNS.values():
        for match in pattern.finditer(tool_text):
            authorized_values.add(match.group())

    for pii in check_output_pii(response):
        if pii["value"] in authorized_values:
            result.authorized_disclosures.append(pii)
        else:
            result.pii_leaks.append(pii)

    if result.pii_leaks:
        result.passed = False
        result.flags.append("PII detected in model output")
    if result.authorized_disclosures:
        disclosed_types = sorted({p["type"] for p in result.authorized_disclosures})
        result.flags.append(
            f"note_authorized_disclosure: {', '.join(disclosed_types)} (grounded in tool result)"
        )

    # Check SLA numbers are grounded in context or tool results.
    # Word-boundary match on number+unit — a plain substring check would
    # let "15 minutes" ground a claim of "5 minutes".
    for match in _TIME_PATTERN.finditer(response):
        term = match.group(0)
        number = match.group(1)
        unit = match.group(2).lower()
        loose_pattern = re.compile(rf"\b{number}\s*{re.escape(unit)}", re.IGNORECASE)
        if not loose_pattern.search(grounding_text):
            result.hallucinated_sla.append(term)

    # Extract percentages from response
    for match in _PERCENTAGE_PATTERN.finditer(response):
        term = match.group(0)
        if term not in grounding_text:
            result.hallucinated_sla.append(term)

    if result.hallucinated_sla:
        result.flags.append(f"Possible hallucinated SLA values: {result.hallucinated_sla}")

    return result
