import json

import pytest

from app.core.exceptions import UnanswerableQueryError, UnsafeSQLError
from app.rag.schema_indexer import build_schema_catalog
from app.rag.sql_generator import CANNOT_ANSWER, SQLGenerationOutput, SQLGenerator
from app.services.structured_output import (
    StructuredOutputError,
    StructuredOutputExtractor,
    json_schema_for,
)
from tests.fakes import FakeChatModel, sql_reply

CATALOG = build_schema_catalog()
TABLES = [CATALOG["companies"]]


def _generator(llm: FakeChatModel, *, max_rows: int = 25, attempts: int = 3) -> SQLGenerator:
    return SQLGenerator(
        StructuredOutputExtractor(llm, max_attempts=attempts),
        max_rows=max_rows,
        allowed_tables=CATALOG.keys(),
    )


async def test_prompt_contains_schema_question_and_json_contract() -> None:
    llm = FakeChatModel(sql="SELECT name FROM companies")

    generated = await _generator(llm).generate("list companies", TABLES)

    assert generated.raw_sql == "SELECT name FROM companies"
    assert generated.sql == "SELECT name FROM companies LIMIT 25"
    assert generated.output.explanation == "Scripted by the test."
    assert generated.output.confidence == 0.9
    assert len(generated.attempts) == 1
    call = llm.calls[0]
    assert call["purpose"] == "sql_generation"
    assert call["json_mode"] is True
    assert "CREATE TABLE companies" in call["user"]
    assert "Question: list companies" in call["user"]
    assert "at most 25 rows" in call["system"]
    assert '"answerable"' in call["system"]  # the JSON schema is in the prompt
    # Regression: tickers must be matched exactly, not via ILIKE on company names.
    assert "market_data.ticker = 'NVDA'" in call["system"]


async def test_not_answerable_raises() -> None:
    llm = FakeChatModel(sql=CANNOT_ANSWER)
    with pytest.raises(UnanswerableQueryError, match="No matching data"):
        await _generator(llm).generate("weather in Paris?", TABLES)


async def test_malformed_reply_is_retried_with_feedback() -> None:
    llm = FakeChatModel(sql="SELECT ticker FROM companies")
    llm.replies["sql_generation"] = ["SELECT ticker FROM companies", '{"answerable": true}']

    generated = await _generator(llm).generate("tickers", TABLES)

    assert generated.raw_sql == "SELECT ticker FROM companies"
    assert [a.ok for a in generated.attempts] == [False, False, True]
    second, third = llm.calls[1]["user"], llm.calls[2]["user"]
    assert "Your previous reply was rejected" in second
    assert "Invalid JSON" in second
    assert "SELECT ticker FROM companies" in second  # the bad reply is echoed back
    assert "Invalid JSON" not in third  # feedback describes the latest failure only
    assert "explanation: Field required" in third


async def test_unsafe_sql_is_fed_back_and_can_be_corrected() -> None:
    llm = FakeChatModel(sql="SELECT name FROM companies")
    llm.replies["sql_generation"] = [sql_reply("DELETE FROM companies")]

    generated = await _generator(llm).generate("remove them", TABLES)

    assert generated.raw_sql == "SELECT name FROM companies"
    assert generated.attempts[0].errors[0].startswith("SQL rejected by safety checks")
    assert "only SELECT queries are allowed" in llm.calls[1]["user"]


async def test_persistently_unsafe_sql_raises_unsafe_sql_error() -> None:
    llm = FakeChatModel(sql="DROP TABLE companies")
    with pytest.raises(UnsafeSQLError) as info:
        await _generator(llm).generate("drop it", TABLES)
    assert info.value.sql == "DROP TABLE companies"
    assert len(llm.calls) == 3


async def test_persistently_malformed_output_raises_structured_error() -> None:
    llm = FakeChatModel()
    llm.replies["sql_generation"] = ["nope"] * 2
    with pytest.raises(StructuredOutputError) as info:
        await _generator(llm, attempts=2).generate("anything", TABLES)
    assert len(info.value.attempts) == 2
    assert "did not return a valid structured response" in info.value.user_message


async def test_sql_is_required_when_answerable() -> None:
    llm = FakeChatModel()
    missing_sql = {**json.loads(sql_reply("SELECT 1")), "sql": None}
    llm.replies["sql_generation"] = [json.dumps(missing_sql)]
    generated = await _generator(llm).generate("anything", TABLES)
    assert generated.attempts[0].errors == (
        '(root): Value error, "sql" is required when "answerable" is true',
    )


async def test_tables_used_keeps_only_real_tables() -> None:
    llm = FakeChatModel()
    llm.replies["sql_generation"] = [
        sql_reply("SELECT name FROM companies", tables_used=["companies", "latest_cte"])
    ]
    generated = await _generator(llm).generate("names", TABLES)
    assert generated.output.tables_used == ["companies"]


async def test_repair_includes_the_database_error() -> None:
    llm = FakeChatModel(sql="SELECT name FROM companies")

    generated = await _generator(llm).repair(
        "names", TABLES, "SELECT nam FROM companies", 'column "nam"\n does not exist'
    )

    assert generated.sql == "SELECT name FROM companies LIMIT 25"
    call = llm.calls[0]
    assert call["purpose"] == "sql_repair"
    assert "SELECT nam FROM companies" in call["user"]
    assert 'Error: column "nam" does not exist' in call["user"]


async def test_reply_in_code_fence_with_prose_is_accepted() -> None:
    llm = FakeChatModel()
    body = json.loads(sql_reply("SELECT 1 FROM companies"))
    llm.replies["sql_generation"] = [f"Sure!\n```json\n{json.dumps(body)}\n```\nDone."]
    generated = await _generator(llm).generate("one", TABLES)
    assert generated.raw_sql == "SELECT 1 FROM companies"


def test_every_field_is_required_for_constrained_decoding() -> None:
    # Regression: an optional "sql" let a small local model omit it under
    # JSON-schema decoding and fail every attempt identically.
    schema = json_schema_for(SQLGenerationOutput)
    assert set(schema["required"]) == {
        "answerable",
        "sql",
        "explanation",
        "tables_used",
        "confidence",
    }
