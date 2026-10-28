"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.concurrency import run_in_threadpool

from app import __version__
from app.api.routes import api_router
from app.container import build_services
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.rate_limit import limiter
from app.core.security import (
    API_KEY_HEADER_NAME,
    REQUEST_ID_HEADER_NAME,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    # Tests may inject their own services before startup.
    if getattr(app.state, "services", None) is None:
        app.state.services = build_services(settings)
        await run_in_threadpool(app.state.services.vector_store.warm_up)
    logger.info(
        "Started %s (env=%s, auth=%s, model=%s)",
        app.title,
        settings.environment,
        "on" if settings.auth_enabled else "off",
        settings.llm_model,
    )
    try:
        yield
    finally:
        await app.state.services.aclose()


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred."},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)

    app = FastAPI(
        title="RAG Data Platform API",
        description="Natural-language querying of financial data with a multi-agent RAG pipeline.",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.expose_docs else None,
    )
    app.state.settings = settings
    app.state.limiter = limiter

    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_exception_handler)

    # Middleware runs bottom-up: CORS sees the request first.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", API_KEY_HEADER_NAME, REQUEST_ID_HEADER_NAME],
        expose_headers=[REQUEST_ID_HEADER_NAME],
    )

    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": app.title, "version": __version__, "docs": app.docs_url or ""}

    return app


app = create_app()
