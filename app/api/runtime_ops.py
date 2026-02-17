from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Response, status

from app.services.readiness import ReadinessChecker, get_readiness_checker

router = APIRouter(tags=["ops"])


@router.get("/healthz")
async def healthz():
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(checker: ReadinessChecker = Depends(get_readiness_checker)):
    result = await checker.check()
    if result.get("status") == "ok":
        return result
    return Response(
        content=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
