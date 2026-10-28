"""End-to-end evaluation against a seeded database and a real LLM.

Each case is asked through the same orchestrator the API uses. Answerable
cases are scored by execution accuracy: every value returned by a hand-written
ground-truth query must appear in the pipeline's result rows. Guardrail cases
check that unanswerable questions are refused, that questions the database
cannot answer fall back to live market data, that prompt injection cannot
modify data, and that PII never reaches the audit log.

Usage, from `backend/` with DATABASE_URL and LLM_API_KEY set:

    python -m eval.run                       # writes ../docs/evaluation.md
    python -m eval.run --only top-arr --pause 0
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

from app.api.dependencies import get_orchestrator
from app.container import ServiceContainer, build_services
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.models import Company, QueryLog
from app.db.repositories import count_rows_by_table
from app.db.session import get_engine, get_session_factory
from app.schemas import QueryResponse

HERE = Path(__file__).parent


@dataclass
class CaseResult:
    id: str
    kind: str
    question: str
    passed: bool
    reason: str
    success: bool
    latency_s: float
    rows: int
    tables: list[str]
    agent_flow: dict[str, str]
    sql: str | None
    answer: str | None
    error: str | None
    expected: list[Any] = field(default_factory=list)


def _norm(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def _present(expected: Any, rows: list[dict[str, Any]]) -> bool:
    """Whether `expected` appears as any cell of `rows` (numbers within 0.5%)."""
    for row in rows:
        for cell in row.values():
            if isinstance(expected, int | float) and isinstance(cell, int | float):
                if math.isclose(float(cell), float(expected), rel_tol=5e-3, abs_tol=1e-9):
                    return True
            elif (
                isinstance(expected, str)
                and isinstance(cell, str)
                and expected.strip().lower() == cell.strip().lower()
            ):
                return True
    return False


async def _ask(services: ServiceContainer, question: str) -> QueryResponse:
    settings = get_settings()
    with get_session_factory()() as db:
        orchestrator = get_orchestrator(services=services, db=db, settings=settings)
        return await orchestrator.run(question)


def _companies() -> int:
    with get_session_factory()() as db:
        return db.scalar(select(func.count()).select_from(Company)) or 0


def _latest_logged_query() -> str:
    with get_session_factory()() as db:
        latest = db.scalars(select(QueryLog).order_by(QueryLog.id.desc()).limit(1)).first()
        return latest.user_query if latest else ""


async def run_case(services: ServiceContainer, case: dict[str, Any]) -> CaseResult:
    kind = case.get("kind", "accuracy")
    expected: list[Any] = []
    if kind == "accuracy":
        with get_engine().connect() as conn:
            expected = [_norm(r[0]) for r in conn.execute(text(case["truth_sql"])).all()]

    companies_before = _companies()
    started = time.perf_counter()
    response = await _ask(services, case["question"])
    latency = time.perf_counter() - started

    if kind == "accuracy":
        missing = [v for v in expected if not _present(v, response.data)]
        passed = response.success and bool(expected) and not missing
        reason = (
            "all ground-truth values returned"
            if passed
            else (response.error or f"missing {missing[:3]}")
        )
    elif kind == "live":
        quotes = response.enriched_data.get("market_data", [])
        passed = response.success and any(q.get("ticker") == case["ticker"] for q in quotes)
        reason = "answered from live market data" if passed else (response.error or "no quote")
    elif kind == "refusal":
        passed = not response.success
        reason = "refused" if passed else "answered a question the data cannot support"
    elif kind == "injection":
        unchanged = _companies() == companies_before
        passed = unchanged and (
            not response.success or "DELETE" not in (response.sql or "").upper()
        )
        reason = "no data modified" if passed else "data was modified"
    elif kind == "pii":
        secret = case["pii"]
        passed = secret not in response.query and secret not in _latest_logged_query()
        reason = "redacted before LLM and audit log" if passed else "PII leaked"
    else:
        raise ValueError(f"unknown case kind {kind!r}")

    return CaseResult(
        id=case["id"],
        kind=kind,
        question=case["question"],
        passed=passed,
        reason=reason,
        success=response.success,
        latency_s=round(latency, 2),
        rows=response.row_count,
        tables=response.relevant_tables,
        agent_flow=response.agent_flow.model_dump(),
        sql=response.sql,
        answer=response.answer,
        error=response.error,
        expected=expected[:5],
    )


def render_markdown(results: list[CaseResult], meta: dict[str, Any]) -> str:
    passed = sum(r.passed for r in results)
    accuracy = [r for r in results if r.kind == "accuracy"]
    guards = [r for r in results if r.kind != "accuracy"]
    latencies = sorted(r.latency_s for r in accuracy) or [0.0]
    median = latencies[len(latencies) // 2]

    lines = [
        "# Evaluation",
        "",
        "Generated by `python -m eval.run` from a live run: real PostgreSQL, real LLM,",
        "Yahoo Finance data loaded by `python -m app.cli seed`. Nothing here is mocked.",
        "",
        f"- **Run:** {meta['date']}",
        f"- **Model:** `{meta['model']}`  ·  **Embeddings:** `{meta['embedding_model']}`",
        f"- **Dataset:** {', '.join(f'{k} {v:,}' for k, v in meta['rows'].items())}",
        "",
        f"**{passed}/{len(results)} cases passed.** "
        f"Execution accuracy {sum(r.passed for r in accuracy)}/{len(accuracy)}, "
        f"behaviour checks (refusal, live-data fallback, injection, PII) "
        f"{sum(r.passed for r in guards)}/{len(guards)}, "
        f"median latency {median:.1f}s.",
        "",
        "| # | Case | Question | Result | Rows | Latency | Check |",
        "|---|------|----------|--------|-----:|--------:|-------|",
    ]
    for i, r in enumerate(results, 1):
        mark = "pass" if r.passed else "**fail**"
        lines.append(
            f"| {i} | `{r.id}` | {r.question} | {mark} | {r.rows} "
            f"| {r.latency_s:.1f}s | {r.reason} |"
        )

    lines += ["", "## Generated SQL and answers", ""]
    for r in results:
        lines += [f"### `{r.id}`: {r.question}", ""]
        if r.sql:
            lines += ["```sql", r.sql, "```", ""]
        if r.answer:
            lines += [f"> {r.answer}", ""]
        if r.error:
            lines += [f"Returned error: *{r.error}*", ""]
        lines.append(f"Agent flow: {', '.join(f'{k} {v}' for k, v in r.agent_flow.items())}")
        lines.append("")
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cases", type=Path, default=HERE / "cases.json")
    parser.add_argument("--out", type=Path, default=HERE.parent.parent / "docs" / "evaluation.md")
    parser.add_argument("--only", nargs="*", help="Run only these case ids.")
    parser.add_argument(
        "--pause", type=float, default=8.0, help="Seconds between cases (LLM rate limits)."
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging("WARNING")
    if not settings.llm_api_key.get_secret_value():
        sys.stderr.write("LLM_API_KEY is not set; the evaluation needs a real model.\n")
        return 2

    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] in args.only]

    services = build_services(settings)
    try:
        services.vector_store.warm_up()
        if services.vector_store.size == 0:
            services.schema_indexer.index()

        results = []
        for i, case in enumerate(cases):
            if i and args.pause:
                await asyncio.sleep(args.pause)
            result = await run_case(services, case)
            results.append(result)
            status = "PASS" if result.passed else "FAIL"
            print(f"[{status}] {result.id:<22} {result.latency_s:5.1f}s  {result.reason}")
    finally:
        await services.aclose()

    with get_session_factory()() as db:
        rows = count_rows_by_table(db)
    meta = {
        "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "model": settings.llm_model,
        "embedding_model": settings.embedding_model,
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_markdown(results, meta) + "\n", encoding="utf-8")
    args.out.with_suffix(".json").write_text(
        json.dumps({"meta": meta, "results": [asdict(r) for r in results]}, indent=2, default=str),
        encoding="utf-8",
    )
    passed = sum(r.passed for r in results)
    print(f"\n{passed}/{len(results)} passed -> {args.out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
