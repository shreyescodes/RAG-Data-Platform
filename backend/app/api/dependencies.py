"""FastAPI dependency providers."""

from __future__ import annotations

from functools import partial

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.agents.analysis import AnalysisAgent
from app.agents.enrichment import EnrichmentAgent
from app.agents.orchestrator import QueryOrchestrator
from app.agents.retrieval import RetrievalAgent
from app.agents.verification import VerificationAgent
from app.container import ServiceContainer
from app.core.config import Settings, get_settings
from app.db.repositories import MetricsRepository, QueryLogRepository, companies_by_ticker
from app.db.session import get_db, get_query_engine
from app.observability.pricing import PriceTable
from app.observability.recorder import MetricsRecorder
from app.rag.sql_generator import SQLGenerator
from app.services.llm import endpoint_kind
from app.services.structured_output import StructuredOutputExtractor


def get_services(request: Request) -> ServiceContainer:
    services: ServiceContainer = request.app.state.services
    return services


def get_orchestrator(
    services: ServiceContainer = Depends(get_services),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> QueryOrchestrator:
    endpoint = endpoint_kind(settings.llm_base_url)
    extractor = StructuredOutputExtractor(
        services.chat_model,
        max_attempts=settings.llm_structured_max_attempts,
        mode=settings.llm_structured_output,
        cache=services.response_cache,
    )
    retrieval = RetrievalAgent(
        indexer=services.schema_indexer,
        sql_generator=SQLGenerator(
            extractor,
            max_rows=settings.max_result_rows,
            allowed_tables=services.schema_indexer.catalog.keys(),
            semantic_cache=services.semantic_cache,
        ),
        engine=get_query_engine(),
        max_tables=settings.retrieval_max_tables,
        statement_timeout_ms=settings.sql_statement_timeout_ms,
        repair_attempts=settings.sql_repair_attempts,
    )
    return QueryOrchestrator(
        retrieval=retrieval,
        enrichment=EnrichmentAgent(market_data=services.market_data, sec_edgar=services.sec_edgar),
        analysis=AnalysisAgent(extractor),
        query_logs=QueryLogRepository(db),
        company_lookup=partial(companies_by_ticker, db),
        verification=VerificationAgent(mode=settings.verification_mode, extractor=extractor),
        metrics=MetricsRecorder(
            MetricsRepository(db),
            prices=PriceTable(settings.llm_pricing, local_endpoint=endpoint == "local"),
            model=settings.llm_model,
            endpoint=endpoint,
        ),
    )
