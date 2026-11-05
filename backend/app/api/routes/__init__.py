from fastapi import APIRouter

from app.api.routes import admin, health, history, metrics, query, stats

api_router = APIRouter(prefix="/api")
for module in (health, query, history, stats, metrics, admin):
    api_router.include_router(module.router)

__all__ = ["api_router"]
