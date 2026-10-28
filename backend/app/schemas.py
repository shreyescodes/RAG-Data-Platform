"""Request and response models for the HTTP API."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

StageStatus = Literal["completed", "skipped", "degraded", "failed"]


class QueryRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(min_length=3, max_length=1000, examples=["Top 5 companies by revenue"])


class AgentFlow(BaseModel):
    retrieval: StageStatus = "skipped"
    enrichment: StageStatus = "skipped"
    analysis: StageStatus = "skipped"


class TraceStep(BaseModel):
    agent: str
    step: str
    detail: Any = None
    timestamp: dt.datetime


class QueryResponse(BaseModel):
    success: bool
    query: str = Field(description="The query as processed, after PII redaction.")
    sql: str | None = None
    answer: str | None = None
    summary: str | None = None
    insights: list[str] = Field(default_factory=list)
    data: list[dict[str, Any]] = Field(default_factory=list)
    row_count: int = 0
    relevant_tables: list[str] = Field(default_factory=list)
    enriched_data: dict[str, Any] = Field(default_factory=dict)
    execution_time_ms: float = 0.0
    agent_flow: AgentFlow = Field(default_factory=AgentFlow)
    trace: list[TraceStep] = Field(default_factory=list)
    error: str | None = None


class HistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    query: str
    sql: str | None
    answer: str | None
    success: bool
    error: str | None
    execution_time_ms: float | None
    created_at: dt.datetime | None


class HistoryResponse(BaseModel):
    total: int
    limit: int
    offset: int
    history: list[HistoryItem]


class QueryStats(BaseModel):
    total: int
    successful: int
    success_rate: float = Field(description="Percentage, 0-100.")


class StatsResponse(BaseModel):
    queries: QueryStats
    database: dict[str, int]
    vector_store: dict[str, Any]


class HealthResponse(BaseModel):
    status: Literal["healthy", "unhealthy"]
    database: Literal["connected", "unavailable"]
    vector_store_documents: int


class IndexSchemaResponse(BaseModel):
    success: bool
    documents_indexed: int
    tables: list[str]
