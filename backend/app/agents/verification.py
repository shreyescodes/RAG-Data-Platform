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
from dataclasses import dataclass, field
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


def _number_fact(match: re.Match[str]) -> NumberFact:
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
        if any(ch.isdigit() for ch in entity) and not entity.isupper():
            continue
        if opens_claim and len(words) == 1 and not entity.isupper():
            weak.append(entity)
        else:
            found.append(entity)
    return found, weak


def extract_facts(claim: str) -> Facts:
    dates = tuple(_ISO_DATE.findall(claim))
    text = _FILING_FORM.sub(" ", _ISO_DATE.sub(" ", claim))
    numbers: list[NumberFact] = []
    years: list[str] = []
    for match in _NUMBER.finditer(text):
        if _is_year(match):
            years.append(match.group("num"))
        else:
            numbers.append(_number_fact(match))
    for match in _NUMBER_WORD.finditer(text):
        value = float(_NUMBER_WORDS[match.group(1).lower()])
        numbers.append(
            NumberFact(text=match.group(1), value=value, tolerance=0.5, small_count=True)
        )
    entities, weak = _entities(claim)
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
        self, question: str, rows: Sequence[Mapping[str, Any]], enrichment: Mapping[str, Any]
    ) -> None:
        self.question = question
        self.rows = list(rows[:MAX_EVIDENCE_ROWS])
        self.total_rows = len(rows)
        self.items: dict[str, _Item] = {}
        self._question_numbers = extract_facts(question).numbers
        self._derived: list[tuple[float, str]] | None = None

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
                        label=f"{name} of {col} = {value:,.6g}",
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
        item = self.items.get(item_id.removeprefix("~"))
        return item.ref if item else None

    def judge_block(self) -> str:
        lines = [
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


def check_claim(claim: Claim, evidence: Evidence) -> FactCheck:
    facts = extract_facts(claim.text)
    result = FactCheck()
    if facts.empty:
        result.reasons.append("no checkable facts")
        return result

    ok = 0
    # Names give context; when a claim states values, only the values can make it
    # (partly) supported, so a right name cannot dilute a wrong number.
    has_values = bool(facts.numbers or facts.years or facts.dates)

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

    for fact in facts.numbers:
        if evidence.in_question(fact):
            ok += 1
            continue
        hits = evidence.match_number(fact, rows=entity_rows or None)
        if entity_rows and not hits and evidence.match_number(fact):
            fail(fact.text, f"{fact.text} belongs to a different row than the one named")
            continue
        if not hits:
            fail(fact.text, f"{fact.text} matches no value in the evidence")
            continue
        ok += 1
        result.evidence.extend(hits[:2])
        # A ratio found among all rows may be a coincidence and needs the judge;
        # within the named entity's own rows the candidates are too few for that.
        result.via_derived = result.via_derived or (hits[0].startswith("~") and not entity_rows)

    for year in facts.years:
        year_fact = NumberFact(text=year, value=float(year), tolerance=0.0)
        if year in evidence.question or evidence.mentions(year) or evidence.match_number(year_fact):
            ok += 1
        else:
            fail(year, f"{year} does not appear in the evidence")

    for date in facts.dates:
        hits = evidence.mentions(date)
        if hits:
            ok += 1
            result.evidence.extend(hits[:1])
        else:
            fail(date, f"{date} does not appear in the evidence")

    bad = len(result.unsupported)
    if bad == 0:
        # Names alone cannot verify what is said about them.
        result.verdict = "supported" if has_values else "unverifiable"
        if not has_values:
            result.reasons.append("names match the evidence; the statement itself is not checkable")
    else:
        result.verdict = "partially_supported" if ok else "unsupported"
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
Judge only against the evidence, never against outside knowledge. List the ids of \
the evidence lines that support or refute each claim."""


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

    refs = [r for r in (evidence.ref(i) for i in dict.fromkeys(evidence_ids)) if r is not None]
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
        trace: Trace,
    ) -> VerificationReport:
        if self.mode == "off":
            return VerificationReport(status="skipped", mode=self.mode)
        claims = extract_claims(answer, summary, insights)
        if not claims:
            self._record(trace, "skipped", "no claims to check")
            return VerificationReport(status="skipped", mode=self.mode)

        evidence = Evidence(question, rows, enrichment)
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
                max_tokens=1_500,
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
