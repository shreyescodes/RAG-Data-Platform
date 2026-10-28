"""Regex-based PII redaction applied to user queries before any processing.

Patterns are deliberately conservative about bare digit runs: this is a
financial application, so numbers such as `1000000` or `2024` must survive.
Phone numbers therefore need separators or a `+` country prefix, and card
numbers must pass the Luhn checksum.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_IPV4 = re.compile(rf"(?<![\d.]){_OCTET}(?:\.{_OCTET}){{3}}(?![\d.])")
_SSN = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
_CARD_CANDIDATE = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
_PHONE = re.compile(
    r"(?<![\w+])"
    r"(?:"
    r"\+\d{1,3}[\s.-]?(?:\(\d{1,4}\)|\d{1,4})(?:[\s.-]?\d{2,4}){2,3}"  # +CC ...
    r"|(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}"  # (415) 555-2671
    r")"
    r"(?:\s?(?:x|ext\.?)\s?\d{1,6})?"
    r"(?!\w)",
    re.IGNORECASE,
)


def _passes_luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


@dataclass(frozen=True, slots=True)
class Redaction:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def redacted(self) -> bool:
        return bool(self.counts)


def redact_pii(text: str) -> Redaction:
    """Replace PII in `text` with `[TYPE]` placeholders."""
    if not text:
        return Redaction(text=text)

    counts: Counter[str] = Counter()

    def sub(pattern: re.Pattern[str], label: str, value: str) -> str:
        def repl(match: re.Match[str]) -> str:
            counts[label] += 1
            return f"[{label}]"

        return pattern.sub(repl, value)

    def card_repl(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group())
        if 13 <= len(digits) <= 19 and _passes_luhn(digits):
            counts["CREDIT_CARD"] += 1
            return "[CREDIT_CARD]"
        return match.group()

    # Order matters: more specific patterns run first.
    result = sub(_EMAIL, "EMAIL", text)
    result = sub(_IPV4, "IPV4", result)
    result = sub(_SSN, "SSN", result)
    result = _CARD_CANDIDATE.sub(card_repl, result)
    result = sub(_PHONE, "PHONE", result)
    return Redaction(text=result, counts=dict(counts))
