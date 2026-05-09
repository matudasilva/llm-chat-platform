from fastapi import APIRouter

from app.api.routes.chat import router as chat_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.notion_read import router as notion_read_router
from app.api.routes.notion_write import router as notion_write_router
from app.api.routes.usage_events import router as usage_events_router
from app.api.routes.ui import router as ui_router
from app.api.routes.web_read import router as web_read_router

api_router = APIRouter()

# Write-path
api_router.include_router(chat_router, prefix="/chat")

# Read-path
api_router.include_router(conversations_router)
api_router.include_router(usage_events_router)
api_router.include_router(web_read_router)
api_router.include_router(notion_read_router)
api_router.include_router(notion_write_router)

# ui path
api_router.include_router(ui_router)
