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
    verification: StageStatus = "skipped"


class TraceStep(BaseModel):
    agent: str
    step: str
    detail: Any = None
    timestamp: dt.datetime


class TableCitation(BaseModel):
    """A table shown to the SQL generator, with the scores that selected it."""

    table: str
    rank: int
    via: Literal["retrieved", "foreign_key", "sql_only"] = Field(
        description=(
            "retrieved: found by search; foreign_key: added because a retrieved table "
            "joins to it; sql_only: referenced by the SQL without being retrieved."
        )
    )
    used_in_sql: bool
    score: float | None = Field(
        default=None, description="Final score of the table's best-matching document."
    )
    dense_score: float | None = Field(default=None, description="Cosine similarity.")
    sparse_score: float | None = Field(default=None, description="BM25 score.")
    fused_score: float | None = Field(default=None, description="RRF score scaled to 0-1.")
    rerank_score: float | None = Field(default=None, description="Cross-encoder probability.")
    best_document: str | None = None
    matched_columns: list[str] = Field(default_factory=list)


class ColumnCitation(BaseModel):
    """Where one column of the result comes from."""

    output_column: str
    sources: list[str] = Field(default_factory=list, description='"table.column" inputs.')
    derivation: Literal["column", "aggregate", "expression", "literal", "unknown"]


class LiveSourceCitation(BaseModel):
    kind: Literal["market_data", "sec_filing"]
    ticker: str
    label: str
    url: str | None = None


class Citations(BaseModel):
    """Provenance of an answer: what was retrieved, what ran and where rows came from."""

    retrieval_mode: str | None = None
    retrieval_confidence: float | None = Field(
        default=None, description="Cross-encoder probability of the best table, 0-1."
    )
    generation_confidence: float | None = Field(
        default=None, description="The SQL generator's self-reported confidence, 0-1."
    )
    sql: str | None = Field(default=None, description="Exactly the SQL that was executed.")
    sql_explanation: str | None = Field(
        default=None, description="The SQL generator's account of how the query answers."
    )
    tables: list[TableCitation] = Field(default_factory=list)
    columns_referenced: list[str] = Field(default_factory=list)
    output_columns: list[ColumnCitation] = Field(default_factory=list)
    key_columns: list[str] = Field(
        default_factory=list,
        description="Result columns that identify which source row (or group) each row is.",
    )
    aggregated: bool = False
    row_count: int = 0
    live_sources: list[LiveSourceCitation] = Field(default_factory=list)


class EvidenceRef(BaseModel):
    """A piece of evidence a claim was checked against."""

    id: str = Field(description='e.g. "row:3", "agg:arr.mean", "market:AAPL".')
    kind: Literal["row", "aggregate", "meta", "question", "market_data", "sec_filing"]
    label: str
    row_index: int | None = Field(default=None, description="Index into `data`.")
    column: str | None = None
    value: Any = None


class ClaimCheck(BaseModel):
    id: str
    text: str
    source: Literal["answer", "summary", "insight"]
    verdict: Literal["supported", "partially_supported", "unsupported", "unverifiable"]
    confidence: float = Field(ge=0, le=1)
    method: Literal["deterministic", "llm", "hybrid"]
    reason: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    unsupported_values: list[str] = Field(
        default_factory=list, description="Numbers or names with no match in the evidence."
    )


class VerificationReport(BaseModel):
    """Claim-level check of the answer against the data it was generated from."""

    status: Literal["verified", "flagged", "skipped"]
    mode: str
    degraded: bool = Field(
        default=False, description="The LLM judge failed; deterministic checks only."
    )
    claims: list[ClaimCheck] = Field(default_factory=list)
    supported: int = 0
    partially_supported: int = 0
    unsupported: int = 0
    unverifiable: int = 0
    score: float | None = Field(
        default=None, description="Supported share of checkable claims (partial counts half)."
    )
    llm_judged: int = Field(default=0, description="Claims the LLM judge was asked about.")


