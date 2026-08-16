from fastapi import APIRouter

from app.api.routes import datasources, semantic, system

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(datasources.router)
api_router.include_router(semantic.router)
