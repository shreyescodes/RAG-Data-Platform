from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_services
from app.container import ServiceContainer
from app.core.security import require_api_key
from app.db.repositories import QueryLogRepository, count_rows_by_table
from app.db.session import get_db
from app.schemas import QueryStats, StatsResponse

router = APIRouter(tags=["stats"], dependencies=[Depends(require_api_key)])


@router.get("/stats", response_model=StatsResponse)
def get_stats(
    db: Session = Depends(get_db),
    services: ServiceContainer = Depends(get_services),
) -> StatsResponse:
    repo = QueryLogRepository(db)
    total = repo.count()
    successful = repo.count(successful_only=True)
    return StatsResponse(
        queries=QueryStats(
            total=total,
            successful=successful,
            success_rate=round(successful / total * 100, 2) if total else 0.0,
        ),
        database=count_rows_by_table(db),
        vector_store=services.vector_store.stats(),
    )
