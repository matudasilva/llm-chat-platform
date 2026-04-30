"""
HTTP routes for Notion Read API.

Provides GET /notion-read/page endpoint for reading Notion page metadata.
Status codes mapped by error layer: 422 (validation), 403 (blocked), 502-504 (MCP).
"""

import logging
from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas.notion_read import NotionPageOut
from app.services.notion_read import (
    NotionReadBlockedError,
    NotionReadError,
    NotionReadService,
)
from app.services.notion_read_client import (
    NotionMCPError,
    NotionMCPExecutionError,
    NotionMCPProtocolError,
    NotionMCPTimeoutError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notion-read", tags=["notion-read"])


@router.get("/page", response_model=NotionPageOut)
async def get_notion_page(
    page_id: str = Query(..., min_length=1, description="Notion page ID"),
    request: Request = None,
) -> NotionPageOut:
    """
    Get Notion page metadata (read-only, metadata-only MVP).

    Query Parameters:
    - page_id: Notion page ID (required, non-empty)

    Responses:
    - 200: Success with NotionPageOut (page_id, title, url, created_time, last_edited_time)
    - 422: Missing or invalid query params (FastAPI auto-validation)
    - 403: Page ID not in allowlist (NotionReadBlockedError)
    - 502: MCP protocol or upstream Notion API error
    - 504: MCP request timeout
    - 503: MCP subprocess unavailable (graceful degradation)
    - 500: Unexpected error

    Readiness: This endpoint can return 503 even if /readyz is true
    (Decision 2: readyz does not check MCP health).
    """
    # Get NotionReadService from app state
    app = request.app if request else None
    if not app or not hasattr(app.state, "notion_read_service"):
        logger.error("NotionReadService not available in app state")
        raise HTTPException(
            status_code=503,
            detail="Notion Read service unavailable",
        )

    service: NotionReadService = app.state.notion_read_service

    try:
        logger.info(f"GET /notion-read/page?page_id={page_id}")
        page_data = await service.get_page(page_id)

        # Validate response against schema
        return NotionPageOut(**page_data)

    except NotionReadBlockedError as e:
        # Page ID not in allowlist
        logger.warning(f"Page blocked by allowlist: {e}")
        raise HTTPException(
            status_code=403,
            detail="Access denied: page not in allowlist",
        )

    except NotionMCPTimeoutError as e:
        # MCP timeout
        logger.warning(f"MCP timeout: {e}")
        raise HTTPException(
            status_code=504,
            detail="Notion Read service timeout",
        )

    except NotionMCPProtocolError as e:
        # MCP protocol or subprocess error
        logger.error(f"MCP protocol error: {e}")
        raise HTTPException(
            status_code=502,
            detail="Notion Read service error (protocol)",
        )

    except NotionMCPExecutionError as e:
        # Notion API error from MCP server
        logger.error(f"MCP execution error: {e}")
        raise HTTPException(
            status_code=502,
            detail="Notion API error",
        )

    except NotionMCPError as e:
        # Other MCP errors
        logger.error(f"MCP error: {e}")
        raise HTTPException(
            status_code=502,
            detail="Notion Read service error",
        )

    except NotionReadError as e:
        # Service-layer error (unexpected)
        logger.error(f"Notion Read service error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal error",
        )

    except Exception as e:
        # Unexpected error
        logger.error(f"Unexpected error in /notion-read/page: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal error",
        )
