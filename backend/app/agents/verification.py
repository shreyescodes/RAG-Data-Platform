"""Verification agent: flags answer claims the evidence does not support.

Pipeline, per answer:

1. Claim extraction (deterministic): the answer, summary and insights are
   split into sentences and clauses, so every verdict maps to visible text.
2. Fact checking (deterministic, no model): every number, year, date and
   named entity in a claim is looked up in the evidence: result rows, column
   aggregates (sum, mean, median, min, max, count), the question itself and
   live market data. Percentages and multiples may also match ratios computed
   from the rows. A number in a claim that names an entity must come from that
   entity's rows, which catches correct figures attributed to the wrong company.
3. LLM judge (hybrid mode only): claims the checker cannot settle (no
   checkable facts, a mismatch, or support only via a computed ratio) go to one
   structured LLM call returning a verdict and evidence ids per claim.
   Deterministic mismatches always win: the judge cannot clear a claim whose
   number or name appears nowhere in the evidence.
"""

from __future__ import annotations

import json
import logging
import math
import re
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.base import Agent, Trace
from app.core.exceptions import LLMError
from app.schemas import ClaimCheck, EvidenceRef, VerificationReport
from app.services.structured_output import (
    OutputRejected,
    StructuredOutputError,
    StructuredOutputExtractor,
)

logger = logging.getLogger(__name__)

PURPOSE = "verification"
VerificationMode = Literal["off", "heuristic", "hybrid"]
Verdict = Literal["supported", "partially_supported", "unsupported", "unverifiable"]
Method = Literal["deterministic", "llm", "hybrid"]
Source = Literal["answer", "summary", "insight"]

# Rows scanned for matching values; computed ratios use a smaller window.
MAX_EVIDENCE_ROWS = 200
_DERIVED_ROWS = 25
# Evidence shown to the LLM judge.
_JUDGE_ROWS = 25
_JUDGE_EVIDENCE_CHARS = 6_000
_MAX_REFS = 4
_COUNT_SUFFIXES = (".count", ".non_null", ".distinct")

# --- Fact extraction ------------------------------------------------------------------

# Models often write typographic hyphens (U+2011 inside "2026-06-30") and
# spaces; fold them to ASCII so dates, 10-K forms and "50-day" parse either way.
_HYPHENS = (0x2010, 0x2011, 0x2012)  # hyphen, non-breaking hyphen, figure dash
_SPACES = (0x00A0, 0x2007, 0x202F)  # no-break, figure and narrow no-break spaces
_TYPOGRAPHY: dict[int, str] = dict.fromkeys(_HYPHENS, "-") | dict.fromkeys(_SPACES, " ")
_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_FILING_FORM = re.compile(r"\b(?:10-K|10-Q|8-K|20-F|S-1)\b", re.IGNORECASE)
_NUMBER = re.compile(
    r"(?<![\w.])(?P<cur>[$€£])?(?P<sign>[-+−])?(?P<cur2>[$€£])?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?!\d|st\b|nd\b|rd\b|th\b|-day\b|-week\b|-month\b|-year\b)"
    r"(?:\s?(?P<suf>%|percent\b|x\b|×|[kKmMbBtT]\b|thousand\b|million\b|billion\b"
    r"|trillion\b|bn\b|mn\b|mm\b))?"
)
_SCALE = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mm": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "t": 1e12,
    "trillion": 1e12,
}
_NUMBER_WORD_TEXT = "two three four five six seven eight nine ten eleven twelve"
_NUMBER_WORDS = {word: value for value, word in enumerate(_NUMBER_WORD_TEXT.split(), start=2)}
_NUMBER_WORD = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", re.IGNORECASE)
# A number after "above", "under", "more than"... is a bound, not a value: no
# cell has to equal it. "min": values are at or above it; "max": at or below.
_BOUND_MIN = re.compile(
    r"\b(?:above|over|beyond|exceed(?:s|ed|ing)?|surpass(?:es|ed|ing)?"
    r"|(?:more|greater|higher)\s+than|at\s+least)\s*$",
    re.IGNORECASE,
)
_BOUND_MAX = re.compile(
    r"\b(?:under|below|(?:less|fewer|lower)\s+than|at\s+most|up\s+to)\s*$", re.IGNORECASE
)
# "All five exceed $180M", "volumes stayed above 26M": a bound on every row,
# which the rows can confirm or refute. A bound on a total or an average cannot.
_UNIVERSAL = re.compile(
    r"\b(?:all|every|each|both|throughout|consistently|always|remain\w*|stay\w*)\b",
    re.IGNORECASE,
)
_AGGREGATE_CUE = re.compile(
    r"\b(?:total|sum|combined|together|average|mean|median|overall|aggregate)\b", re.IGNORECASE
)
Bound = Literal["", "min", "max"]
# "roughly $7.5M" for 7.6M is not a hallucination: a hedged number matches
# within twice its stated precision or 2%, whichever is wider.
_HEDGE_BEFORE = re.compile(
    r"(?:\b(?:about|roughly|approximately|approx\.?|around|nearly|almost|close\s+to)|~|≈)\s*$",
    re.IGNORECASE,
)
_HEDGE_RELATIVE = 0.02
# "top 5", "the last three days", "the 3 largest": a rank or window, not a value.
_POSITION_BEFORE = re.compile(
    r"\b(?:top|first|last|bottom|leading|final|past|previous|recent)\s*$", re.IGNORECASE
)
_POSITION_AFTER = re.compile(
    r"^\s*(?:largest|biggest|highest|lowest|smallest|best|worst|strongest|weakest|most|least)\b",
    re.IGNORECASE,
)
# Words saying a claim compares values, so a stated number may be their difference.
_DIFFERENCE_CUE = re.compile(
    r"\b(?:gaps?|difference|differ\w*|spread|apart|ahead|behind|widen\w*|narrow\w*|higher"
    r"|lower|more|less|larger|smaller|bigger|increase\w*|decrease\w*|rose|fell|grew|dropped"
    r"|declined|gained|lost|by)\b",
    re.IGNORECASE,
)
# Words saying a claim adds values up: "the top two together hold $540M".
_SUM_CUE = re.compile(
    r"\b(?:together|combined|in\s+total|total|sum|add\s+up|account\s+for)\b", re.IGNORECASE
)
# Dates with month names: "June 30, 2026", "Jun 30", "30 June 2026". Matched
# case-sensitively, so the verb "may" is not a month.
_MONTH_NAMES = (
    "January Jan",
    "February Feb",
    "March Mar",
    "April Apr",
    "May",
    "June Jun",
    "July Jul",
    "August Aug",
    "September Sept Sep",
    "October Oct",
    "November Nov",
    "December Dec",
)
_MONTHS = {name: n for n, names in enumerate(_MONTH_NAMES, start=1) for name in names.split()}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_MONTH_FIRST = re.compile(
    rf"\b(?P<month>{_MONTH})\.?\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b"
    rf"(?:,?\s+(?P<year>\d{{4}})\b)?"
)
_DAY_FIRST = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<month>{_MONTH})\.?,?\s+"
    rf"(?P<year>\d{{4}})\b"
)
# Metric names such as "LTV-to-CAC" are vocabulary, not names to look up.
_TERM_SEPARATOR = re.compile(r"[-/]")
_TERM_CONNECTORS = frozenset({"to", "vs", "per", "over", "and"})
_ENTITY = re.compile(r"\b[A-Z][\w&'.-]*(?:\s+(?:[A-Z][\w&'.-]*|of|&))*")
_POSSESSIVE = re.compile(r"['’]s\b")
# Capitalised words that carry no checkable identity.
_COMMON_CAPITALISED_TEXT = """
    a an the this that these those there their it its in on of at by for from to and or
    but with as overall however notably meanwhile also only most all both each total
    average median data results result query table rows row sample values value january
    february march april may june july august september october november december monday
    tuesday wednesday thursday friday saturday sunday q1 q2 q3 q4 fy h1 h2 i we you they
    he she note while although among between per across over under compared relative
    since during after before yes no none"""
