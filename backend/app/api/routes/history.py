from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import require_api_key
from app.db.repositories import QueryLogRepository
from app.db.session import get_db
from app.schemas import HistoryItem, HistoryResponse

router = APIRouter(tags=["history"], dependencies=[Depends(require_api_key)])


@router.get("/history", response_model=HistoryResponse)
def get_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> HistoryResponse:
    """Most recent queries first."""
    repo = QueryLogRepository(db)
    items = [
        HistoryItem(
            id=log.id,
            query=log.user_query,
            sql=log.generated_sql,
            answer=log.final_answer,
            success=bool(log.success),
            error=log.error_message,
            execution_time_ms=log.execution_time_ms,
            created_at=log.created_at,
        )
        for log in repo.list_recent(limit=limit, offset=offset)
    ]
    return HistoryResponse(total=repo.count(), limit=limit, offset=offset, history=items)
