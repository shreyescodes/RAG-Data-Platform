from datetime import date, timedelta

from app.agents.analysis import AnalysisAgent
from app.agents.base import Trace
from app.core.exceptions import LLMError
from app.services.structured_output import StructuredOutputExtractor
from tests.fakes import FakeChatModel


def Agent(llm: FakeChatModel) -> AnalysisAgent:
    return AnalysisAgent(StructuredOutputExtractor(llm))


ROWS = [{"name": "Apple Inc.", "revenue": 94.0e9}, {"name": "Microsoft", "revenue": 76.4e9}]


async def test_parses_llm_json() -> None:
    llm = FakeChatModel(analysis={"answer": "Apple leads.", "summary": "s", "insights": ["i"]})
    result = await Agent(llm).run("who leads?", "SELECT 1", ROWS, {}, Trace())

    assert result.status == "completed"
    assert result.answer == "Apple leads."
    assert result.insights == ["i"]
    assert llm.calls[0]["json_mode"] is True
    assert "Results (2 of 2 rows)" in llm.calls[0]["user"]


def _daily_closes(days: int) -> list[dict[str, object]]:
    start = date(2026, 1, 1)
    return [
        {"date": (start + timedelta(days=i)).isoformat(), "close": 100.0 + i} for i in range(days)
    ]


async def test_long_results_reach_the_model_from_first_row_to_last() -> None:
    llm = FakeChatModel()
    rows = _daily_closes(120)
    rows[60]["close"] = 999.0

    await Agent(llm).run("NVDA over 120 days", "SELECT 1", rows, {}, Trace())

    prompt = llm.calls[0]["user"]
    assert "Results: 120 rows." in prompt
    assert '"date": "2026-01-01"' in prompt
    assert f'"date": "{rows[-1]["date"]}"' in prompt
    assert '"highest": {"value": 999.0, "row": {"date": "2026-03-02"}}' in prompt


async def test_long_series_send_patterns_computed_from_every_row() -> None:
    llm = FakeChatModel()
    rows = [{**row, "ma_50": 150.0} for row in _daily_closes(120)]

    await Agent(llm).run("q", "SELECT 1", rows, {}, Trace())

    prompt = llm.calls[0]["user"]
    assert "Patterns computed from every row" in prompt
    assert "close was above ma_50 on 69 of 120 rows and below it on 50." in prompt


async def test_results_without_a_date_series_list_no_patterns() -> None:
    llm = FakeChatModel()
    rows = [{"name": f"Fund {i}", "value": float(i)} for i in range(40)]

    await Agent(llm).run("q", "SELECT 1", rows, {}, Trace())

    assert "Patterns computed" not in llm.calls[0]["user"]


async def test_wide_rows_never_cut_off_the_end_of_a_long_result() -> None:
    llm = FakeChatModel()
    rows = [{**row, "note": "x" * 900} for row in _daily_closes(120)]

    await Agent(llm).run("q", "SELECT 1", rows, {}, Trace())

    prompt = llm.calls[0]["user"]
    assert "(truncated)" not in prompt.rsplit("selected rows", 1)[1]
    assert f'"date": "{rows[-1]["date"]}"' in prompt.rsplit("selected rows", 1)[1]


async def test_includes_enrichment_in_prompt() -> None:
    llm = FakeChatModel()
    await Agent(llm).run("q", "SELECT 1", ROWS, {"market_data": [{"t": 1}]}, Trace())
    assert "Live data:" in llm.calls[0]["user"]


async def test_no_rows_skips_llm() -> None:
    llm = FakeChatModel()
    result = await Agent(llm).run("q", "SELECT 1", [], {}, Trace())
    assert result.status == "completed"
    assert "No records" in result.answer
    assert llm.calls == []


async def test_malformed_json_falls_back() -> None:
    llm = FakeChatModel(analysis="not json")
    result = await Agent(llm).run("q", "SELECT 1", ROWS, {}, Trace())
    assert result.status == "degraded"
    assert result.answer == "The query returned 2 row(s)."
    assert len(llm.calls) == 3  # retried with feedback before falling back


async def test_llm_error_falls_back() -> None:
    llm = FakeChatModel(fail_with=LLMError("timeout"))
    trace = Trace()
    result = await Agent(llm).run("q", "SELECT 1", ROWS, {}, trace)
    assert result.status == "degraded"
    assert trace.entries[-1].step == "fallback"


async def test_answers_from_live_data_when_no_rows() -> None:
    llm = FakeChatModel(analysis={"answer": "NVDA is at $217.94.", "insights": []})
    live = {"market_data": [{"ticker": "NVDA", "current_price": 217.94}]}

    result = await Agent(llm).run("NVDA price?", "", [], live, Trace())

    assert result.answer == "NVDA is at $217.94."
    prompt = llm.calls[0]["user"]
    assert "no data for this question" in prompt
    assert "SQL:" not in prompt


async def test_live_data_only_fallback_is_degraded() -> None:
    llm = FakeChatModel(fail_with=LLMError("down"))
    result = await Agent(llm).run("q", "", [], {"market_data": [{}]}, Trace())
    assert result.status == "degraded"
    assert "Live market data" in result.answer


async def test_invalid_reply_is_retried() -> None:
    llm = FakeChatModel(replies={"analysis": ['{"answer": ""}']})
    trace = Trace()
    result = await Agent(llm).run("q", "SELECT 1", ROWS, {}, trace)
    assert result.status == "completed"
    assert result.answer == "There are three companies."
    assert trace.entries[-1].detail == {"insights": 2, "attempts": 2}
