"""FastAPI dependency providers."""

from __future__ import annotations

from functools import partial

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.agents.analysis import AnalysisAgent
from app.agents.enrichment import EnrichmentAgent
from app.agents.orchestrator import QueryOrchestrator
from app.agents.retrieval import RetrievalAgent
from app.container import ServiceContainer
from app.core.config import Settings, get_settings
from app.db.repositories import QueryLogRepository, companies_by_ticker
from app.db.session import get_db, get_query_engine
from app.rag.sql_generator import SQLGenerator


def get_services(request: Request) -> ServiceContainer:
    services: ServiceContainer = request.app.state.services
    return services


def get_orchestrator(
    services: ServiceContainer = Depends(get_services),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> QueryOrchestrator:
    retrieval = RetrievalAgent(
        indexer=services.schema_indexer,
        sql_generator=SQLGenerator(services.chat_model, max_rows=settings.max_result_rows),
        engine=get_query_engine(),
        max_tables=settings.retrieval_max_tables,
        max_rows=settings.max_result_rows,
        statement_timeout_ms=settings.sql_statement_timeout_ms,
    )
    return QueryOrchestrator(
        retrieval=retrieval,
        enrichment=EnrichmentAgent(market_data=services.market_data, sec_edgar=services.sec_edgar),
        analysis=AnalysisAgent(services.chat_model),
        query_logs=QueryLogRepository(db),
        company_lookup=partial(companies_by_ticker, db),
    )
