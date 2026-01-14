import time
import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.session import get_db
from app.services.usage_logger import log_usage_event

router = APIRouter(tags=["chat"])


@router.post("")
async def chat(db: AsyncSession = Depends(get_db)):
    start = time.perf_counter()
    request_id = uuid.uuid4()

    status = "error"
    error_message = None

    try:
        # Stub: aún no hay proveedor
        reply_text = "stub: provider not configured yet"
        status = "ok"
        return {"reply": reply_text}

    except Exception as e:
        error_message = str(e)
        raise

    finally:
        latency_ms = int((time.perf_counter() - start) * 1000)

        # Best-effort logging (no rompe el endpoint)
        try:
            await log_usage_event(
                db=db,
                provider="stub",
                model_version="local",
                prompt_version="v0",
                status=status,
                request_id=request_id,
                latency_ms=latency_ms,
                error_message=error_message,
            )
        except Exception:
            pass
