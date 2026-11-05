import json
from typing import Any

import pytest

from app.agents.base import Trace
from app.agents.verification import (
    Evidence,
    VerificationAgent,
    check_claim,
    extract_claims,
    extract_facts,
)
from app.core.exceptions import LLMError
from app.services.structured_output import StructuredOutputExtractor
from tests.fakes import FakeChatModel

ROWS: list[dict[str, Any]] = [
    {"name": "Apple Inc.", "ticker": "AAPL", "revenue": 94.0e9, "net_income": 23.4e9},
    {"name": "Microsoft Corporation", "ticker": "MSFT", "revenue": 76.4e9, "net_income": 27.2e9},
    {"name": "Atlas Analytics", "ticker": None, "revenue": 1.2e9, "net_income": -0.1e9},
]
QUESTION = "Revenue and net income for the last 2 quarters of 2026"


def _verdict(text: str, rows: list[dict[str, Any]] = ROWS, enrichment: Any = None) -> str:
    evidence = Evidence(QUESTION, rows, enrichment or {})
    (claim,) = extract_claims(text)
    return check_claim(claim, evidence).verdict


# --- Fact extraction ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value", "tolerance"),
    [
        ("$94.0B", 94.0e9, 0.05e9),
        ("$1.2 billion", 1.2e9, 0.05e9),
        ("12,000,000", 12e6, 0.5),
        ("4.5%", 4.5, 0.05),
        ("3x", 3.0, 0.5),
        ("-$0.1B", -0.1e9, 0.05e9),
        ("250k", 250e3, 500),
    ],
)
def test_numbers_carry_value_and_precision(text: str, value: float, tolerance: float) -> None:
    (fact,) = extract_facts(f"It was {text} overall").numbers
    assert fact.value == pytest.approx(value)
    assert fact.tolerance == pytest.approx(tolerance)


def test_years_dates_and_non_numbers_are_separated() -> None:
    facts = extract_facts(
        "In 2026 the 10-K filed on 2026-02-01 showed a 50-day average for Q3, its 1st."
    )
    assert facts.years == ("2026",)
    assert facts.dates == ("2026-02-01",)
    assert facts.numbers == ()


def test_number_words_are_small_counts() -> None:
    (fact,) = extract_facts("There are three companies").numbers
    assert (fact.value, fact.small_count) == (3.0, True)


def test_entities_skip_grammar_and_domain_terms() -> None:
    facts = extract_facts("Apple's ARR beats Microsoft Corporation and Bank of America in SaaS.")
    assert facts.entities == ("Microsoft Corporation", "Bank of America")
    assert facts.weak_entities == ("Apple",)


def test_claims_split_on_sentences_and_semicolons_not_abbreviations() -> None:
    claims = extract_claims(
        "Apple Inc. leads. Microsoft follows; Atlas trails.",
        "Apple Inc. leads.",
        ["Two are listed."],
    )
    assert [(c.id, c.text, c.source) for c in claims] == [
        ("c1", "Apple Inc. leads.", "answer"),
        ("c2", "Microsoft follows", "answer"),
        ("c3", "Atlas trails.", "answer"),
        ("c4", "Two are listed.", "insight"),
    ]


# --- Deterministic checks ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "verdict"),
    [
        ("Apple Inc. leads with revenue of $94.0B, ahead of Microsoft at $76.4B.", "supported"),
        ("Apple reported revenue of about $94 billion.", "supported"),
        ("Apple's revenue reached $120B.", "unsupported"),
        ("Apple Inc. had $94.0B in revenue and $99B in net income.", "partially_supported"),
        ("Microsoft had the highest revenue at $94B.", "unsupported"),  # misattributed
        ("Microsoft's net margin is about 35.6%.", "supported"),  # computed from its row
        ("Total revenue across the three companies is $171.6B.", "supported"),
        ("Two companies have a ticker.", "supported"),  # count of non-null tickers
        ("There are five companies.", "unsupported"),
        ("Results cover the last 2 quarters of 2026.", "supported"),  # from the question
        ("Revenue fell in 2019.", "unsupported"),
        ("Tesla Motors earned $5B.", "unsupported"),
        ("Atlas leads by a wide margin.", "unverifiable"),
    ],
)
def test_check_claim(text: str, verdict: str) -> None:
    assert _verdict(text) == verdict


def test_percentages_match_values_stored_as_fractions() -> None:
    rows = [{"stage": "Series A", "churn_rate": 0.012}, {"stage": "Seed", "churn_rate": 0.031}]
    assert _verdict("Series A churn is 1.2% a month.", rows) == "supported"
    assert _verdict("Series A churn is 3.1% a month.", rows) == "unsupported"


def test_dates_must_appear_in_the_evidence() -> None:
    rows = [{"ticker": "AAPL", "date": "2026-10-27", "close_price": 251.3}]
    assert _verdict("AAPL closed at $251.30 on 2026-10-27.", rows) == "supported"
    assert _verdict("AAPL closed at $251.30 on 2026-10-28.", rows) == "partially_supported"


def test_live_market_data_is_evidence() -> None:
    live = {"market_data": [{"ticker": "NVDA", "current_price": 217.94, "market_cap": 5.3e12}]}
    assert _verdict("NVDA trades at $217.94 with a $5.3T market cap.", [], live) == "supported"
    assert _verdict("NVDA trades at $300.", [], live) == "unsupported"


