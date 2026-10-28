"""Domain exceptions.

Each carries a `user_message` that is safe to return to API clients; the
exception's own string may contain internal detail and is only logged.
"""

from __future__ import annotations


class PlatformError(Exception):
    user_message = "The request could not be completed."

    def __init__(
        self,
        detail: str = "",
        *,
        user_message: str | None = None,
        sql: str | None = None,
    ) -> None:
        super().__init__(detail or self.user_message)
        if user_message is not None:
            self.user_message = user_message
        # The SQL involved, if any, so failures can still be audited.
        self.sql = sql


class SchemaNotIndexedError(PlatformError):
    user_message = (
        "The schema index is empty. Seed the database and call "
        "POST /api/index-schema before querying."
    )


class LLMError(PlatformError):
    user_message = "The language model is unavailable. Please try again shortly."


class LLMNotConfiguredError(LLMError):
    user_message = "No LLM API key is configured on the server."


class UnanswerableQueryError(PlatformError):
    user_message = (
        "This question cannot be answered from the available data: the schema "
        "has no tables or columns that match it."
    )


class UnsafeSQLError(PlatformError):
    user_message = "The generated query was rejected by the SQL safety checks."


class QueryExecutionError(PlatformError):
    user_message = "The generated query failed to execute against the database."
