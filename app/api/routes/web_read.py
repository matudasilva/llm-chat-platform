from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas.web_read import WebReadOut
from app.services.web_read import (
    WebReadBlockedError,
    WebReadFetchError,
    WebReadService,
    get_web_read_service,
)


router = APIRouter(prefix="/web-read", tags=["web-read"])


@router.get("", response_model=WebReadOut)
async def read_web_page(
    url: str = Query(..., min_length=1),
    reader: WebReadService = Depends(get_web_read_service),
) -> WebReadOut:
    try:
        result = await reader.read_url(url)
    except WebReadBlockedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except WebReadFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return WebReadOut(
        url=result.url,
        final_url=result.final_url,
        content_type=result.content_type,
        title=result.title,
        text=result.text,
        truncated=result.truncated,
    )
