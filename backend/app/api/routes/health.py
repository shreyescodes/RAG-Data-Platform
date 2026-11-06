import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_services
from app.container import ServiceContainer
from app.core.config import Settings, get_settings
from app.core.rate_limit import limiter
from app.core.security import require_api_key
from app.db.session import get_db
from app.schemas import HealthResponse, LLMHealthResponse
from app.services.cache import describe
from app.services.llm import endpoint_kind

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


def _llm_configured(services: ServiceContainer) -> bool:
    return bool(getattr(services.chat_model, "configured", True))


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
def health(
    response: Response,
    db: Session = Depends(get_db),
    services: ServiceContainer = Depends(get_services),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Readiness probe: 200 when the database is reachable, 503 otherwise.

    The LLM is reported but does not affect readiness: without it the API
    still serves history, metrics and clear errors for queries.
    """
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except SQLAlchemyError:
        logger.exception("Health check: database unavailable")
        db_ok = False

    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="healthy" if db_ok else "unhealthy",
        database="connected" if db_ok else "unavailable",
        vector_store_documents=services.vector_store.size,
        llm_endpoint=endpoint_kind(settings.llm_base_url),
        llm_configured=_llm_configured(services),
    )


@router.get(
    "/health/llm", response_model=LLMHealthResponse, dependencies=[Depends(require_api_key)]
)
@limiter.limit(lambda: get_settings().rate_limit_query)
async def llm_health(
    request: Request,
    services: ServiceContainer = Depends(get_services),
    settings: Settings = Depends(get_settings),
) -> LLMHealthResponse:
    """Probe the configured LLM endpoint: local or remote, reachable, model served."""
    probe = getattr(services.chat_model, "probe", None)
    result = await probe() if probe is not None else None
    return LLMHealthResponse(
        endpoint=endpoint_kind(settings.llm_base_url),
        host=urlsplit(settings.llm_base_url).hostname or "",
        model=settings.llm_model,
        configured=_llm_configured(services),
        reachable=result.reachable if result else None,
        model_available=result.model_available if result else None,
        latency_ms=result.latency_ms if result else None,
        error=result.error if result else None,
        structured_output=settings.llm_structured_output,
        retrieval_mode=services.schema_indexer.mode,
        verification_mode=settings.verification_mode,
        caches=describe({"response": services.response_cache, "semantic": services.semantic_cache}),
    )
