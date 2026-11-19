"""End-to-end evaluation against a seeded database and a real LLM.

Each case is asked through the same orchestrator the API uses. Answerable
cases are scored by execution accuracy: every value returned by a hand-written
ground-truth query must appear in the pipeline's result rows. Every answered
case also reports its citations (were the tables the ground truth reads cited
as used?), the fact check of its answer (claims flagged as unsupported) and its
LLM usage. Guardrail cases check that unanswerable questions are refused, that
questions the database cannot answer fall back to live market data, that
prompt injection cannot modify data, that PII never reaches the audit log and
that a repeated question is served from the response cache.

Usage, from `backend/` with DATABASE_URL set and an LLM configured (a local
endpoint such as Ollama needs no key):

    python -m eval.run                       # writes ../docs/evaluation.md
    python -m eval.run --only apple-latest-revenue --pause 0
    python -m eval.run --sql-only --resume --wait-on-limit

`--sql-only` scores accuracy on the generated SQL without writing an answer,
which uses about a third of the tokens. `--resume` keeps finished cases and
`--wait-on-limit` sleeps through a provider's rate limit.
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

import sqlglot
from sqlalchemy import func, select, text
from sqlglot import exp

from app.agents.base import Trace
from app.api.dependencies import build_retrieval_agent, get_orchestrator
from app.container import ServiceContainer, build_services
from app.core.config import get_settings
from app.core.exceptions import LLMError, LLMRateLimitError, PlatformError
from app.core.logging import configure_logging
from app.db.models import Company, QueryLog
from app.db.session import get_engine, get_session_factory
from app.observability.metrics import track_request
from app.schemas import QueryResponse, RequestUsage
from app.services.llm import endpoint_kind

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
    cited: bool | None = None  # every ground-truth table cited as used by the SQL
    retrieval_confidence: float | None = None
    claims: int = 0
    flagged_claims: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    cache_hits: int = 0
    llm_calls: int = 0
    detail: str | None = None  # internal error text, for diagnosing failures


# Failures caused by the model provider rather than the pipeline: rerun on --resume.
_PROVIDER_FAILURE = LLMError.user_message


def _norm(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def _present(expected: Any, rows: list[dict[str, Any]]) -> bool:
    """Whether `expected` appears as any cell of `rows` (numbers within 0.5%)."""
    for row in rows:
        for raw in row.values():
            cell = _norm(raw)
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


def _truth_tables(sql: str) -> set[str]:
    return {t.name for t in sqlglot.parse_one(sql, read="postgres").find_all(exp.Table)}


def _accuracy(
    expected: list[Any], rows: list[dict[str, Any]], error: str | None
) -> tuple[bool, str]:
    missing = [v for v in expected if not _present(v, rows)]
    passed = error is None and bool(expected) and not missing
    reason = "all ground-truth values returned" if passed else (error or f"missing {missing[:3]}")
    return passed, reason


async def run_sql_case(services: ServiceContainer, case: dict[str, Any]) -> CaseResult:
    """Score the generated SQL alone: no written answer and no fact check."""
    with get_engine().connect() as conn:
        expected = [_norm(r[0]) for r in conn.execute(text(case["truth_sql"])).all()]
    agent = build_retrieval_agent(services, get_settings())
    rows: list[dict[str, Any]] = []
    sql: str | None = None
    error: str | None = None
    detail: str | None = None
    tables: list[str] = []
    started = time.perf_counter()
    with track_request() as metrics:
        try:
            retrieved = await agent.run(case["question"], Trace())
            rows, sql, tables = retrieved.rows, retrieved.sql, retrieved.tables
        except LLMRateLimitError:
            raise
        except PlatformError as exc:
            sql, error, detail = exc.sql, exc.user_message, f"{type(exc).__name__}: {exc}"[:500]
    passed, reason = _accuracy(expected, rows, error)
    return CaseResult(
        id=case["id"],
        kind="accuracy",
        question=case["question"],
        passed=passed,
        reason=reason,
        success=error is None,
        latency_s=round(time.perf_counter() - started, 2),
        rows=len(rows),
        tables=tables,
        agent_flow={},
        sql=sql,
        answer=None,
        error=error,
        expected=expected[:5],
        tokens=metrics.prompt_tokens + metrics.completion_tokens,
        cache_hits=metrics.cache_hits,
        llm_calls=len(metrics.llm_calls),
        detail=detail,
    )


async def run_case(services: ServiceContainer, case: dict[str, Any]) -> CaseResult:
    kind = case.get("kind", "accuracy")
    expected: list[Any] = []
    if kind == "accuracy":
        with get_engine().connect() as conn:
            expected = [_norm(r[0]) for r in conn.execute(text(case["truth_sql"])).all()]

    companies_before = _companies()
    repeat_usage: RequestUsage | None = None
    started = time.perf_counter()
    response = await _ask(services, case["question"])
    latency = time.perf_counter() - started
    if "usage limit" in (response.error or ""):
        raise LLMRateLimitError(response.error or "", retry_after_seconds=None)

    if kind == "accuracy":
        passed, reason = _accuracy(expected, response.data, response.error)
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
    elif kind == "cache":
        repeat = await _ask(services, case["question"])
        repeat_usage = repeat.usage
        replayed = (
            repeat_usage is not None
            and repeat_usage.llm_calls > 0
            and repeat_usage.cache_hits == repeat_usage.llm_calls
        )
        passed = response.success and replayed and repeat.data == response.data
        reason = (
            f"repeat served from cache "
            f"({repeat_usage.cache_hits} of {repeat_usage.llm_calls} LLM calls)"
            if passed and repeat_usage
            else "repeat was not served from the cache"
        )
    else:
        raise ValueError(f"unknown case kind {kind!r}")

    cited: bool | None = None
    if kind == "accuracy" and response.citations is not None:
        used = {t.table for t in response.citations.tables if t.used_in_sql}
        cited = _truth_tables(case["truth_sql"]) <= used
    report = response.verification
    usage = response.usage

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
        cited=cited,
        retrieval_confidence=(
            response.citations.retrieval_confidence if response.citations else None
        ),
        claims=len(report.claims) if report else 0,
        flagged_claims=(report.unsupported + report.partially_supported) if report else 0,
        tokens=(usage.prompt_tokens + usage.completion_tokens) if usage else 0,
        cost_usd=usage.cost_usd if usage else 0.0,
        # Count the cache case's repeat too, so the summary includes its hits.
        cache_hits=sum(u.cache_hits for u in (usage, repeat_usage) if u),
        llm_calls=sum(u.llm_calls for u in (usage, repeat_usage) if u),
    )


def render_markdown(results: list[CaseResult], meta: dict[str, Any]) -> str:
    passed = sum(r.passed for r in results)
    accuracy = [r for r in results if r.kind == "accuracy"]
    guards = [r for r in results if r.kind != "accuracy"]
    latencies = sorted(r.latency_s for r in accuracy) or [0.0]
    median = latencies[len(latencies) // 2]
    cited = [r for r in accuracy if r.cited is not None]
    answered = [r for r in results if r.claims]

    lines = [
        "# Evaluation",
        "",
        "Generated by `python -m eval.run` from a live run: real PostgreSQL, a real LLM and",
        "the Yahoo Finance and SEC data loaded by `python -m app.cli seed`. Nothing is mocked.",
        *(
            ["", "Accuracy cases score the generated SQL only; no written answer is produced."]
            if meta.get("sql_only")
            else []
        ),
        "",
        f"- **Run:** {meta['date']}",
        f"- **Model:** `{meta['model']}` ({meta['endpoint']} endpoint)  ·  "
        f"**Embeddings:** `{meta['embedding_model']}`",
        f"- **Retrieval:** `{meta['retrieval']}`  ·  **Fact check:** `{meta['verification']}`",
        "",
        f"**{passed}/{len(results)} cases passed.** "
        f"Execution accuracy {sum(r.passed for r in accuracy)}/{len(accuracy)}, "
        f"behaviour checks (refusal, live-data fallback, injection, PII, cache) "
        f"{sum(r.passed for r in guards)}/{len(guards)}, "
        f"median latency {median:.1f}s.",
        "",
        *(
            [
                f"- **Citations:** ground-truth tables cited as used in "
                f"{sum(bool(r.cited) for r in cited)}/{len(cited)} answered accuracy cases."
            ]
            if cited
            else []
        ),
        *(
            [
                f"- **Fact check:** {sum(r.flagged_claims for r in answered)} of "
                f"{sum(r.claims for r in answered)} answer claims flagged as not fully "
                f"supported across {len(answered)} answers."
            ]
            if answered
            else []
        ),
        f"- **Usage:** {sum(r.tokens for r in results):,} tokens, "
        f"${sum(r.cost_usd for r in results):.4f} estimated, "
        f"{sum(r.cache_hits for r in results)} of {sum(r.llm_calls for r in results)} "
        "LLM calls served from cache.",
        "",
        "| # | Case | Question | Result | Rows | Latency | Cited | Claims flagged | Tokens "
        "| Check |",
        "|---|------|----------|--------|-----:|--------:|:-----:|---------------:|-------:"
        "|-------|",
    ]
    for i, r in enumerate(results, 1):
        mark = "pass" if r.passed else "**fail**"
        cited_mark = {True: "yes", False: "**no**", None: "–"}[r.cited]
        flagged = f"{r.flagged_claims}/{r.claims}" if r.claims else "–"
        lines.append(
            f"| {i} | `{r.id}` | {r.question} | {mark} | {r.rows} "
            f"| {r.latency_s:.1f}s | {cited_mark} | {flagged} | {r.tokens:,} | {r.reason} |"
        )

    failures = [r for r in results if not r.passed]
    if failures:
        lines += ["", "## Failures", ""]
        lines += [f"- `{r.id}`: {r.reason}" for r in failures]
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
        "--pause",
        type=float,
        default=None,
        help="Seconds between cases for hosted-API rate limits (default: 8, or 0 when local).",
    )
    parser.add_argument("--sql-only", action="store_true", help="Score accuracy on SQL alone.")
    parser.add_argument("--resume", action="store_true", help="Keep results already in --out.")
    parser.add_argument(
        "--wait-on-limit", action="store_true", help="Sleep through provider rate limits."
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging("WARNING")
    local = endpoint_kind(settings.llm_base_url) == "local"
    if not (local or settings.llm_api_key.get_secret_value()):
        sys.stderr.write(
            "LLM_API_KEY is not set and LLM_BASE_URL is not a local endpoint; "
            "the evaluation needs a real model.\n"
        )
        return 2

    pause = args.pause if args.pause is not None else (0.0 if local else 8.0)
    results_path = args.out.with_suffix(".json")
    finished: dict[str, CaseResult] = {}
    if args.resume and results_path.exists():
        saved = json.loads(results_path.read_text(encoding="utf-8"))["results"]
        finished = {
            item["id"]: CaseResult(**item) for item in saved if item["reason"] != _PROVIDER_FAILURE
        }
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c["id"] in args.only]

    services = build_services(settings)
    try:
        services.vector_store.warm_up()
        if services.vector_store.size == 0:
            services.schema_indexer.index()

        results: list[CaseResult] = []
        for case in cases:
            if case["id"] in finished:
                results.append(finished[case["id"]])
                continue
            while True:
                try:
                    accuracy = case.get("kind", "accuracy") == "accuracy"
                    result = await (
                        run_sql_case(services, case)
                        if args.sql_only and accuracy
                        else run_case(services, case)
                    )
                    break
                except LLMRateLimitError as exc:
                    if not args.wait_on_limit:
                        raise
                    delay = (exc.retry_after_seconds or 600.0) + 30.0
                    print(f"[wait] rate limited, sleeping {delay:.0f}s", flush=True)
                    await asyncio.sleep(delay)
            results.append(result)
            results_path.parent.mkdir(parents=True, exist_ok=True)
            results_path.write_text(
                json.dumps({"results": [asdict(r) for r in results]}, indent=2, default=str),
                encoding="utf-8",
            )
            status = "PASS" if result.passed else "FAIL"
            print(
                f"[{status}] {result.id:<26} {result.latency_s:5.1f}s  {result.reason}", flush=True
            )
            if pause:
                await asyncio.sleep(pause)
    finally:
        await services.aclose()

    meta = {
        "date": dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "model": settings.llm_model,
        "endpoint": "local" if local else "remote",
        "embedding_model": settings.embedding_model,
        "retrieval": services.schema_indexer.mode,
        "verification": settings.verification_mode,
        "sql_only": args.sql_only,
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
