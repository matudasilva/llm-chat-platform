from fastapi import APIRouter

from app.api.routes.chat import router as chat_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.usage_events import router as usage_events_router

api_router = APIRouter()

# Write-path
api_router.include_router(chat_router, prefix="/chat")

# Read-path
api_router.include_router(conversations_router)
api_router.include_router(usage_events_router)
