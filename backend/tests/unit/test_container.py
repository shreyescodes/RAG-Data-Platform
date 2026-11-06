from pathlib import Path

from app.container import ServiceContainer, build_services
from app.core.config import get_settings
from app.rag.reranker import CrossEncoderReranker
from app.services.cache import ResponseCache, SemanticCache
from tests.fakes import OverlapReranker


async def test_build_services_follows_feature_flags(tmp_path: Path) -> None:
    settings = get_settings().model_copy(
        update={
            "faiss_index_path": str(tmp_path / "index"),
            "llm_base_url": "http://ollama:11434/v1",
            "retrieval_rerank": True,
            "semantic_cache_enabled": False,
        }
    )
    services = build_services(settings)
    try:
        assert services.schema_indexer.mode == "hybrid+rerank"
        assert isinstance(services.schema_indexer.reranker, CrossEncoderReranker)
        assert isinstance(services.response_cache, ResponseCache)
        assert services.semantic_cache is None
        assert services.market_data is None  # enrichment is disabled in tests
        assert getattr(services.chat_model, "endpoint", None) == "local"
    finally:
        await services.aclose()

    lean = build_services(
        settings.model_copy(
            update={
                "retrieval_hybrid": False,
                "retrieval_rerank": False,
                "llm_cache_enabled": False,
                "semantic_cache_enabled": True,
            }
        )
    )
    try:
        assert lean.schema_indexer.mode == "dense"
        assert lean.response_cache is None
        assert isinstance(lean.semantic_cache, SemanticCache)
    finally:
        await lean.aclose()


def test_warm_up_survives_a_broken_reranker(services: ServiceContainer) -> None:
    services.schema_indexer.reranker = OverlapReranker(error=OSError("weights missing"))
    services.warm_up()  # logs instead of raising
