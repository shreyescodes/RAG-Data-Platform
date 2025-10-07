import openai
import os
from typing import Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()


class SQLGenerator:
    def __init__(self):
        self.client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def generate_sql(
        self,
        query: str,
        relevant_tables: List[str],
        table_columns: Dict[str, List[str]],
        schema_context: str = ""
    ) -> Dict[str, any]:
        """Generate SQL query from natural language using GPT-4"""

        schema_info = self._format_schema_context(relevant_tables, table_columns)

        prompt = f"""You are an expert SQL query generator. Given a natural language question and database schema information, generate a valid PostgreSQL query.

Database Schema:
{schema_info}

Additional Context:
- The database contains financial data for companies and portfolio investments
- Use appropriate JOINs when querying multiple tables
- Use aggregations (SUM, AVG, COUNT) when appropriate
- Format dates properly using PostgreSQL date functions
- Return only the SQL query, no explanations

Question: {query}

Generate a valid PostgreSQL query to answer this question. Return ONLY the SQL query without any markdown formatting or explanations."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an expert SQL query generator. Return only valid PostgreSQL queries without any formatting or explanations."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=500
            )

            sql_query = response.choices[0].message.content.strip()
            sql_query = sql_query.replace("```sql", "").replace("```", "").strip()

            return {
                "sql": sql_query,
                "relevant_tables": relevant_tables,
                "reasoning": "Generated SQL based on schema context and natural language query"
            }

        except Exception as e:
            return {
                "sql": None,
                "error": str(e),
                "relevant_tables": relevant_tables
            }

    def _format_schema_context(self, tables: List[str], table_columns: Dict[str, List[str]]) -> str:
        """Format schema information for the prompt"""
        schema_lines = []

        for table in tables:
            if table in table_columns:
                columns = ", ".join(table_columns[table])
                schema_lines.append(f"Table '{table}': columns ({columns})")
            else:
                schema_lines.append(f"Table '{table}'")

        return "\n".join(schema_lines)

    def explain_query(self, sql: str, result: any) -> str:
        """Generate human-readable explanation of the query and result"""

        prompt = f"""Given this SQL query and its result, provide a clear, concise explanation in plain English.

SQL Query:
{sql}

Result:
{result}

Provide a brief explanation of what the query does and what the result means. Keep it under 2 sentences."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that explains SQL queries and results in plain English."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=200
            )

            return response.choices[0].message.content.strip()

        except Exception as e:
            return f"Query executed successfully. Result: {result}"
