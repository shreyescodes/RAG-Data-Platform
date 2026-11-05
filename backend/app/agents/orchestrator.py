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
from collections.abc import Callable, Mapping

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
from app.observability.metrics import RequestMetrics, stage, track_request
from app.observability.recorder import MetricsRecorder
from app.rag.citations import build_citations
from app.schemas import AgentFlow, QueryResponse, RequestUsage, TraceStep, VerificationReport
from app.utils.pii_redactor import redact_pii

logger = logging.getLogger(__name__)

# Rows of the result persisted with the audit log.
_LOGGED_ROWS = 5


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

    async def run(self, raw_query: str) -> QueryResponse:
        with track_request() as metrics:
            response, error_type = await self._answer(raw_query, metrics)
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
        return response

    async def _answer(
        self, raw_query: str, metrics: RequestMetrics
    ) -> tuple[QueryResponse, str | None]:
        """Run the pipeline; returns the response and the failure type, if any."""
        started = metrics.started
        trace = Trace()
        flow = AgentFlow()

        redaction = redact_pii(raw_query)
        query = redaction.text
        if redaction.redacted:
            trace.record("guardrails", "pii_redacted", redaction.counts)

        def elapsed_ms() -> float:
            return round((time.perf_counter() - started) * 1000, 2)

        async def fail(exc: PlatformError) -> tuple[QueryResponse, str | None]:
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
            await self._audit(response, trace, error_detail=str(exc))
            return response, type(exc).__name__

        wants_live_data = self._enrichment.wants_enrichment(query)
        unanswerable: UnanswerableQueryError | None = None
        try:
            retrieved = await self._retrieval.run(query, trace)
            flow.retrieval = "completed"
        except UnanswerableQueryError as exc:
            if not wants_live_data:
                flow.retrieval = "failed"
                return await fail(exc)
            # Not in the database, but possibly answerable from live data.
            trace.record("orchestrator", "fallback_to_live_data", str(exc))
            flow.retrieval = "skipped"
            retrieved = RetrievalResult(sql="", rows=[], tables=[])
            unanswerable = exc
        except PlatformError as exc:
            flow.retrieval = "failed"
            return await fail(exc)

        companies: Mapping[str, str] = {}
        if wants_live_data:
            companies = await run_in_threadpool(self._company_lookup)
        with stage("enrichment"):
            enriched = await self._enrichment.run(query, retrieved.rows, companies, trace)
        flow.enrichment = enriched.status
        if unanswerable is not None and not enriched.data:
            return await fail(unanswerable)

        with stage("analysis"):
            analysis = await self._analysis.run(
                query, retrieved.sql, retrieved.rows, enriched.data, trace
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
                        query,
                        retrieved.rows,
                        enriched.data,
                        answer=analysis.answer,
                        summary=analysis.summary,
                        insights=analysis.insights,
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
        await self._audit(response, trace)
        return response, None

    @staticmethod
    def _steps(trace: Trace) -> list[TraceStep]:
        return [TraceStep.model_validate(step) for step in trace.as_dicts()]

    async def _audit(
        self, response: QueryResponse, trace: Trace, *, error_detail: str | None = None
    ) -> None:
        entry = QueryLog(
            user_query=response.query,
            generated_sql=response.sql,
            sql_result=json.dumps(response.data[:_LOGGED_ROWS], default=str),
            final_answer=response.answer,
            context_used=json.dumps(response.relevant_tables),
            agent_reasoning=json.dumps(trace.as_dicts(), default=str),
            execution_time_ms=response.execution_time_ms,
            success=response.success,
            error_message=error_detail,
        )
        try:
            await run_in_threadpool(self._query_logs.add, entry)
        except SQLAlchemyError:
            # Auditing must never fail the user's request.
            logger.exception("Failed to persist query log")
