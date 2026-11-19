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


def _wait_phrase(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = round(minutes / 60)
    return f"{hours} hour{'s' if hours != 1 else ''}"


class LLMRateLimitError(LLMError):
    """The model provider refused the call because a usage limit was reached."""

    user_message = "The AI model has reached its usage limit. Please try again later."

    def __init__(self, detail: str = "", *, retry_after_seconds: float | None = None) -> None:
        message = None
        if retry_after_seconds is not None:
            message = (
                "The AI model has reached its usage limit. "
                f"Please try again in about {_wait_phrase(retry_after_seconds)}."
            )
        super().__init__(detail, user_message=message)
        self.retry_after_seconds = retry_after_seconds


class RestrictedQueryError(PlatformError):
    user_message = (
        "The size of the dataset is not available here. "
        "Ask about specific companies, funds or dates instead."
    )


class UnanswerableQueryError(PlatformError):
    user_message = (
        "This question cannot be answered from the available data: the schema "
        "has no tables or columns that match it."
    )


class UnsafeSQLError(PlatformError):
    user_message = "The generated query was rejected by the SQL safety checks."


class QueryExecutionError(PlatformError):
    user_message = "The generated query failed to execute against the database."
