from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from ..db.database import get_db, init_db
from ..rag.vector_store import FAISSVectorStore
from ..rag.schema_indexer import SchemaIndexer
from ..agents.retrieval_agent import RetrievalAgent
from ..agents.orchestrator import AgentOrchestrator
from ..db.models import QueryLog
import os

app = FastAPI(
    title="RAG Platform API",
    description="Multi-agent RAG system for financial data querying",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize vector store
vector_store = FAISSVectorStore(dimension=1536, index_path="data/faiss_index")


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


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    print("Initializing database...")
    init_db()
    print("Database initialized")


@app.get("/")
async def root():
    return {
        "message": "RAG Platform API",
        "version": "1.0.0",
        "endpoints": {
            "query": "/api/query",
            "history": "/api/history",
            "stats": "/api/stats",
            "health": "/api/health"
        }
    }


@app.get("/api/health")
async def health_check(db: Session = Depends(get_db)):
    """Health check endpoint"""
    try:
        # Check database connection
        db.execute("SELECT 1")

        # Check vector store
        vector_stats = vector_store.get_stats()

        return {
            "status": "healthy",
            "database": "connected",
            "vector_store": vector_stats
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


@app.post("/api/query", response_model=QueryResponse)
async def query(request: QueryRequest, db: Session = Depends(get_db)):
    """
    Main query endpoint - orchestrates multi-agent workflow
    """
    try:
        # Create retrieval agent
        retrieval_agent = RetrievalAgent(vector_store, db)

        # Create orchestrator
        orchestrator = AgentOrchestrator(retrieval_agent, db)

        # Process query through multi-agent system
        result = await orchestrator.process_query(request.query)

        return QueryResponse(**result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/history")
async def get_query_history(
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    """Get query history"""
    try:
        logs = db.query(QueryLog).order_by(
            QueryLog.created_at.desc()
        ).limit(limit).offset(offset).all()

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
                    "created_at": log.created_at.isoformat()
                }
                for log in logs
            ]
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    """Get platform statistics"""
    try:
        from ..db.models import Company, FinancialStatement, PortfolioCompany, PerformanceMetric, MarketData

        total_queries = db.query(QueryLog).count()
        successful_queries = db.query(QueryLog).filter(QueryLog.success == True).count()

        stats = {
            "queries": {
                "total": total_queries,
                "successful": successful_queries,
                "success_rate": (successful_queries / total_queries * 100) if total_queries > 0 else 0
            },
            "database": {
                "companies": db.query(Company).count(),
                "financial_statements": db.query(FinancialStatement).count(),
                "portfolio_companies": db.query(PortfolioCompany).count(),
                "performance_metrics": db.query(PerformanceMetric).count(),
                "market_data": db.query(MarketData).count()
            },
            "vector_store": vector_store.get_stats()
        }

        return stats

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/index-schema")
async def index_schema(db: Session = Depends(get_db)):
    """Index database schema into vector store"""
    try:
        schema_indexer = SchemaIndexer(vector_store)
        schema_indexer.index_database_schema()

        return {
            "success": True,
            "message": "Database schema indexed successfully",
            "stats": vector_store.get_stats()
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
