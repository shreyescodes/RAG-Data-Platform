"""Process-wide services, created once at startup and shared across requests."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.agents.enrichment import FilingsProvider, QuoteProvider
from app.core.config import Settings
from app.rag.embeddings import SentenceTransformerEmbedder
from app.rag.schema_indexer import SchemaIndexer
from app.rag.vector_store import FAISSVectorStore
from app.services.llm import ChatModel, OpenAICompatibleChatModel
from app.services.market_data import MarketDataClient
from app.services.sec_edgar import SecEdgarClient


@dataclass(slots=True)
class ServiceContainer:
    vector_store: FAISSVectorStore
    schema_indexer: SchemaIndexer
    chat_model: ChatModel
    http_client: httpx.AsyncClient
    market_data: QuoteProvider | None
    sec_edgar: FilingsProvider | None

    async def aclose(self) -> None:
        await self.http_client.aclose()
        close = getattr(self.chat_model, "aclose", None)
        if close is not None:
            await close()


def build_services(settings: Settings) -> ServiceContainer:
    vector_store = FAISSVectorStore(
        SentenceTransformerEmbedder(settings.embedding_model),
        settings.faiss_index_path,
    )
    http_client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
    enabled = settings.enrichment_enabled
    return ServiceContainer(
        vector_store=vector_store,
        schema_indexer=SchemaIndexer(vector_store),
        chat_model=OpenAICompatibleChatModel(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        ),
        http_client=http_client,
        market_data=(
            MarketDataClient(timeout_seconds=settings.http_timeout_seconds) if enabled else None
        ),
        sec_edgar=(
            SecEdgarClient(http_client, user_agent=settings.sec_edgar_user_agent)
            if enabled
            else None
        ),
    )
