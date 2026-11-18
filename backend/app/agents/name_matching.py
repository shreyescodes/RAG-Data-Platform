"""Matches company names however a data source spells them.

SEC filings abbreviate issuers ("BANK AMER CORP", "OCCIDENTAL PETE CORP"), while
answers use everyday names ("Bank of America", "Occidental Petroleum"). A name
matches when its words appear, in order, in the stored name, so a different
company that shares one word ("Bank of Canada") does not.
"""

from __future__ import annotations

import re
from functools import lru_cache

_WORD = re.compile(r"[^\W_]+")
_MIN_JOINED_LENGTH = 6

# Words that do not identify a company, including SEC filer suffixes.
_IGNORED = frozenset(
    [
        "the",
        "of",
        "and",
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "ltd",
        "limited",
        "llc",
        "lp",
        "plc",
        "sa",
        "nv",
        "ag",
        "se",
        "del",
        "new",
    ]
)

# Abbreviations used in SEC 13F issuer names.
_SPELLINGS = {
    "amer": "america",
    "commun": "communications",
    "communs": "communications",
    "entmt": "entertainment",
    "fin": "financial",
    "finl": "financial",
    "grp": "group",
    "hldg": "holdings",
    "hldgs": "holdings",
    "holding": "holdings",
    "hlth": "health",
    "inds": "industries",
    "intl": "international",
    "labs": "laboratories",
    "mfg": "manufacturing",
    "mgmt": "management",
    "mtrs": "motors",
    "natl": "national",
    "pete": "petroleum",
    "pharm": "pharmaceuticals",
    "pharma": "pharmaceuticals",
    "pharmaceutical": "pharmaceuticals",
    "resh": "research",
    "str": "street",
    "svcs": "services",
    "sys": "systems",
    "tech": "technologies",
    "technology": "technologies",
}


@lru_cache(maxsize=4096)
def name_words(name: str) -> tuple[str, ...]:
    """The identifying words of a company name, with abbreviations spelled out."""
    words = (word.lower() for word in _WORD.findall(name))
    return tuple(_SPELLINGS.get(word, word) for word in words if word not in _IGNORED)


def _in_order(words: tuple[str, ...], stored: tuple[str, ...]) -> bool:
    remaining = iter(stored)
    return all(word in remaining for word in words)


def _joins_leading_words(words: tuple[str, ...], stored: tuple[str, ...]) -> bool:
    """Spacing differences at the start of a name: "ExxonMobil", "JP Morgan"."""
    joined = "".join(words)
    if len(joined) < _MIN_JOINED_LENGTH:
        return False
    return any("".join(stored[:end]) == joined for end in range(1, len(stored) + 1))


def names_match(claimed: str, stored: str) -> bool:
    """Whether `claimed` refers to the company recorded as `stored`."""
    words, stored_words = name_words(claimed), name_words(stored)
    if not words or not stored_words:
        return False
    return _in_order(words, stored_words) or _joins_leading_words(words, stored_words)