_COMMON_CAPITALISED = frozenset(_COMMON_CAPITALISED_TEXT.split())
# Domain vocabulary that needs no evidence of its own.
_DOMAIN_TERMS_TEXT = """
    saas usd eur gbp ttm yoy qoq mom cagr ipo ceo cfo sec edgar nasdaq nyse s&p ai p/e pe
    ebitda arr mrr ltv cac eps"""
_DOMAIN_TERMS = frozenset(_DOMAIN_TERMS_TEXT.split())
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9$\"'(])")
_ABBREVIATION_END = re.compile(
    r"\b(?:inc|corp|co|ltd|plc|vs|e\.g|i\.e|etc|approx|no|u\.s)\.$", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class NumberFact:
    text: str
    value: float
    tolerance: float  # half a unit of the stated precision
    percent: bool = False
    multiple: bool = False
    small_count: bool = False  # a bare integer <= 20: only counts may support it
    bound: Bound = ""  # "above $180M" is "min": a threshold, not a value
    positional: bool = False  # "top 3", "last 10 days": a rank or window


@dataclass(frozen=True, slots=True)
class Facts:
    numbers: tuple[NumberFact, ...] = ()
    years: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    # Lone capitalised words opening a sentence: names or just grammar. They
    # narrow the row check when found in the evidence but never fail a claim.
    weak_entities: tuple[str, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.numbers or self.years or self.dates or self.entities)


def _role(text: str, match: re.Match[str]) -> tuple[Bound, bool]:
    """Which bound the number at `match` is, if any, and whether it is a rank or window."""
    before, after = text[max(0, match.start() - 30) : match.start()], text[match.end() :]
    bound: Bound = (
        "min" if _BOUND_MIN.search(before) else "max" if _BOUND_MAX.search(before) else ""
    )
    positional = bool(_POSITION_BEFORE.search(before) or _POSITION_AFTER.match(after))
    return bound, positional


def _word_dates(text: str) -> tuple[tuple[str, ...], str]:
    """Dates written with month names, and `text` with them blanked out.

    Each date becomes an ISO needle ("2026-06-30"; "-06-30" without a year), so
    its day and year are not misread as a number and a year.
    """
    found: list[str] = []

    def convert(match: re.Match[str]) -> str:
        month, day, year = (
            _MONTHS[match.group("month")],
            int(match.group("day")),
            match.group("year"),
        )
        try:
            date(int(year) if year else 2000, month, day)  # 2000 is a leap year
        except ValueError:
            return match.group(0)
        found.append(f"{year}-{month:02d}-{day:02d}" if year else f"-{month:02d}-{day:02d}")
        return " " * len(match.group(0))

    text = _MONTH_FIRST.sub(convert, _DAY_FIRST.sub(convert, text))
    return tuple(found), text


def _number_fact(
    match: re.Match[str], *, bound: Bound = "", positional: bool = False
) -> NumberFact:
    raw = match.group("num")
    suffix = (match.group("suf") or "").lower()
    currency = bool(match.group("cur") or match.group("cur2"))
    sign = -1.0 if match.group("sign") in ("-", "−") else 1.0
    digits = raw.replace(",", "")
    decimals = len(digits.split(".", 1)[1]) if "." in digits else 0
    scale = _SCALE.get(suffix, 1.0)
    value = sign * float(digits) * scale
    return NumberFact(
        text=match.group(0).strip(),
        value=value,
        tolerance=0.5 * 10 ** (-decimals) * scale,
        percent=suffix in ("%", "percent"),
        multiple=suffix in ("x", "×"),
        small_count=not (currency or suffix or decimals or "," in raw) and abs(value) <= 20,
        bound=bound,
        positional=positional,
    )


def _is_year(match: re.Match[str]) -> bool:
    raw = match.group("num")
    return (
        len(raw) == 4
        and raw.isdigit()
        and 1900 <= int(raw) <= 2100
        and not (match.group("cur") or match.group("cur2") or match.group("suf"))
    )


def _entities(claim: str) -> tuple[list[str], list[str]]:
    found: list[str] = []
    weak: list[str] = []
    # A possessive ends a name ("Apple's ARR"); same-length replacement keeps offsets.
    claim = _POSSESSIVE.sub(", ", claim)
    for match in _ENTITY.finditer(claim):
        words = match.group(0).strip(" .,'-").split()
        while words and words[0].lower() in _COMMON_CAPITALISED:
            words.pop(0)
        while words and words[-1] in ("of", "&"):
            words.pop()
        if not words:
            continue
        entity = " ".join(words)
        opens_claim = (
            not claim[: match.start()].strip() or claim[: match.start()].rstrip()[-1] in ".:;"
        )
        if len(entity) < 2 or entity.lower() in _DOMAIN_TERMS:
            continue
        parts = _TERM_SEPARATOR.split(entity.lower())
        if len(parts) > 1 and all(p in _DOMAIN_TERMS or p in _TERM_CONNECTORS for p in parts):
            continue
        if any(ch.isdigit() for ch in entity) and not entity.isupper():
            continue
        if opens_claim and len(words) == 1 and not entity.isupper():
            weak.append(entity)
        else:
            found.append(entity)
    return found, weak


def extract_facts(claim: str) -> Facts:
    claim = claim.translate(_TYPOGRAPHY)
    word_dates, plain = _word_dates(claim)
    dates = tuple(_ISO_DATE.findall(plain)) + word_dates
    text = _FILING_FORM.sub(" ", _ISO_DATE.sub(" ", plain))
    numbers: list[NumberFact] = []
    years: list[str] = []
    for match in _NUMBER.finditer(text):
        if _is_year(match):
            years.append(match.group("num"))
        else:
            bound, positional = _role(text, match)
            fact = _number_fact(match, bound=bound, positional=positional)
            if _HEDGE_BEFORE.search(text[max(0, match.start() - 20) : match.start()]):
                tolerance = max(2 * fact.tolerance, _HEDGE_RELATIVE * abs(fact.value))
                fact = replace(fact, tolerance=tolerance)
            numbers.append(fact)
    for match in _NUMBER_WORD.finditer(text):
        value = float(_NUMBER_WORDS[match.group(1).lower()])
        bound, positional = _role(text, match)
        numbers.append(
            NumberFact(
                text=match.group(1),
                value=value,
                tolerance=0.5,
                small_count=True,
                bound=bound,
                positional=positional,
            )
        )
    entities, weak = _entities(plain)  # month names in dates are not names
    return Facts(tuple(numbers), tuple(years), dates, tuple(entities), tuple(weak))


# --- Claims ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Claim:
    id: str
    text: str
    source: Source


def _sentences(text: str) -> list[str]:
    parts: list[str] = []
    for piece in _SENTENCE_SPLIT.split(text.strip()):
        if parts and _ABBREVIATION_END.search(parts[-1]):
            parts[-1] = f"{parts[-1]} {piece}"
        else:
            parts.append(piece)
    clauses = [c.strip() for sentence in parts for c in sentence.split(";")]
    return [c for c in clauses if len(c.split()) >= 2]


def extract_claims(answer: str, summary: str = "", insights: Iterable[str] = ()) -> list[Claim]:
    """Atomic claims (sentences and `;` clauses), de-duplicated, in reading order."""
    claims: list[Claim] = []
    seen: set[str] = set()

    def add(text: str, source: Source) -> None:
        for sentence in _sentences(text):
            key = sentence.lower().rstrip(".")
            if key not in seen:
                seen.add(key)
                claims.append(Claim(id=f"c{len(claims) + 1}", text=sentence, source=source))

    add(answer, "answer")
    add(summary, "summary")
    for insight in insights:
        add(insight, "insight")
    return claims


# --- Evidence --------------------------------------------------------------------------


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _display(value: Any) -> str:
    """A cell for an evidence label: no float noise, no exponent notation."""
    if isinstance(value, float) and math.isfinite(value):
        return f"{value:,.0f}" if value.is_integer() or abs(value) >= 1e6 else f"{value:.6g}"
    return str(value)


@dataclass(slots=True)
class _Item:
    ref: EvidenceRef
    numbers: list[float] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)


