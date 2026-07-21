import logging
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from ..agents.orchestrator import AgentOrchestrator
from ..agents.retrieval_agent import RetrievalAgent
from ..config import settings
from ..db.database import get_db, init_db
from ..db.models import QueryLog
from ..rag.schema_indexer import SchemaIndexer
from ..rag.vector_store import FAISSVectorStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiter (Medium #7)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup"""
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized")
    yield


app = FastAPI(
    title="RAG Platform API",
    description="Multi-agent RAG system for financial data querying",
    version="1.0.0",
    lifespan=lifespan,
    # Disable automatic OpenAPI docs in production if desired
    # docs_url=None, redoc_url=None,
)

# Attach rate-limiter state and its error handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------------------------------------------------------------------------
# Security headers middleware (Low #13)
# ---------------------------------------------------------------------------
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=()"
        return response


app.add_middleware(SecurityHeadersMiddleware)

# ---------------------------------------------------------------------------
# CORS middleware — restricted origins (Critical #2)
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

# ---------------------------------------------------------------------------
# API Key authentication (High #3 & #6)
# ---------------------------------------------------------------------------
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)):
    """
    Validate X-API-Key header.
    If settings.API_KEY is empty the check is skipped (dev mode).
    In production, always set a non-empty API_KEY.
    """
    if not settings.API_KEY:
        # API key enforcement disabled — allow all (dev only)
        return
    if api_key != settings.API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# ---------------------------------------------------------------------------
# Vector store (global singleton)
# ---------------------------------------------------------------------------
vector_store = FAISSVectorStore(
    dimension=settings.FAISS_DIMENSION,
    index_path=settings.FAISS_INDEX_PATH,
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class QueryRequest(BaseModel):
    query: str


class QueryResponse(BaseModel):
    success: bool
    query: str
    sql: Optional[str] = None
    answer: Optional[str] = None
    summary: Optional[str] = None
    insights: List[str] = []
    data: List[Dict[str, Any]] = []
    row_count: int = 0
    relevant_tables: List[str] = []
    enriched_data: Dict[str, Any] = {}
    execution_time_ms: float = 0
    agent_flow: Dict[str, str] = {}
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
async def root():
    return {
        "message": "RAG Platform API",
        "version": "1.0.0",
        "endpoints": {
            "query": "/api/query",
            "history": "/api/history",
            "stats": "/api/stats",
            "health": "/api/health",
        },
    }


@app.get("/api/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint"""
    try:
        await run_in_threadpool(db.execute, text("SELECT 1"))
        vector_stats = vector_store.get_stats()
        return {
            "status": "healthy",
            "database": "connected",
            "vector_store": vector_stats,
        }
    except Exception as e:
        logger.error("Health check failed: %s", e)
        return {"status": "unhealthy", "error": "Service unavailable"}


@app.post("/api/query", response_model=QueryResponse, dependencies=[Depends(verify_api_key)])
@limiter.limit("20/minute")
async def query(request: Request, body: QueryRequest, db: Session = Depends(get_db)):
    """
    Main query endpoint — orchestrates multi-agent workflow.
    Rate-limited to 20 requests/minute per IP (Medium #7).
    """
    try:
        retrieval_agent = RetrievalAgent(vector_store, db)
        orchestrator = AgentOrchestrator(retrieval_agent, db)
        result = await orchestrator.process_query(body.query)
        return QueryResponse(**result)
    except Exception as e:
        logger.exception("Unhandled error in /api/query")
        raise HTTPException(status_code=500, detail="An internal error occurred.")


@app.get("/api/history", dependencies=[Depends(verify_api_key)])
async def get_query_history(
    # Medium #8: cap limit to 100 to prevent memory DoS
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Get query history"""
    try:
        logs = (
            db.query(QueryLog)
            .order_by(QueryLog.created_at.desc())
            .limit(limit)
            .offset(offset)
            .all()
        )
        return {
            "total": db.query(QueryLog).count(),
            "limit": limit,
            "offset": offset,
            "history": [
                {
                    "id": log.id,
                    "query": log.user_query,
                    "sql": log.generated_sql,
                    "answer": log.final_answer,
                    "success": log.success,
                    "execution_time_ms": log.execution_time_ms,
                    "created_at": log.created_at.isoformat(),
                }
                for log in logs
            ],
        }
    except Exception as e:
        logger.exception("Unhandled error in /api/history")
        raise HTTPException(status_code=500, detail="An internal error occurred.")


@app.get("/api/stats", dependencies=[Depends(verify_api_key)])
async def get_stats(db: Session = Depends(get_db)):
    """Get platform statistics"""
    try:
        from ..db.models import (
            Company,
            FinancialStatement,
            MarketData,
            PerformanceMetric,
            PortfolioCompany,
        )

        total_queries = db.query(QueryLog).count()
        successful_queries = db.query(QueryLog).filter(QueryLog.success.is_(True)).count()

        stats = {
            "queries": {
                "total": total_queries,
                "successful": successful_queries,
                "success_rate": (successful_queries / total_queries * 100)
                if total_queries > 0
                else 0,
            },
            "database": {
                "companies": db.query(Company).count(),
                "financial_statements": db.query(FinancialStatement).count(),
                "portfolio_companies": db.query(PortfolioCompany).count(),
                "performance_metrics": db.query(PerformanceMetric).count(),
                "market_data": db.query(MarketData).count(),
            },
            "vector_store": vector_store.get_stats(),
        }
        return stats
    except Exception as e:
        logger.exception("Unhandled error in /api/stats")
        raise HTTPException(status_code=500, detail="An internal error occurred.")


# High #6: index-schema requires authentication (see verify_api_key dependency)
# and is rate-limited to 5/hour to prevent abuse of this expensive operation.
@app.post("/api/index-schema", dependencies=[Depends(verify_api_key)])
@limiter.limit("5/hour")
async def index_schema(request: Request, db: Session = Depends(get_db)):
    """Index database schema into vector store — admin operation, requires API key."""
    try:
        schema_indexer = SchemaIndexer(vector_store)
        schema_indexer.index_database_schema()
        return {
            "success": True,
            "message": "Database schema indexed successfully",
            "stats": vector_store.get_stats(),
        }
    except Exception as e:
        logger.exception("Unhandled error in /api/index-schema")
        raise HTTPException(status_code=500, detail="An internal error occurred.")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.API_HOST, port=settings.API_PORT)
