"""Coordinates the agents that answer a single query.

redact PII -> retrieval (hybrid schema search, SQL, execution)
           -> enrichment (live market / SEC data, optional)
           -> analysis (LLM narrative over rows + enrichment)
           -> verification (flag answer claims the evidence does not support)
           -> audit log

When the database cannot answer a question that asks for live market or
filing data (e.g. "NVDA's market cap", which is not stored), the pipeline
falls back to answering from enrichment alone.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.agents.analysis import AnalysisAgent
from app.agents.base import Trace
from app.agents.enrichment import EnrichmentAgent
from app.agents.retrieval import RetrievalAgent, RetrievalResult
from app.agents.verification import VerificationAgent
from app.core.exceptions import PlatformError, UnanswerableQueryError
from app.db.models import QueryLog
from app.db.repositories import QueryLogRepository
from app.observability.metrics import RequestMetrics, StageListener, stage, track_request
from app.observability.recorder import MetricsRecorder
from app.rag.citations import build_citations
from app.schemas import AgentFlow, QueryResponse, RequestUsage, TraceStep, VerificationReport
from app.utils.pii_redactor import redact_pii

logger = logging.getLogger(__name__)

# Rows of the result persisted with the audit log.
_LOGGED_ROWS = 5
# Earlier turns given to the model so follow-up questions make sense.
_CONTEXT_TURNS = 3
_CONTEXT_QUESTION_CHARS = 300
_CONTEXT_SQL_CHARS = 600
_CONTEXT_ANSWER_CHARS = 400


@dataclass(frozen=True, slots=True)
class ConversationContext:
    text: str = ""
    last_question: str = ""


def _conversation_context(turns: Sequence[QueryLog]) -> ConversationContext:
    answered = [turn for turn in turns if turn.success][-_CONTEXT_TURNS:]
    if not answered:
        return ConversationContext()
    lines = ["Earlier in this conversation:"]
    for turn in answered:
        lines.append(f"Q: {turn.user_query[:_CONTEXT_QUESTION_CHARS]}")
        if turn.generated_sql:
            lines.append(f"SQL: {turn.generated_sql[:_CONTEXT_SQL_CHARS]}")
        if turn.final_answer:
            lines.append(f"A: {turn.final_answer[:_CONTEXT_ANSWER_CHARS]}")
    return ConversationContext("\n".join(lines), answered[-1].user_query)


class QueryOrchestrator:
    def __init__(
        self,
        *,
        retrieval: RetrievalAgent,
        enrichment: EnrichmentAgent,
        analysis: AnalysisAgent,
        query_logs: QueryLogRepository,
        company_lookup: Callable[[], Mapping[str, str]],
        verification: VerificationAgent | None = None,
        metrics: MetricsRecorder | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._enrichment = enrichment
        self._analysis = analysis
        self._verification = verification
        self._query_logs = query_logs
        self._company_lookup = company_lookup
        self._metrics = metrics

    async def run(
        self,
        raw_query: str,
        *,
        visitor_id: str | None = None,
        conversation_id: str | None = None,
        on_stage: StageListener | None = None,
    ) -> QueryResponse:
        context = ConversationContext()
        if visitor_id and conversation_id:
            turns = await run_in_threadpool(
                self._query_logs.conversation, visitor_id, conversation_id
            )
            context = _conversation_context(turns)
        with track_request(on_stage) as metrics:
            response, error_type, error_detail = await self._answer(raw_query, metrics, context)
        response.conversation_id = conversation_id
        if self._metrics is not None:
            entry = self._metrics.build(response, metrics, error_type=error_type)
            response.usage = RequestUsage(
                llm_calls=entry.llm_calls,
                cache_hits=entry.cache_hits,
                prompt_tokens=entry.prompt_tokens,
                completion_tokens=entry.completion_tokens,
                cost_usd=round(entry.cost_usd, 6),
                model=entry.model,
                llm_endpoint=entry.llm_endpoint,
                stage_latency_ms=metrics.stages_ms,
            )
            await self._metrics.persist(entry)
        response.id = await self._audit(
            response,
            error_detail=error_detail,
            visitor_id=visitor_id,
            conversation_id=conversation_id,
        )
        return response

    async def _answer(
        self, raw_query: str, metrics: RequestMetrics, context: ConversationContext
    ) -> tuple[QueryResponse, str | None, str | None]:
        """Run the pipeline; returns the response and, on failure, its type and detail."""
        started = metrics.started
        trace = Trace()
        flow = AgentFlow()

        redaction = redact_pii(raw_query)
        query = redaction.text
        if redaction.redacted:
            trace.record("guardrails", "pii_redacted", redaction.counts)

        def elapsed_ms() -> float:
            return round((time.perf_counter() - started) * 1000, 2)

        def fail(exc: PlatformError) -> tuple[QueryResponse, str | None, str | None]:
            logger.info("Query failed (%s): %s", type(exc).__name__, exc)
            response = QueryResponse(
                success=False,
                query=query,
                sql=exc.sql,
                error=exc.user_message,
                agent_flow=flow,
                trace=self._steps(trace),
                execution_time_ms=elapsed_ms(),
            )
            return response, type(exc).__name__, str(exc)

        wants_live_data = self._enrichment.wants_enrichment(query)
        unanswerable: UnanswerableQueryError | None = None
        try:
            retrieved = await self._retrieval.run(
                query, trace, context=context.text, search_hint=context.last_question
            )
            flow.retrieval = "completed"
        except UnanswerableQueryError as exc:
            if not wants_live_data:
                flow.retrieval = "failed"
                return fail(exc)
            # Not in the database, but possibly answerable from live data.
            trace.record("orchestrator", "fallback_to_live_data", str(exc))
            flow.retrieval = "skipped"
            retrieved = RetrievalResult(sql="", rows=[], tables=[])
            unanswerable = exc
        except PlatformError as exc:
            flow.retrieval = "failed"
            return fail(exc)

        companies: Mapping[str, str] = {}
        if wants_live_data:
            companies = await run_in_threadpool(self._company_lookup)
        with stage("enrichment"):
            enriched = await self._enrichment.run(query, retrieved.rows, companies, trace)
        flow.enrichment = enriched.status
        if unanswerable is not None and not enriched.data:
            return fail(unanswerable)

        with stage("analysis"):
            analysis = await self._analysis.run(
                query, retrieved.sql, retrieved.rows, enriched.data, trace, context=context.text
            )
        flow.analysis = analysis.status

        verification: VerificationReport | None = None
        if (
            self._verification is not None
            and analysis.status == "completed"
            and (retrieved.rows or enriched.data)
        ):
            try:
                with stage("verification"):
                    verification = await self._verification.run(
                        # A follow-up ("its revenue") names its subject in the turn before.
                        f"{context.last_question}\n{query}" if context.last_question else query,
                        retrieved.rows,
                        enriched.data,
                        answer=analysis.answer,
                        summary=analysis.summary,
                        insights=analysis.insights,
                        sql=retrieved.sql or "",
                        trace=trace,
                    )
                flow.verification = (
                    "skipped"
                    if verification.status == "skipped"
                    else ("degraded" if verification.degraded else "completed")
                )
            except Exception:  # a checker bug must never cost the user their answer
                logger.exception("Answer verification failed")
                flow.verification = "failed"

        response = QueryResponse(
            success=True,
            query=query,
            sql=retrieved.sql or None,
            answer=analysis.answer,
            summary=analysis.summary,
            insights=analysis.insights,
            data=retrieved.rows,
            row_count=len(retrieved.rows),
            relevant_tables=retrieved.tables,
            enriched_data=enriched.data,
            agent_flow=flow,
            trace=self._steps(trace),
            citations=build_citations(
                search=retrieved.search,
                sql=retrieved.sql,
                lineage_info=retrieved.lineage,
                row_count=len(retrieved.rows),
                enrichment=enriched.data,
                generation=retrieved.generation.output if retrieved.generation else None,
            ),
            verification=verification,
            execution_time_ms=elapsed_ms(),
        )
        return response, None, None

    @staticmethod
    def _steps(trace: Trace) -> list[TraceStep]:
        return [TraceStep.model_validate(step) for step in trace.as_dicts()]

    async def _audit(
        self,
        response: QueryResponse,
        *,
        error_detail: str | None,
        visitor_id: str | None,
        conversation_id: str | None,
    ) -> int | None:
        entry = QueryLog(
            visitor_id=visitor_id,
            conversation_id=conversation_id,
            user_query=response.query,
            generated_sql=response.sql,
            sql_result=json.dumps(response.data[:_LOGGED_ROWS], default=str),
            final_answer=response.answer,
            response_json=response.model_dump_json() if visitor_id else None,
            context_used=json.dumps(response.relevant_tables),
            agent_reasoning=json.dumps(
                [step.model_dump(mode="json") for step in response.trace], default=str
            ),
            execution_time_ms=response.execution_time_ms,
            success=response.success,
            error_message=error_detail,
        )
        try:
            return await run_in_threadpool(self._query_logs.add, entry)
        except SQLAlchemyError:
            # Auditing must never fail the user's request.
            logger.exception("Failed to persist query log")
            return None