class RequestUsage(BaseModel):
    """What answering this query cost: LLM usage and time per stage."""

    llm_calls: int = 0
    cache_hits: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    model: str | None = None
    llm_endpoint: str | None = Field(default=None, description="local or remote")
    stage_latency_ms: dict[str, float] = Field(default_factory=dict)


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
    citations: Citations | None = None
    verification: VerificationReport | None = None
    usage: RequestUsage | None = None
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
    llm_endpoint: Literal["local", "remote"] = Field(
        description="local: your own server (Ollama, vLLM, llama.cpp); remote: a hosted API."
    )
    llm_configured: bool


class LLMHealthResponse(BaseModel):
    endpoint: Literal["local", "remote"]
    host: str = Field(description="Host of the configured endpoint (no path or credentials).")
    model: str
    configured: bool
    reachable: bool | None = Field(description="None when the client cannot be probed.")
    model_available: bool | None = Field(
        default=None, description="Whether the server lists the configured model."
    )
    latency_ms: float | None = None
    error: str | None = None
    structured_output: str
    retrieval_mode: str
    verification_mode: str
    caches: dict[str, dict[str, Any]]


class IndexSchemaResponse(BaseModel):
    success: bool
    documents_indexed: int
    tables: list[str]


# --- Observability -----------------------------------------------------------------

MetricsWindow = Literal["1h", "6h", "24h", "7d", "30d"]


class LatencyStats(BaseModel):
    p50: float | None = None
    p95: float | None = None
    p99: float | None = None
    mean: float | None = None


class TokenUsage(BaseModel):
    prompt: int = 0
    completion: int = 0
    total: int = 0


class ModelUsage(BaseModel):
    model: str
    requests: int
    llm_calls: int
    failed_calls: int
    cache_hits: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    avg_latency_ms: float | None


class PurposeUsage(BaseModel):
    purpose: str = Field(description="sql_generation, sql_repair, analysis, verification, ...")
    llm_calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class FailingQuery(BaseModel):
    query: str
    failures: int
    last_error: str | None
    last_seen: dt.datetime


class ExpensiveQuery(BaseModel):
    query: str
    cost_usd: float
    total_tokens: int
    latency_ms: float
    created_at: dt.datetime


class VerificationStats(BaseModel):
    checked: int = 0
    flagged: int = 0
    unsupported_claims: int = 0


class MetricsSummary(BaseModel):
    window: MetricsWindow
    since: dt.datetime
    requests: int
    successes: int
    failures: int
    error_rate: float = Field(description="Failed share of requests, 0-1.")
    llm_calls: int
    cache_hits: int
    cache_hit_rate: float = Field(description="Share of LLM calls served from cache, 0-1.")
    tokens: TokenUsage
    cost_usd: float
    avg_cost_per_request_usd: float
    latency_ms: LatencyStats
    stage_latency_ms: dict[str, LatencyStats]
    verification: VerificationStats
    errors_by_type: dict[str, int]
    models: list[ModelUsage]
    purposes: list[PurposeUsage]
    top_failing_queries: list[FailingQuery]
    most_expensive_queries: list[ExpensiveQuery]


class TimeseriesPoint(BaseModel):
    start: dt.datetime
    requests: int
    failures: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_p50_ms: float | None
    latency_p95_ms: float | None


class TimeseriesResponse(BaseModel):
    window: MetricsWindow
    bucket_seconds: int
    points: list[TimeseriesPoint]


class RecentRequest(BaseModel):
    id: int
    created_at: dt.datetime
    request_id: str | None
    query: str
    success: bool
    error_type: str | None
    model: str
    llm_endpoint: str
    llm_calls: int
    cache_hits: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: float
    stage_latency_ms: dict[str, float]
    verification_status: str | None
    unsupported_claims: int | None


class RecentResponse(BaseModel):
    requests: list[RecentRequest]
