from typing import Dict, Any
from .base_agent import BaseAgent
import openai
import os


class AnalysisAgent(BaseAgent):
    def __init__(self):
        super().__init__("AnalysisAgent")
        self.client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analysis Agent workflow:
        1. Receive query results from RetrievalAgent
        2. Analyze and summarize the data
        3. Provide insights and reasoning
        4. Generate human-readable answer
        """
        user_query = context.get("query", "")
        retrieval_result = context.get("retrieval_result", {})

        self.log_reasoning("analysis_started", {
            "query": user_query,
            "data_available": retrieval_result.get("success", False)
        })

        if not retrieval_result.get("success"):
            return {
                "success": False,
                "error": "No data to analyze",
                "reasoning": self.get_reasoning()
            }

        sql_query = retrieval_result.get("sql", "")
        data = retrieval_result.get("data", [])
        row_count = retrieval_result.get("row_count", 0)

        # Generate analysis and summary
        analysis = await self._analyze_results(user_query, sql_query, data)

        self.log_reasoning("analysis_completed", {
            "summary_generated": True,
            "insights_count": len(analysis.get("insights", []))
        })

        return {
            "success": True,
            "answer": analysis.get("answer", ""),
            "summary": analysis.get("summary", ""),
            "insights": analysis.get("insights", []),
            "reasoning": self.get_reasoning()
        }

    async def _analyze_results(self, query: str, sql: str, data: list) -> Dict[str, Any]:
        """Use GPT to analyze and summarize query results"""

        # Limit data for context (first 10 rows)
        data_sample = data[:10] if len(data) > 10 else data

        prompt = f"""Analyze the following database query results and provide a clear, concise answer.

User Question: {query}

SQL Query:
{sql}

Results (showing {len(data_sample)} of {len(data)} rows):
{data_sample}

Provide:
1. A direct answer to the user's question
2. A brief summary of the findings
3. 2-3 key insights from the data

Format your response as JSON with keys: "answer", "summary", "insights" (array)"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a financial data analyst. Provide clear, accurate analysis of query results."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=500,
                response_format={"type": "json_object"}
            )

            import json
            result = json.loads(response.choices[0].message.content)

            return result

        except Exception as e:
            # Fallback if GPT fails
            return {
                "answer": f"Query returned {len(data)} results.",
                "summary": f"The SQL query successfully retrieved {len(data)} rows from the database.",
                "insights": ["Data retrieved successfully"]
            }
