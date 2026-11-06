"""Persists one query's telemetry: a `request_metrics` row and its `llm_calls`."""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.core.logging import request_id_ctx
from app.db.models import LLMCall, RequestMetric
from app.db.repositories import MetricsRepository
from app.observability.metrics import STAGES, RequestMetrics
from app.observability.pricing import PriceTable
from app.schemas import QueryResponse

logger = logging.getLogger(__name__)

# Stored query text is already PII-redacted; it is truncated to bound row size.
_QUERY_CHARS = 500


class MetricsRecorder:
    def __init__(
        self, repository: MetricsRepository, *, prices: PriceTable, model: str, endpoint: str
    ) -> None:
        self._repository = repository
        self._prices = prices
        self._model = model
        self._endpoint = endpoint

    def build(
        self, response: QueryResponse, metrics: RequestMetrics, *, error_type: str | None
    ) -> RequestMetric:
        calls = [
            LLMCall(
                purpose=c.purpose,
                model=c.model,
                prompt_tokens=c.prompt_tokens,
                completion_tokens=c.completion_tokens,
                cost_usd=(
                    0.0
                    if c.cached
                    else self._prices.cost_usd(c.model, c.prompt_tokens, c.completion_tokens)
                ),
                latency_ms=c.latency_ms,
                success=c.success,
                cached=c.cached,
                tokens_estimated=c.estimated,
            )
            for c in metrics.llm_calls
        ]
        report = response.verification
        request_id = request_id_ctx.get()
        return RequestMetric(
            request_id=None if request_id == "-" else request_id,
            query=response.query[:_QUERY_CHARS],
            success=response.success,
            error_type=error_type,
            model=self._model,
            llm_endpoint=self._endpoint,
            llm_calls=len(calls),
            cache_hits=metrics.cache_hits,
            prompt_tokens=metrics.prompt_tokens,
            completion_tokens=metrics.completion_tokens,
            cost_usd=sum(c.cost_usd for c in calls),
            row_count=response.row_count,
            retrieval_mode=response.citations.retrieval_mode if response.citations else None,
            verification_status=report.status if report else None,
            unsupported_claims=(report.unsupported + report.partially_supported)
            if report and report.status != "skipped"
            else None,
            latency_total_ms=response.execution_time_ms,
            **{f"latency_{s}_ms": metrics.stages_ms.get(s) for s in STAGES},
            calls=calls,
        )

    async def persist(self, entry: RequestMetric) -> None:
        try:
            await run_in_threadpool(self._repository.add, entry)
        except SQLAlchemyError:
            # Telemetry must never fail the user's request.
            logger.exception("Failed to persist request metrics")
