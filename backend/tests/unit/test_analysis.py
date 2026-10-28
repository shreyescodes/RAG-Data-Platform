from app.agents.analysis import AnalysisAgent
from app.agents.base import Trace
from app.core.exceptions import LLMError
from tests.fakes import FakeChatModel

ROWS = [{"name": "Apple Inc.", "revenue": 94.0e9}, {"name": "Microsoft", "revenue": 76.4e9}]


async def test_parses_llm_json() -> None:
    llm = FakeChatModel(analysis={"answer": "Apple leads.", "summary": "s", "insights": ["i"]})
    result = await AnalysisAgent(llm).run("who leads?", "SELECT 1", ROWS, {}, Trace())

    assert result.status == "completed"
    assert result.answer == "Apple leads."
    assert result.insights == ["i"]
    assert llm.calls[0]["json_mode"] is True
    assert "Results (2 of 2 rows)" in llm.calls[0]["user"]


async def test_includes_enrichment_in_prompt() -> None:
    llm = FakeChatModel()
    await AnalysisAgent(llm).run("q", "SELECT 1", ROWS, {"market_data": [{"t": 1}]}, Trace())
    assert "Live data:" in llm.calls[0]["user"]


async def test_no_rows_skips_llm() -> None:
    llm = FakeChatModel()
    result = await AnalysisAgent(llm).run("q", "SELECT 1", [], {}, Trace())
    assert result.status == "completed"
    assert "No records" in result.answer
    assert llm.calls == []


async def test_malformed_json_falls_back() -> None:
    llm = FakeChatModel(analysis="not json")
    result = await AnalysisAgent(llm).run("q", "SELECT 1", ROWS, {}, Trace())
    assert result.status == "degraded"
    assert result.answer == "The query returned 2 row(s)."


async def test_llm_error_falls_back() -> None:
    llm = FakeChatModel(fail_with=LLMError("timeout"))
    trace = Trace()
    result = await AnalysisAgent(llm).run("q", "SELECT 1", ROWS, {}, trace)
    assert result.status == "degraded"
    assert trace.entries[-1].step == "fallback"


async def test_answers_from_live_data_when_no_rows() -> None:
    llm = FakeChatModel(analysis={"answer": "NVDA is at $217.94.", "insights": []})
    live = {"market_data": [{"ticker": "NVDA", "current_price": 217.94}]}

    result = await AnalysisAgent(llm).run("NVDA price?", "", [], live, Trace())

    assert result.answer == "NVDA is at $217.94."
    prompt = llm.calls[0]["user"]
    assert "no data for this question" in prompt
    assert "SQL:" not in prompt


async def test_live_data_only_fallback_is_degraded() -> None:
    llm = FakeChatModel(fail_with=LLMError("down"))
    result = await AnalysisAgent(llm).run("q", "", [], {"market_data": [{}]}, Trace())
    assert result.status == "degraded"
    assert "Live market data" in result.answer
