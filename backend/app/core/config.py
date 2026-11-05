"""Application settings, loaded from environment variables and `.env` files."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.observability.pricing import ModelPrice


class Settings(BaseSettings):
    """Typed runtime configuration.

    Values come from (in order of precedence) environment variables, then
    `backend/.env`, then the repository-root `.env`.
    """

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Runtime -----------------------------------------------------------
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_json: bool = False

    # --- Database ----------------------------------------------------------
    # Required: there is deliberately no default.
    database_url: str
    # Optional connection for LLM-generated SQL, ideally a role with SELECT-only
    # grants on the domain tables. Falls back to DATABASE_URL.
    query_database_url: str | None = None
    # Upper bound for a single LLM-generated query (PostgreSQL only).
    sql_statement_timeout_ms: int = Field(default=15_000, ge=100)
    max_result_rows: int = Field(default=500, ge=1, le=10_000)

    # --- LLM (any OpenAI-compatible endpoint; Groq by default) ---------------
    llm_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("LLM_API_KEY", "GROQ_API_KEY"),
    )
    llm_base_url: str = Field(
        default="https://api.groq.com/openai/v1",
        validation_alias=AliasChoices("LLM_BASE_URL", "OPENAI_API_BASE"),
    )
    llm_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)
    # How replies are kept to a JSON schema: json_schema (constrained decoding;
    # OpenAI, vLLM, Ollama, llama.cpp), json_object (valid JSON; Groq and most
    # servers) or prompt (instructions only, for endpoints with neither).
    llm_structured_output: Literal["json_schema", "json_object", "prompt"] = "json_object"
    # Attempts per structured reply; each retry feeds the errors back.
    llm_structured_max_attempts: int = Field(default=3, ge=1, le=5)
    # Times a query that fails in the database is sent back for correction.
    sql_repair_attempts: int = Field(default=1, ge=0, le=3)
    # Response caches in front of the LLM (per process, LRU + TTL). The exact
    # cache replays validated replies to identical prompts; the semantic cache
    # reuses SQL for similar questions that share every number, name and
    # ordering word. Cached SQL is always re-validated and re-executed.
    llm_cache_enabled: bool = True
    llm_cache_ttl_seconds: int = Field(default=3_600, ge=1)
    llm_cache_max_entries: int = Field(default=1_000, ge=1)
    semantic_cache_enabled: bool = True
    semantic_cache_threshold: float = Field(default=0.92, gt=0, le=1)
    # USD per million tokens, merged over the built-in prices, as JSON:
    # LLM_PRICING='{"my-model": {"input": 0.5, "output": 1.5}}'
    llm_pricing: dict[str, ModelPrice] = Field(default_factory=dict)

    # --- Retrieval ---------------------------------------------------------
    embedding_model: str = "all-MiniLM-L6-v2"
    faiss_index_path: str = "data/faiss_index"
    retrieval_max_tables: int = Field(default=4, ge=1)
    # Hybrid search: BM25 keyword retrieval fused with dense retrieval (RRF).
    retrieval_hybrid: bool = True
    retrieval_rrf_k: int = Field(default=60, ge=1)
    # Cross-encoder reranking of the fused shortlist (local, CPU-friendly).
    retrieval_rerank: bool = True
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    retrieval_rerank_candidates: int = Field(default=12, ge=1, le=200)

    # --- Verification (hallucination detection) ------------------------------
    # off; heuristic: deterministic checks of every number, date and name in
    # the answer; hybrid: plus one LLM judge call for claims those checks
    # cannot settle (only made when such claims exist).
    verification_mode: Literal["off", "heuristic", "hybrid"] = "hybrid"

    # --- Enrichment --------------------------------------------------------
    enrichment_enabled: bool = True
    # SEC requires a descriptive User-Agent with contact details:
    # https://www.sec.gov/os/accessing-edgar-data
    sec_edgar_user_agent: str = "RAG-Data-Platform admin@example.com"
    http_timeout_seconds: float = Field(default=10.0, gt=0)

    # --- API / security ----------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # Comma-separated list, e.g. "http://localhost:5173,https://app.example.com".
    allowed_origins: str = "http://localhost:5173"
    # Shared secret expected in the X-API-Key header. Empty disables auth,
    # which is only permitted outside production.
    api_key: SecretStr = SecretStr("")
    rate_limit_query: str = "20/minute"
    rate_limit_admin: str = "5/hour"
    expose_docs: bool = True

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key.get_secret_value())

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.environment == "production":
            if not self.auth_enabled:
                raise ValueError("API_KEY must be set when ENVIRONMENT=production")
            if "*" in self.allowed_origins_list:
                raise ValueError("Wildcard CORS origins are not allowed in production")
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance (cached)."""
    return Settings()  # populated from the environment