class Evidence:
    """Everything an answer may legitimately draw on, indexed for lookup."""

    def __init__(
        self,
        question: str,
        rows: Sequence[Mapping[str, Any]],
        enrichment: Mapping[str, Any],
        *,
        sql: str = "",
    ) -> None:
        self.question = question
        # How the rows were chosen: shown to the judge for claims about the selection.
        self.sql = sql
        self.rows = list(rows[:MAX_EVIDENCE_ROWS])
        self.total_rows = len(rows)
        self.items: dict[str, _Item] = {}
        self._question_numbers = extract_facts(question).numbers
        self._derived: list[tuple[float, str]] | None = None
        self._gaps: list[tuple[float, int, int]] | None = None
        self._sums: list[tuple[float, int, int]] | None = None

        for i, row in enumerate(self.rows):
            cells = ", ".join(f"{k}: {_display(v)}" for k, v in list(row.items())[:4])
            label = f"Row {i + 1} · {cells}"
            self._add(
                EvidenceRef(id=f"row:{i}", kind="row", label=label, row_index=i),
                numbers=[float(v) for v in row.values() if _is_number(v)],
                texts=[str(v) for v in row.values() if v is not None and not _is_number(v)],
            )
        self._add(
            EvidenceRef(
                id="meta:row_count",
                kind="meta",
                label=f"{self.total_rows} rows returned",
                value=self.total_rows,
            ),
            numbers=[float(self.total_rows)],
        )
        self._add_aggregates()
        self._add_live(enrichment)

    def _add(
        self, ref: EvidenceRef, *, numbers: Sequence[float] = (), texts: Sequence[str] = ()
    ) -> None:
        self.items[ref.id] = _Item(ref=ref, numbers=list(numbers), texts=list(texts))

    def _add_count(self, item_id: str, label: str, value: int, column: str) -> None:
        ref = EvidenceRef(id=item_id, kind="aggregate", label=label, column=column, value=value)
        self._add(ref, numbers=[float(value)])

    def _add_aggregates(self) -> None:
        # Counts answer "how many" claims: "two companies are listed".
        cells: dict[str, list[Any]] = {}
        for row in self.rows:
            for col, value in row.items():
                cells.setdefault(col, []).append(value)
        for col, values in cells.items():
            present = [v for v in values if v is not None]
            distinct = {str(v) for v in present}
            self._add_count(
                f"agg:{col}.non_null", f"{col} set in {len(present)} rows", len(present), col
            )
            self._add_count(
                f"agg:{col}.distinct", f"{len(distinct)} distinct {col}", len(distinct), col
            )
            if all(isinstance(v, str) for v in present) and len(distinct) <= 20:
                for text in sorted(distinct):
                    n = sum(v == text for v in present)
                    self._add_count(f"agg:{col}[{text}].count", f"{n} rows: {col} = {text}", n, col)

        columns: dict[str, list[float]] = {}
        for row in self.rows:
            for col, value in row.items():
                if _is_number(value):
                    columns.setdefault(col, []).append(float(value))
        for col, values in columns.items():
            if len(values) < 2:
                continue
            stats = {
                "sum": math.fsum(values),
                "mean": statistics.fmean(values),
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
                "count": float(len(values)),
            }
            for name, value in stats.items():
                self._add(
                    EvidenceRef(
                        id=f"agg:{col}.{name}",
                        kind="aggregate",
                        label=f"{name} of {col} = {_display(value)}",
                        column=col,
                        value=value,
                    ),
                    numbers=[value],
                )

    def _add_live(self, enrichment: Mapping[str, Any]) -> None:
        for quote in enrichment.get("market_data", []):
            ticker = str(quote.get("ticker", ""))
            self._add(
                EvidenceRef(
                    id=f"market:{ticker}", kind="market_data", label=f"Live quote: {ticker}"
                ),
                numbers=[float(v) for v in quote.values() if _is_number(v)],
                texts=[str(v) for v in quote.values() if isinstance(v, str)],
            )
        for i, filing in enumerate(enrichment.get("sec_filings", [])):
            label = (
                f"{filing.get('ticker', '')} {filing.get('form', '')} "
                f"filed {filing.get('filing_date', '')}"
            )
            self._add(
                EvidenceRef(id=f"filing:{i}", kind="sec_filing", label=label),
                texts=[str(v) for v in filing.values() if v is not None],
            )

    # -- lookups ------------------------------------------------------------------------
    def _derived_values(self) -> list[tuple[float, str]]:
        """Ratios and relative differences an answer may compute from the rows."""
        if self._derived is not None:
            return self._derived
        derived: list[tuple[float, str]] = []
        window = self.rows[:_DERIVED_ROWS]

        def pairs(values: Sequence[tuple[int, float]], source: str | None) -> None:
            for i, a in values:
                for j, b in values:
                    if i != j and b:
                        ref = source or f"row:{i}"
                        derived.append((a / b, ref))
                        derived.append(((a - b) / abs(b), ref))

        for i, row in enumerate(window):  # within a row, e.g. net_income / revenue
            nums = [float(v) for v in row.values() if _is_number(v)]
            pairs(list(enumerate(nums)), f"row:{i}")
        columns: dict[str, list[tuple[int, float]]] = {}
        for i, row in enumerate(window):
            for col, value in row.items():
                if _is_number(value):
                    columns.setdefault(col, []).append((i, float(value)))
        for col, values in columns.items():  # across rows, e.g. growth or share
            total = math.fsum(v for _, v in values)
            if total:
                derived.extend((v / total, f"agg:{col}.sum") for _, v in values)
            pairs(values, None)
        self._derived = derived
        return derived

    def match_number(self, fact: NumberFact, rows: set[int] | None = None) -> list[str]:
        """Evidence ids holding a value equal to `fact` at its stated precision.

        `rows`, when given, restricts row evidence to those row indices. Ids of
        values computed from the rows (ratios, shares) are prefixed with "~".
        """
        tol = max(fact.tolerance, abs(fact.value) * 1e-9)

        def equal(value: float) -> bool:
            targets = (value, value * 100) if fact.percent else (value,)
            return any(abs(abs(t) - abs(fact.value)) <= tol for t in targets)

        hits: list[str] = []
        for item_id, item in self.items.items():
            kind = item.ref.kind
            if rows is not None and (
                (kind == "row" and item.ref.row_index not in rows)
                # An order statistic is one row's value, so it must be that row's.
                or item_id.endswith((".min", ".max", ".median"))
            ):
                continue
            if fact.small_count:
                # A bare small integer is a count: only counts and whole cells support it.
                if kind == "aggregate" and not item_id.endswith(_COUNT_SUFFIXES):
                    continue
                values = [v for v in item.numbers if v == int(v)]
            else:
                values = item.numbers
            if any(equal(v) for v in values):
                hits.append(item_id)
        if not hits and (fact.percent or fact.multiple):
            for value, source in self._derived_values():
                if (
                    rows is not None
                    and source.startswith("row:")
                    and int(source.removeprefix("row:")) not in rows
                ):
                    continue
                if equal(value):
                    return [f"~{source}"]
        return hits

    def _differences(self) -> list[tuple[float, int, int]]:
        """Gaps between two values of a row (close vs. average) or of a column (A vs. B)."""
        if self._gaps is not None:
            return self._gaps
        gaps: list[tuple[float, int, int]] = []
        columns: dict[str, list[tuple[int, float]]] = {}
        for i, row in enumerate(self.rows[:_DERIVED_ROWS]):
            nums = [float(v) for v in row.values() if _is_number(v)]
            gaps.extend((abs(a - b), i, i) for k, a in enumerate(nums) for b in nums[k + 1 :])
            for col, value in row.items():
                if _is_number(value):
                    columns.setdefault(col, []).append((i, float(value)))
        for values in columns.values():
            gaps.extend(
                (abs(a - b), i, j) for k, (i, a) in enumerate(values) for j, b in values[k + 1 :]
            )
        self._gaps = gaps
        return gaps

    def _pair_sums(self) -> list[tuple[float, int, int]]:
        """Sums of two rows' values in one column ("the top two together")."""
        if self._sums is not None:
            return self._sums
        columns: dict[str, list[tuple[int, float]]] = {}
        for i, row in enumerate(self.rows[:_DERIVED_ROWS]):
            for col, value in row.items():
                if _is_number(value):
                    columns.setdefault(col, []).append((i, float(value)))
        self._sums = [
            (a + b, i, j)
            for values in columns.values()
            for k, (i, a) in enumerate(values)
            for j, b in values[k + 1 :]
        ]
        return self._sums

    def match_difference(
        self, fact: NumberFact, rows: set[int] | None = None, *, sums: bool = False
    ) -> list[str]:
        """A row id, prefixed "~", when `fact` equals the gap between two values
        (or, with `sums`, their sum).

        `rows`, when given, requires both values to come from those rows.
        """
        if fact.percent or fact.multiple or fact.small_count:
            return []
        tol = max(fact.tolerance, abs(fact.value) * 1e-9)
        pairs = self._pair_sums() if sums else self._differences()
        for value, i, j in pairs:
            if rows is not None and not (i in rows and j in rows):
                continue
            if abs(abs(value) - abs(fact.value)) <= tol:
                return [f"~row:{i}"]
        return []

    def check_bound(
        self, fact: NumberFact, *, rows: set[int] | None = None, scope: int | None = None
    ) -> tuple[bool, str] | None:
        """Whether `fact` bounds every row of some column ("all exceed $180M").

        Only columns of a comparable magnitude (within 10x) are considered; a
        percentage also matches fractions. `scope` ("the top 3") limits the
        check to the first or the last `scope` rows, whichever order the query
        used. Returns (holds, evidence id), or None when no column compares.
        """
        indices = [i for i in range(len(self.rows)) if rows is None or i in rows]
        windows = [indices[:scope], indices[-scope:]] if scope else [indices]
        target = abs(fact.value)
        columns = dict.fromkeys(c for r in self.rows for c, v in r.items() if _is_number(v))
        violation = ""
        for col in columns:
            for scale in (1.0, 100.0) if fact.percent else (1.0,):
                for window in windows:
                    values = [
                        (i, float(self.rows[i][col]) * scale)
                        for i in window
                        if _is_number(self.rows[i].get(col))
                    ]
                    if not values or not (
                        target / 10 <= statistics.median(abs(v) for _, v in values) <= target * 10
                    ):
                        continue
                    breaking = [
                        i
                        for i, v in values
                        if (v < fact.value if fact.bound == "min" else v > fact.value)
                    ]
                    if not breaking:
                        return True, f"agg:{col}.{fact.bound}"
                    violation = violation or f"row:{breaking[0]}"
        return (False, violation) if violation else None

    def in_question(self, fact: NumberFact) -> bool:
        return any(
            abs(q.value - fact.value) <= max(q.tolerance, fact.tolerance)
            for q in self._question_numbers
        )

    def rows_mentioning(self, entity: str) -> set[int]:
        needle = entity.lower()
        return {
            item.ref.row_index
            for item in self.items.values()
            if item.ref.kind == "row" and item.ref.row_index is not None
            for text in item.texts
            if len(text) >= 2 and (needle in text.lower() or text.lower() in needle)
        }

    def mentions(self, needle: str) -> list[str]:
        """Evidence ids whose text, column names or question contain `needle`."""
        lowered = needle.lower()
        hits = [
            i for i, item in self.items.items() if any(lowered in t.lower() for t in item.texts)
        ]
        if hits:
            return hits
        columns = {c.lower().replace("_", " ") for row in self.rows[:1] for c in row}
        if any(lowered in c or c in lowered for c in columns):
            return ["row:0"]
        return ["question"] if lowered in self.question.lower() else []

    def ref(self, item_id: str) -> EvidenceRef | None:
        if item_id == "question":
            return EvidenceRef(id="question", kind="question", label="Stated in the question")
        if item_id == "sql" and self.sql:
            return EvidenceRef(id="sql", kind="meta", label="How the query selected the rows")
        item = self.items.get(item_id.removeprefix("~"))
        return item.ref if item else None

    def judge_block(self) -> str:
        lines = [f"[sql] {self.sql}"] if self.sql else []
        lines += [
            f"[row:{i}] {json.dumps(r, default=str)}" for i, r in enumerate(self.rows[:_JUDGE_ROWS])
        ]
        if self.total_rows > _JUDGE_ROWS:
            lines.append(f"(first {_JUDGE_ROWS} of {self.total_rows} rows shown)")
        lines += [
            f"[{item_id}] {item.ref.label}"
            for item_id, item in self.items.items()
            if item.ref.kind != "row"
        ]
        for item_id, item in self.items.items():
            if item.ref.kind == "market_data":
                lines.append(f"[{item_id}] values: {item.numbers}")
        return "\n".join(lines)[:_JUDGE_EVIDENCE_CHARS]


