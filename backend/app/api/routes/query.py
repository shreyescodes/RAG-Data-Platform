from fastapi import APIRouter, Depends, Request

from app.agents.orchestrator import QueryOrchestrator
from app.api.dependencies import get_orchestrator
from app.core.config import get_settings
from app.core.rate_limit import limiter
from app.core.security import require_api_key
from app.schemas import QueryRequest, QueryResponse

router = APIRouter(tags=["query"], dependencies=[Depends(require_api_key)])


@router.post("/query", response_model=QueryResponse)
@limiter.limit(lambda: get_settings().rate_limit_query)
async def run_query(
    request: Request,
    body: QueryRequest,
    orchestrator: QueryOrchestrator = Depends(get_orchestrator),
) -> QueryResponse:
    """Answer a natural-language question about the financial dataset.

    Pipeline failures that are the query's fault (unanswerable question,
    rejected SQL, ...) return 200 with `success: false` and a user-facing
    `error`, so clients can render them alongside the trace.
    """
    return await orchestrator.run(body.query)
