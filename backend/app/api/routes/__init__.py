from fastapi import APIRouter

from app.api.routes import admin, health, history, query, stats

api_router = APIRouter(prefix="/api")
for module in (health, query, history, stats, admin):
    api_router.include_router(module.router)

__all__ = ["api_router"]
