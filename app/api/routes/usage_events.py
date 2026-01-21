from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.session import get_db
from app.infra.schemas.usage_events import UsageEventOut
from app.models.usage_event import UsageEvent


router = APIRouter(prefix="/usage-events", tags=["usage-events"])


@router.get("", response_model=List[UsageEventOut])
async def list_usage_events(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    order: Literal["asc", "desc"] = Query("desc"),

    # filtros
    from_dt: Optional[datetime] = Query(None, alias="from"),
    to_dt: Optional[datetime] = Query(None, alias="to"),

    provider: Optional[str] = Query(None),
    model_version: Optional[str] = Query(None),
    request_id: Optional[UUID] = Query(None),          # <- FIX
    conversation_id: Optional[UUID] = Query(None),
    status: Optional[Literal["success", "error"]] = Query(None),
) -> List[UsageEventOut]:
    """
    Read-path de auditoría: lista UsageEvents con filtros.
    Orden determinista por timestamp (+ id).
    """
    if from_dt is not None and to_dt is not None and from_dt > to_dt:
        raise HTTPException(status_code=422, detail="'from' must be <= 'to'")

    stmt = select(UsageEvent)

    if from_dt is not None:
        stmt = stmt.where(UsageEvent.timestamp >= from_dt)
    if to_dt is not None:
        stmt = stmt.where(UsageEvent.timestamp <= to_dt)

    if provider is not None:
        stmt = stmt.where(UsageEvent.provider == provider)
    if model_version is not None:
        stmt = stmt.where(UsageEvent.model_version == model_version)
    if request_id is not None:
        stmt = stmt.where(UsageEvent.request_id == request_id)
    if conversation_id is not None:
        stmt = stmt.where(UsageEvent.conversation_id == conversation_id)
    if status is not None:
        stmt = stmt.where(UsageEvent.status == status)

    order_by = (UsageEvent.timestamp.asc(), UsageEvent.id.asc())
    if order == "desc":
        order_by = (UsageEvent.timestamp.desc(), UsageEvent.id.desc())

    stmt = stmt.order_by(*order_by).limit(limit).offset(offset)

    result = await db.execute(stmt)
    return result.scalars().all()
