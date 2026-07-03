# app/api/routes/ui.py


from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ui"])

_STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
_UI_FILE = _STATIC_DIR / "chat.html"


@router.get("/ui", include_in_schema=False)
async def ui() -> FileResponse:
    # Deprecated (ORQ-19.6): superseded by the llm-chat-platform-web frontend.
    # Kept for now, not removed — removal is tracked for ORQ-20.
    logger.warning("deprecated_endpoint_used endpoint=/ui replacement=llm-chat-platform-web")
    return FileResponse(_UI_FILE, media_type="text/html")