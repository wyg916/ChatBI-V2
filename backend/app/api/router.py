from fastapi import APIRouter

from app.api.routes import analysis, attachments, auth, chat, content, datasources, evaluation, queries, security, semantic, system

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(attachments.router)
api_router.include_router(security.router)
api_router.include_router(datasources.router)
api_router.include_router(semantic.router)
api_router.include_router(content.router)
api_router.include_router(evaluation.router)
api_router.include_router(queries.router)
api_router.include_router(analysis.router)