# --- Deterministic checking -----------------------------------------------------------


@dataclass(slots=True)
class FactCheck:
    verdict: Verdict = "unverifiable"
    evidence: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    via_derived: bool = False
    # Sentence-opening names not found in the evidence: grammar or invention.
    unresolved: list[str] = field(default_factory=list)

    @property
    def settled(self) -> bool:
        """Whether the deterministic verdict needs no second opinion."""
        return self.verdict == "supported" and not (self.via_derived or self.unresolved)


def _within_result(fact: NumberFact, total_rows: int) -> bool:
    return fact.value == int(fact.value) and 1 <= fact.value <= max(total_rows, 1)


def check_claim(claim: Claim, evidence: Evidence) -> FactCheck:
    facts = extract_facts(claim.text)
    result = FactCheck()
    # A rank or window inside the result ("the top 3", "the last 10 days") is
    # not a value to look up; it narrows which rows a bound speaks about.
    ranks = [f for f in facts.numbers if f.positional and _within_result(f, evidence.total_rows)]
    numbers = [f for f in facts.numbers if f not in ranks]
    # A bound ("above $180M") equals no cell: on every row ("all exceed") it is
    # checked against whole columns; otherwise the judge checks it.
    bounds = [f for f in numbers if f.bound]
    numbers = [f for f in numbers if not f.bound]
    if not (numbers or facts.years or facts.dates or facts.entities or bounds):
        result.reasons.append("no checkable facts")
        return result

    ok = 0
    # Names give context; when a claim states values, only the values can make it
    # (partly) supported, so a right name cannot dilute a wrong number.
    has_values = bool(numbers or facts.years or facts.dates)
    compares = bool(_DIFFERENCE_CUE.search(claim.text))
    combines = bool(_SUM_CUE.search(claim.text))
    every_row = bool(_UNIVERSAL.search(claim.text)) and not _AGGREGATE_CUE.search(claim.text)
    open_bounds: list[str] = []

    def fail(value: str, reason: str) -> None:
        result.unsupported.append(value)
        result.reasons.append(reason)

    entity_rows: set[int] = set()
    for entity in facts.entities:
        hits = evidence.mentions(entity)
        if hits:
            ok += 0 if has_values else 1
            result.evidence.extend(hits[:1])
            entity_rows |= evidence.rows_mentioning(entity)
        else:
            fail(entity, f'"{entity}" does not appear in the evidence')
    for entity in facts.weak_entities:
        rows = evidence.rows_mentioning(entity)
        entity_rows |= rows
        if not rows and not evidence.mentions(entity):
            result.unresolved.append(entity)

    for fact in numbers:
        if evidence.in_question(fact):
            ok += 1
            continue
        hits = evidence.match_number(fact, rows=entity_rows or None)
        if entity_rows and not hits and evidence.match_number(fact):
            fail(fact.text, f"{fact.text} belongs to a different row than the one named")
            continue
        if not hits and compares:
            # "a gap of $92M": the difference of two values. With this many
            # candidate pairs a match may be coincidental, so the judge confirms.
            hits = evidence.match_difference(fact, rows=entity_rows or None)
            result.via_derived = result.via_derived or bool(hits)
        if not hits and combines:
            # "the top two together hold $540M": the sum of two rows' values.
            hits = evidence.match_difference(fact, rows=entity_rows or None, sums=True)
            result.via_derived = result.via_derived or bool(hits)
        if not hits:
            fail(fact.text, f"{fact.text} matches no value in the evidence")
            continue
        ok += 1
        result.evidence.extend(hits[:2])
        # A ratio found among all rows may be a coincidence and needs the judge;
        # within the named entity's own rows the candidates are too few for that.
        result.via_derived = result.via_derived or (hits[0].startswith("~") and not entity_rows)

    checked_bounds = 0
    scope = int(ranks[0].value) if ranks else None
    for fact in bounds:
        checked = (
            evidence.check_bound(fact, rows=entity_rows or None, scope=scope) if every_row else None
        )
        if checked is None:
            open_bounds.append(fact.text)
            continue
        holds, ref = checked
        result.evidence.append(ref)
        if holds:
            ok += 1
            checked_bounds += 1
            # Some column satisfies it; whether that is the column meant is the judge's call.
            result.via_derived = True
        else:
            fail(fact.text, f"{fact.text} does not hold for every row ({ref})")

    for year in facts.years:
        year_fact = NumberFact(text=year, value=float(year), tolerance=0.0)
        if year in evidence.question or evidence.mentions(year) or evidence.match_number(year_fact):
            ok += 1
        else:
            fail(year, f"{year} does not appear in the evidence")

    for needle in facts.dates:
        hits = evidence.mentions(needle)
        if hits:
            ok += 1
            result.evidence.extend(hits[:1])
        else:
            shown = needle.lstrip("-")
            fail(shown, f"{shown} does not appear in the evidence")

    if result.unsupported:
        result.verdict = "partially_supported" if ok else "unsupported"
    elif (has_values or checked_bounds) and not open_bounds:
        result.verdict = "supported"
    else:
        # Names alone cannot verify what is said about them, nor can matching
        # values verify a bound on a total or a single row stated alongside them.
        result.verdict = "unverifiable"
        result.reasons.append(
            f"{', '.join(open_bounds)}: a bound the checks cannot compare"
            if open_bounds
            else "names match the evidence; the statement itself is not checkable"
        )
    return result


