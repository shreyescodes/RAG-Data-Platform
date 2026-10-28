import logging

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import get_services
from app.container import ServiceContainer
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.core.security import require_api_key
from app.schemas import IndexSchemaResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["admin"], dependencies=[Depends(require_api_key)])


@router.post("/index-schema", response_model=IndexSchemaResponse)
@limiter.limit(lambda: get_settings().rate_limit_admin)
def index_schema(
    request: Request,
    services: ServiceContainer = Depends(get_services),
) -> IndexSchemaResponse:
    """Rebuild the schema vector index. Idempotent; call after migrations."""
    count = services.schema_indexer.index()
    logger.info("Schema re-indexed: %d documents", count)
    return IndexSchemaResponse(
        success=True,
        documents_indexed=count,
        tables=sorted(services.schema_indexer.catalog),
    )
