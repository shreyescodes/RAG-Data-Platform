import pytest

from app.core.exceptions import LLMError, UnanswerableQueryError
from app.rag.schema_indexer import build_schema_catalog
from app.rag.sql_generator import CANNOT_ANSWER, SQLGenerator, extract_sql
from tests.fakes import FakeChatModel


@pytest.mark.parametrize(
    "completion",
    [
        "SELECT 1",
        "```sql\nSELECT 1\n```",
        "```\nSELECT 1\n```",
        "Here is the query:\n```sql\nSELECT 1\n```\nIt selects one.",
    ],
)
def test_extract_sql_strips_fences_and_prose(completion: str) -> None:
    assert extract_sql(completion) == "SELECT 1"


async def test_prompt_contains_schema_and_question() -> None:
    llm = FakeChatModel(sql="SELECT name FROM companies")
    tables = [build_schema_catalog()["companies"]]

    sql = await SQLGenerator(llm, max_rows=25).generate("list companies", tables)

    assert sql == "SELECT name FROM companies"
    call = llm.calls[0]
    assert "CREATE TABLE companies" in call["user"]
    assert "Question: list companies" in call["user"]
    assert "at most 25 rows" in call["system"]
    # Regression: tickers must be matched exactly, not via ILIKE on company names.
    assert "market_data.ticker = 'NVDA'" in call["system"]


async def test_cannot_answer_raises() -> None:
    llm = FakeChatModel(sql=CANNOT_ANSWER)
    with pytest.raises(UnanswerableQueryError):
        await SQLGenerator(llm, max_rows=10).generate("weather in Paris?", [])


async def test_empty_completion_raises() -> None:
    llm = FakeChatModel(sql="```sql\n```")
    with pytest.raises(LLMError):
        await SQLGenerator(llm, max_rows=10).generate("anything", [])