# --- LLM judge ---------------------------------------------------------------------------

_JUDGE_PROMPT = """\
You are a strict fact checker for answers about financial data. For each claim, \
decide whether the evidence supports it:
- supported: every fact in the claim is stated in, or directly computable from, \
the evidence;
- partially_supported: some facts are supported but others are not, or the claim \
overstates the evidence;
- unsupported: the claim contradicts the evidence or its facts are absent from it.
Judge only against the evidence, never against outside knowledge. The [sql] line \
is the query that produced the rows: its filters, ordering and LIMIT support \
claims about how the rows were selected ("only listed companies", "the highest"). \
Check bounds ("above $180M") and differences against the row values. List the \
ids of the evidence lines that support or refute each claim."""
# Room for the verdicts plus a reasoning model's hidden reasoning, which counts
# against the same limit: a cut-off reply is invalid JSON.
_JUDGE_MAX_TOKENS = 4_000


class JudgedClaim(BaseModel):
    id: str
    verdict: Literal["supported", "partially_supported", "unsupported"]
    evidence: list[str] = Field(default_factory=list, max_length=8)
    reason: str = Field(default="", max_length=300)


class JudgeOutput(BaseModel):
    verdicts: list[JudgedClaim]


# --- Agent -------------------------------------------------------------------------------

