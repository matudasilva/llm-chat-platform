# app/api/routes/ui.py


from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["ui"])

_STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
_UI_FILE = _STATIC_DIR / "chat.html"


@router.get("/ui", include_in_schema=False)
async def ui() -> FileResponse:
    return FileResponse(_UI_FILE, media_type="text/html")