# --- Agent ---------------------------------------------------------------------------------


def _agent(llm: FakeChatModel | None = None, mode: str = "hybrid") -> VerificationAgent:
    extractor = StructuredOutputExtractor(llm) if llm is not None else None
    return VerificationAgent(mode=mode, extractor=extractor)  # type: ignore[arg-type]


async def _run(agent: VerificationAgent, answer: str, **kwargs: Any):
    return await agent.run(QUESTION, ROWS, {}, answer=answer, trace=Trace(), **kwargs)


async def test_heuristic_mode_needs_no_llm() -> None:
    report = await _run(
        _agent(mode="heuristic"),
        "Apple Inc. had $94.0B in revenue.",
        summary="Microsoft earned $27.2B.",
        insights=["Revenue hit $300B."],
    )
    assert report.status == "flagged"
    assert (report.supported, report.unsupported) == (2, 1)
    assert report.score == pytest.approx(2 / 3, abs=1e-3)
    flagged = report.claims[2]
    assert flagged.source == "insight"
    assert flagged.unsupported_values == ["$300B"]
    assert "matches no value" in flagged.reason
    assert report.claims[0].evidence[0].row_index == 0


async def test_judge_is_only_asked_about_uncertain_claims() -> None:
    llm = FakeChatModel()
    report = await _run(_agent(llm), "Apple Inc. had $94.0B in revenue. Atlas trails the pack.")

    (call,) = llm.calls
    assert call["purpose"] == "verification"
    assert "[c2] Atlas trails the pack." in call["user"]
    assert "[c1]" not in call["user"]  # settled deterministically
    assert "[row:0]" in call["user"]
    assert report.llm_judged == 1
    assert report.claims[1].method == "llm"
    assert report.claims[1].verdict == "supported"
    assert report.status == "verified"


async def test_judge_cannot_clear_an_unmatched_number() -> None:
    llm = FakeChatModel()  # the fake judge marks everything supported
    report = await _run(_agent(llm), "Apple's revenue reached $120B.")
    claim = report.claims[0]
    assert claim.method == "hybrid"
    assert claim.verdict == "unsupported"


async def test_judge_can_flag_what_the_checks_could_not() -> None:
    llm = FakeChatModel(
        verification={
            "verdicts": [
                {
                    "id": "c1",
                    "verdict": "unsupported",
                    "evidence": ["row:2"],
                    "reason": "Atlas is last",
                }
            ]
        }
    )
    report = await _run(_agent(llm), "Atlas leads by a wide margin.")
    claim = report.claims[0]
    assert claim.verdict == "unsupported"
    assert claim.reason == "Atlas is last"
    assert claim.evidence[0].id == "row:2"
    assert claim.confidence == 0.7


async def test_judge_missing_a_claim_is_retried() -> None:
    complete = json.dumps({"verdicts": [{"id": "c1", "verdict": "supported"}]})
    llm = FakeChatModel(replies={"verification": ['{"verdicts": []}', complete]})
    report = await _run(_agent(llm), "Atlas trails the pack.")
    assert len(llm.calls) == 2
    assert "verdicts missing for claims: c1" in llm.calls[1]["user"]
    assert report.claims[0].verdict == "supported"


async def test_judge_failure_degrades_to_deterministic_checks() -> None:
    llm = FakeChatModel(fail_with=LLMError("down"))
    trace = Trace()
    report = await _agent(llm).run(
        QUESTION, ROWS, {}, answer="Atlas trails. Apple's revenue reached $120B.", trace=trace
    )
    assert report.degraded is True
    assert report.claims[0].verdict == "unverifiable"
    assert report.claims[1].verdict == "unsupported"
    assert "llm_judge_failed" in [e.step for e in trace.entries]


async def test_off_mode_and_empty_answers_are_skipped() -> None:
    assert (await _run(_agent(mode="off"), "Apple Inc. had $94.0B.")).status == "skipped"
    assert (await _run(_agent(mode="heuristic"), "OK")).status == "skipped"


async def test_incomplete_judgement_keeps_the_verdicts_given() -> None:
    partial = json.dumps({"verdicts": [{"id": "c1", "verdict": "unsupported", "reason": "no"}]})
    llm = FakeChatModel(replies={"verification": [partial] * 3})
    report = await _run(_agent(llm), "Atlas trails the pack. Beacon is steady.")
    assert len(llm.calls) == 3
    assert report.claims[0].verdict == "unsupported"
    assert report.claims[1].verdict == "unverifiable"  # left to the deterministic result
    assert report.degraded is False


async def test_ratios_inside_a_named_entitys_row_need_no_judge() -> None:
    llm = FakeChatModel()
    report = await _run(_agent(llm), "Microsoft's net margin of 35.6% exceeds Apple's 24.9%.")
    assert report.claims[0].verdict == "supported"
    assert report.claims[0].method == "deterministic"
    assert llm.calls == []
    # Without a named entity a computed ratio may be coincidental: ask the judge.
    await _run(_agent(llm), "The best margin in the group is 35.6%.")
    assert len(llm.calls) == 1


def test_evidence_labels_are_readable() -> None:
    evidence = Evidence(QUESTION, [{"churn": 0.0211357142857143, "revenue": 94.0e9, "n": 3}], {})
    assert (
        evidence.items["row:0"].ref.label
        == "Row 1 · churn: 0.0211357, revenue: 94,000,000,000, n: 3"
    )