_CONFIDENCE: dict[Method, float] = {"deterministic": 0.9, "hybrid": 0.85, "llm": 0.7}
_STRICTNESS: list[Verdict] = ["unsupported", "partially_supported", "supported"]


def _combine(
    claim: Claim, check: FactCheck, judged: JudgedClaim | None, evidence: Evidence
) -> ClaimCheck:
    verdict: Verdict = check.verdict
    method: Method = "deterministic"
    reason = "; ".join(check.reasons) or "every fact matches the evidence"
    evidence_ids = check.evidence
    if judged is not None:
        method = "llm" if check.verdict == "unverifiable" else "hybrid"
        verdict = judged.verdict
        if check.verdict != "unverifiable":
            # The stricter verdict wins: a value found nowhere in the evidence
            # cannot be cleared by the judge, and the judge may catch what the
            # checks cannot (e.g. a ratio that only coincidentally matches).
            verdict = min(verdict, check.verdict, key=_STRICTNESS.index)
        if judged.reason:
            reason = f"{judged.reason} ({reason})" if check.unsupported else judged.reason
        evidence_ids = [*judged.evidence, *check.evidence]

    # "~row:0" (a value computed from row 0) and "row:0" cite the same row.
    unique = dict.fromkeys(i.removeprefix("~") for i in evidence_ids)
    refs = [r for r in (evidence.ref(i) for i in unique) if r is not None]
    confidence = 0.0
    if verdict != "unverifiable":
        confidence = _CONFIDENCE[method] - (0.2 if check.via_derived else 0.0)
    return ClaimCheck(
        id=claim.id,
        text=claim.text,
        source=claim.source,
        verdict=verdict,
        confidence=round(confidence, 2),
        method=method,
        reason=reason,
        evidence=refs[:_MAX_REFS],
        unsupported_values=check.unsupported,
    )


