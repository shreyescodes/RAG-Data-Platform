import asyncio
import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.agents.orchestrator import QueryOrchestrator
from app.api.dependencies import (
    enforce_daily_limits,
    get_orchestrator,
    get_services,
    get_visitor_id,
)
from app.container import ServiceContainer
from app.core.config import Settings, get_settings
from app.core.rate_limit import limiter
from app.core.security import require_api_key
from app.db.session import get_session_factory
from app.schemas import QueryRequest, QueryResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["query"], dependencies=[Depends(require_api_key)])

# Keeps idle proxies from closing the stream during a slow LLM call.
_KEEP_ALIVE_SECONDS = 15.0


@router.post("/query", response_model=QueryResponse, dependencies=[Depends(enforce_daily_limits)])
@limiter.limit(lambda: get_settings().rate_limit_query)
async def run_query(
    request: Request,
    body: QueryRequest,
    visitor_id: str | None = Depends(get_visitor_id),
    orchestrator: QueryOrchestrator = Depends(get_orchestrator),
) -> QueryResponse:
    """Answer a natural-language question about the financial dataset.

    Pipeline failures that are the query's fault (unanswerable question,
    rejected SQL, ...) return 200 with `success: false` and a user-facing
    `error`, so clients can render them alongside the trace.
    """
    return await orchestrator.run(
        body.query, visitor_id=visitor_id, conversation_id=body.conversation_id
    )


def _event(name: str, data: str) -> str:
    return f"event: {name}\ndata: {data}\n\n"


@router.post("/query/stream", dependencies=[Depends(enforce_daily_limits)])
@limiter.limit(lambda: get_settings().rate_limit_query)
async def stream_query(
    request: Request,
    body: QueryRequest,
    visitor_id: str | None = Depends(get_visitor_id),
    services: ServiceContainer = Depends(get_services),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Like `POST /query`, as server-sent events: `stage` updates, then one `result`."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    def on_stage(stage: str, status: str) -> None:
        queue.put_nowait(_event("stage", json.dumps({"stage": stage, "status": status})))

    async def answer() -> None:
        try:
            # Opened here because request-scoped sessions may close before a stream ends.
            with get_session_factory()() as db:
                orchestrator = get_orchestrator(services=services, db=db, settings=settings)
                response = await orchestrator.run(
                    body.query,
                    visitor_id=visitor_id,
                    conversation_id=body.conversation_id,
                    on_stage=on_stage,
                )
            queue.put_nowait(_event("result", response.model_dump_json()))
        except Exception:
            logger.exception("Streaming query failed")
            queue.put_nowait(_event("error", json.dumps({"detail": "An internal error occurred."})))
        finally:
            queue.put_nowait(None)

    async def events() -> AsyncIterator[str]:
        task = asyncio.create_task(answer())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), _KEEP_ALIVE_SECONDS)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    return
                yield item
        finally:
            task.cancel()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
