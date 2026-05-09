from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.http.request_context import get_request_id
from app.api.deps import get_notion_write_service
from app.schemas.notion_write import (
    NotionPageWriteIn,
    NotionRowWriteIn,
    NotionWriteOut,
)
from app.services.notion_write import (
    NotionWriteBlockedError,
    NotionWriteDisabledError,
    NotionWriteExecutionError,
    NotionWriteService,
    NotionWriteValidationError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notion-write", tags=["notion-write"])


@router.post("/page", response_model=NotionWriteOut)
async def write_page(
    payload: NotionPageWriteIn,
    service: NotionWriteService = Depends(get_notion_write_service),
) -> NotionWriteOut:
    request_id = get_request_id()

    try:
        result = await service.write_page(payload.page_id, payload.updates, request_id=request_id)
    except NotionWriteDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NotionWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except NotionWriteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NotionWriteExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("unexpected error in /notion-write/page")
        raise HTTPException(status_code=500, detail="Internal error") from exc

    return NotionWriteOut(
        operation=result.operation,
        target_type=result.target_type,
        target_id=result.target_id,
        notion_object_id=result.notion_object_id,
        status=result.status,
        request_id=result.request_id,
    )


@router.post("/row", response_model=NotionWriteOut)
async def write_row(
    payload: NotionRowWriteIn,
    service: NotionWriteService = Depends(get_notion_write_service),
) -> NotionWriteOut:
    request_id = get_request_id()

    try:
        if payload.operation == "create":
            result = await service.create_row(
                payload.database_id,
                payload.properties,
                request_id=request_id,
            )
        else:
            result = await service.update_row(
                payload.database_id,
                payload.row_id or "",
                payload.properties,
                request_id=request_id,
            )
    except NotionWriteDisabledError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NotionWriteBlockedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except NotionWriteValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NotionWriteExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("unexpected error in /notion-write/row")
        raise HTTPException(status_code=500, detail="Internal error") from exc

    return NotionWriteOut(
        operation=result.operation,
        target_type=result.target_type,
        target_id=result.target_id,
        notion_object_id=result.notion_object_id,
        status=result.status,
        request_id=result.request_id,
    )