class VerificationAgent(Agent):
    name = "verification"

    def __init__(
        self, *, mode: VerificationMode, extractor: StructuredOutputExtractor | None = None
    ) -> None:
        self.mode = mode
        self._extractor = extractor

    async def run(
        self,
        question: str,
        rows: Sequence[Mapping[str, Any]],
        enrichment: Mapping[str, Any],
        *,
        answer: str,
        summary: str = "",
        insights: Sequence[str] = (),
        sql: str = "",
        trace: Trace,
    ) -> VerificationReport:
        if self.mode == "off":
            return VerificationReport(status="skipped", mode=self.mode)
        claims = extract_claims(answer, summary, insights)
        if not claims:
            self._record(trace, "skipped", "no claims to check")
            return VerificationReport(status="skipped", mode=self.mode)

        evidence = Evidence(question, rows, enrichment, sql=sql)
        checks = {c.id: check_claim(c, evidence) for c in claims}
        self._record(trace, "claims_checked", {cid: c.verdict for cid, c in checks.items()})

        judged: dict[str, JudgedClaim] = {}
        degraded = False
        uncertain = [c for c in claims if not checks[c.id].settled]
        if self.mode == "hybrid" and self._extractor is not None and uncertain:
            try:
                judged = await self._judge(self._extractor, question, uncertain, evidence)
                self._record(trace, "llm_judged", {cid: j.verdict for cid, j in judged.items()})
            except LLMError as exc:
                degraded = True
                logger.warning("Claim judge unavailable: %s", exc)
                self._record(trace, "llm_judge_failed", type(exc).__name__)

        results = [_combine(c, checks[c.id], judged.get(c.id), evidence) for c in claims]
        report = self._report(results, degraded=degraded, llm_judged=len(judged))
        self._record(
            trace,
            "verification_completed",
            report.model_dump(
                include={
                    "status",
                    "supported",
                    "partially_supported",
                    "unsupported",
                    "unverifiable",
                }
            ),
        )
        return report

    @staticmethod
    async def _judge(
        extractor: StructuredOutputExtractor,
        question: str,
        claims: Sequence[Claim],
        evidence: Evidence,
    ) -> dict[str, JudgedClaim]:
        wanted = {c.id for c in claims}
        claim_lines = "\n".join(f"[{c.id}] {c.text}" for c in claims)
        user = (
            f"Question: {question}\n\nEvidence:\n{evidence.judge_block()}\n\nClaims:\n{claim_lines}"
        )

        def covers_every_claim(output: JudgeOutput) -> None:
            missing = sorted(wanted - {v.id for v in output.verdicts})
            if missing:
                raise OutputRejected(f"verdicts missing for claims: {', '.join(missing)}")

        try:
            extraction = await extractor.extract(
                JudgeOutput,
                system=_JUDGE_PROMPT,
                user=user,
                purpose=PURPOSE,
                temperature=0.0,
                max_tokens=_JUDGE_MAX_TOKENS,
                validate=covers_every_claim,
            )
            output = extraction.value
        except StructuredOutputError as exc:
            # Well-formed but incomplete after the retries: keep what was judged.
            if not isinstance(exc.last_value, JudgeOutput):
                raise
            output = exc.last_value
        return {v.id: v for v in output.verdicts if v.id in wanted}

    def _report(
        self, results: list[ClaimCheck], *, degraded: bool, llm_judged: int
    ) -> VerificationReport:
        def count(verdict: str) -> int:
            return sum(r.verdict == verdict for r in results)

        supported, partial = count("supported"), count("partially_supported")
        unsupported, unverifiable = count("unsupported"), count("unverifiable")
        checkable = len(results) - unverifiable
        return VerificationReport(
            status="flagged" if unsupported or partial else "verified",
            mode=self.mode,
            degraded=degraded,
            claims=results,
            supported=supported,
            partially_supported=partial,
            unsupported=unsupported,
            unverifiable=unverifiable,
            score=round((supported + 0.5 * partial) / checkable, 3) if checkable else None,
            llm_judged=llm_judged,
        )
