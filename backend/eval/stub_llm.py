"""A stand-in OpenAI-compatible LLM for load tests.

Replies instantly-valid JSON after a fixed delay, so a load test measures the
platform (retrieval, SQL execution, fact check, database) rather than a model
provider's rate limits. Never use it for accuracy measurements.

    python -m eval.stub_llm --port 9000 --delay 0.5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, Request

_SQL = {
    "nvda": "SELECT date, close_price, ma_50 FROM market_data WHERE ticker = 'NVDA' "
    "ORDER BY date DESC LIMIT 30",
    "berkshire": "SELECT h.issuer_name, h.value_usd FROM fund_holdings h JOIN funds f "
    "ON f.id = h.fund_id WHERE f.name ILIKE 'berkshire%' ORDER BY h.report_date DESC, "
    "h.value_usd DESC LIMIT 5",
    "revenue": "SELECT c.name, f.statement_date, f.revenue FROM financial_statements f "
    "JOIN companies c ON c.id = f.company_id WHERE c.ticker = 'AAPL' "
    "AND f.period_type = 'Quarterly' ORDER BY f.statement_date DESC LIMIT 4",
}
_DEFAULT_SQL = "SELECT name, sector FROM companies WHERE sector = 'Technology' ORDER BY name"


def _reply(system: str, user: str) -> dict[str, Any]:
    if "translate questions" in system:
        question = user.rsplit("Question:", 1)[-1].lower()
        sql = next((s for key, s in _SQL.items() if key in question), _DEFAULT_SQL)
        return {
            "answerable": True,
            "sql": sql,
            "explanation": "Stub reply.",
            "tables_used": [],
            "confidence": 0.9,
        }
    return {
        "answer": "The query returned the rows shown below.",
        "summary": "A stub answer for load testing.",
        "insights": ["The rows are listed in the table."],
    }


def create_app(delay: float) -> FastAPI:
    app = FastAPI()

    @app.get("/v1/models")
    async def models() -> dict[str, Any]:
        return {"object": "list", "data": [{"id": "stub", "object": "model"}]}

    @app.post("/v1/chat/completions")
    async def complete(request: Request) -> dict[str, Any]:
        body = await request.json()
        messages = {m["role"]: m["content"] for m in body["messages"]}
        await asyncio.sleep(delay)
        content = json.dumps(_reply(messages.get("system", ""), messages.get("user", "")))
        return {
            "id": "stub",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": body["model"],
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200},
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds per reply.")
    args = parser.parse_args()
    uvicorn.run(create_app(args.delay), host="0.0.0.0", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
