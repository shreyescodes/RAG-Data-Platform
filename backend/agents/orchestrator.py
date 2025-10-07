from typing import Dict, Any
from .retrieval_agent import RetrievalAgent
from .analysis_agent import AnalysisAgent
from .enrichment_agent import EnrichmentAgent
from ..db.models import QueryLog
from sqlalchemy.orm import Session
import time
from datetime import datetime


class AgentOrchestrator:
    """
    Orchestrates the multi-agent workflow:
    1. RetrievalAgent - Retrieves data from database
    2. AnalysisAgent - Analyzes and summarizes results
    3. EnrichmentAgent - Enriches with external API data (optional)
    """

    def __init__(self, retrieval_agent: RetrievalAgent, db: Session):
        self.retrieval_agent = retrieval_agent
        self.analysis_agent = AnalysisAgent()
        self.enrichment_agent = EnrichmentAgent()
        self.db = db

    async def process_query(self, user_query: str) -> Dict[str, Any]:
        """
        Main orchestration workflow
        """
        start_time = time.time()

        context = {
            "query": user_query,
            "timestamp": datetime.utcnow().isoformat()
        }

        # Step 1: Retrieval Agent - Get data from database
        retrieval_result = await self.retrieval_agent.execute(context)
        context["retrieval_result"] = retrieval_result

        if not retrieval_result.get("success"):
            # Log failed query
            self._log_query(
                user_query=user_query,
                generated_sql=retrieval_result.get("sql"),
                final_answer=None,
                success=False,
                error_message=retrieval_result.get("error"),
                execution_time_ms=(time.time() - start_time) * 1000,
                agent_reasoning=self._combine_reasoning([retrieval_result])
            )

            return {
                "success": False,
                "error": retrieval_result.get("error"),
                "query": user_query,
                "execution_time_ms": (time.time() - start_time) * 1000
            }

        # Step 2: Analysis Agent - Analyze and summarize
        analysis_result = await self.analysis_agent.execute(context)
        context["analysis_result"] = analysis_result

        # Step 3: Enrichment Agent - Add external data (if applicable)
        enrichment_result = await self.enrichment_agent.execute(context)
        context["enrichment_result"] = enrichment_result

        # Combine results
        execution_time_ms = (time.time() - start_time) * 1000

        final_response = {
            "success": True,
            "query": user_query,
            "sql": retrieval_result.get("sql"),
            "answer": analysis_result.get("answer"),
            "summary": analysis_result.get("summary"),
            "insights": analysis_result.get("insights", []),
            "data": retrieval_result.get("data"),
            "row_count": retrieval_result.get("row_count"),
            "relevant_tables": retrieval_result.get("relevant_tables"),
            "enriched_data": enrichment_result.get("enriched_data", {}),
            "execution_time_ms": execution_time_ms,
            "agent_flow": {
                "retrieval": "completed",
                "analysis": "completed",
                "enrichment": "completed" if enrichment_result.get("enriched_data") else "skipped"
            }
        }

        # Log successful query
        self._log_query(
            user_query=user_query,
            generated_sql=retrieval_result.get("sql"),
            sql_result=str(retrieval_result.get("data", [])[:5]),  # First 5 rows
            final_answer=analysis_result.get("answer"),
            context_used=str(retrieval_result.get("relevant_tables")),
            success=True,
            execution_time_ms=execution_time_ms,
            agent_reasoning=self._combine_reasoning([
                retrieval_result,
                analysis_result,
                enrichment_result
            ])
        )

        return final_response

    def _combine_reasoning(self, results: list) -> str:
        """Combine reasoning logs from all agents"""
        all_reasoning = []

        for result in results:
            if result and "reasoning" in result:
                all_reasoning.extend(result["reasoning"])

        import json
        return json.dumps(all_reasoning, indent=2)

    def _log_query(
        self,
        user_query: str,
        generated_sql: str = None,
        sql_result: str = None,
        final_answer: str = None,
        context_used: str = None,
        success: bool = True,
        error_message: str = None,
        execution_time_ms: float = 0,
        agent_reasoning: str = None
    ):
        """Log query to database"""
        try:
            query_log = QueryLog(
                user_query=user_query,
                generated_sql=generated_sql,
                sql_result=sql_result,
                final_answer=final_answer,
                context_used=context_used,
                agent_reasoning=agent_reasoning,
                execution_time_ms=execution_time_ms,
                success=success,
                error_message=error_message
            )

            self.db.add(query_log)
            self.db.commit()
        except Exception as e:
            print(f"Error logging query: {e}")
            self.db.rollback()
