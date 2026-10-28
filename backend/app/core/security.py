"""Authentication dependency and HTTP hardening middleware."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, Response, Security, status
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Settings, get_settings
from app.core.logging import request_id_ctx

API_KEY_HEADER_NAME = "X-API-Key"
REQUEST_ID_HEADER_NAME = "X-Request-ID"

_api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


async def require_api_key(
    api_key: str | None = Security(_api_key_header),
    settings: Settings = Depends(get_settings),
) -> None:
    """Reject the request unless it carries the configured API key.

    Auth is skipped when no key is configured; `Settings` refuses to start in
    production without one.
    """
    if not settings.auth_enabled:
        return
    expected = settings.api_key.get_secret_value()
    if api_key is None or not secrets.compare_digest(api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": API_KEY_HEADER_NAME},
        )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign each request an ID, expose it in logs and echo it back."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER_NAME, "")
        # Accept a caller-provided ID only if it is short and printable.
        request_id = (
            incoming if 0 < len(incoming) <= 64 and incoming.isprintable() else None
        ) or uuid.uuid4().hex
        token = request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers[REQUEST_ID_HEADER_NAME] = request_id
        return response
