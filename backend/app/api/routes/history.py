from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_visitor_id
from app.core.security import require_api_key
from app.db.repositories import QueryLogRepository
from app.db.session import get_db
from app.schemas import ConversationResponse, HistoryItem, HistoryResponse, QueryResponse

router = APIRouter(tags=["history"], dependencies=[Depends(require_api_key)])


@router.get("/history", response_model=HistoryResponse)
def get_history(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    visitor_id: str | None = Depends(get_visitor_id),
    db: Session = Depends(get_db),
) -> HistoryResponse:
    """The calling visitor's most recent queries, newest first."""
    if visitor_id is None:
        return HistoryResponse(total=0, limit=limit, offset=offset, history=[])
    repo = QueryLogRepository(db)
    items = [
        HistoryItem(
            id=log.id,
            conversation_id=log.conversation_id,
            query=log.user_query,
            sql=log.generated_sql,
            answer=log.final_answer,
            success=bool(log.success),
            error=log.error_message if not log.success else None,
            execution_time_ms=log.execution_time_ms,
            created_at=log.created_at,
        )
        for log in repo.list_for_visitor(visitor_id, limit=limit, offset=offset)
    ]
    return HistoryResponse(
        total=repo.count_for_visitor(visitor_id), limit=limit, offset=offset, history=items
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: str,
    visitor_id: str | None = Depends(get_visitor_id),
    db: Session = Depends(get_db),
) -> ConversationResponse:
    """A saved conversation, without running anything again."""
    logs = QueryLogRepository(db).conversation(visitor_id, conversation_id) if visitor_id else []
    turns = [
        QueryResponse.model_validate_json(log.response_json) for log in logs if log.response_json
    ]
    if not turns:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return ConversationResponse(conversation_id=conversation_id, turns=turns)
