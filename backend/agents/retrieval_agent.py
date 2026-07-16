from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..rag.schema_indexer import SchemaIndexer
from ..rag.sql_generator import SQLGenerator
from ..rag.vector_store import FAISSVectorStore
from .base_agent import BaseAgent


class RetrievalAgent(BaseAgent):
    def __init__(self, vector_store: FAISSVectorStore, db: Session):
        super().__init__("RetrievalAgent")
        self.vector_store = vector_store
        self.schema_indexer = SchemaIndexer(vector_store)
        self.sql_generator = SQLGenerator()
        self.db = db

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Retrieval Agent workflow:
        1. Analyze user query
        2. Find relevant tables and columns using vector search
        3. Generate SQL query
        4. Execute query against database
        5. Return results
        """
        user_query = context.get("query", "")

        self.log_reasoning("query_received", user_query)

        # Step 1: Find relevant schema elements
        relevant_tables = self.schema_indexer.get_relevant_tables(user_query, k=5)
        table_columns = self.schema_indexer.get_relevant_columns(user_query, k=10)

        self.log_reasoning(
            "schema_retrieval",
            {"relevant_tables": relevant_tables, "table_columns": table_columns},
        )

        # Step 2: Generate SQL query
        sql_result = self.sql_generator.generate_sql(
            user_query, relevant_tables, table_columns
        )

        if not sql_result.get("sql"):
            self.log_reasoning("sql_generation_failed", sql_result.get("error"))
            return {
                "success": False,
                "error": "Failed to generate SQL query",
                "reasoning": self.get_reasoning(),
            }

        generated_sql = sql_result["sql"]
        self.log_reasoning("sql_generated", generated_sql)

        # Step 3: Execute SQL query
        try:
            import sqlglot
            from sqlglot import exp
            from starlette.concurrency import run_in_threadpool

            # Validate query is strictly a SELECT
            try:
                expressions = sqlglot.parse(generated_sql, read="postgres")
                for expression in expressions:
                    if not isinstance(expression, exp.Select):
                        raise ValueError(f"Only SELECT queries are allowed. Found: {type(expression).__name__}")
            except Exception as parse_error:
                raise ValueError(f"SQL Validation failed: {parse_error}")

            def _execute():
                res = self.db.execute(text(generated_sql))
                return res.fetchall(), list(res.keys())

            rows, columns = await run_in_threadpool(_execute)

            # Convert to list of dicts
            data = [dict(zip(columns, row)) for row in rows]

            self.log_reasoning(
                "query_executed", {"rows_returned": len(data), "columns": list(columns)}
            )

            return {
                "success": True,
                "sql": generated_sql,
                "data": data,
                "row_count": len(data),
                "relevant_tables": relevant_tables,
                "reasoning": self.get_reasoning(),
            }

        except Exception as e:
            self.log_reasoning("query_execution_failed", str(e))
            return {
                "success": False,
                "error": f"Query execution failed: {str(e)}",
                "sql": generated_sql,
                "reasoning": self.get_reasoning(),
            }
