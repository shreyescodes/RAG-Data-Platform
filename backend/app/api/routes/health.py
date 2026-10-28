import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_services
from app.container import ServiceContainer
from app.db.session import get_db
from app.schemas import HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
def health(
    response: Response,
    db: Session = Depends(get_db),
    services: ServiceContainer = Depends(get_services),
) -> HealthResponse:
    """Readiness probe: 200 when the database is reachable, 503 otherwise."""
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
    )
