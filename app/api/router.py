from fastapi import APIRouter

from app.api.routes import chat

api_router = APIRouter()

# Chat routes
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
