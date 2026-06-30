# app/main.py
import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.ops import router as ops_router
from app.api.router import api_router
from app.api.runtime_ops import router as runtime_ops_router
from app.core.settings import settings
from app.http.middleware.request_context import RequestContextMiddleware
from app.http.middleware.request_size_limit import RequestSizeLimitMiddleware
from app.http.middleware.structured_logging import StructuredJsonLoggingMiddleware
from app.http.middleware.tenant import TenantContextFilter, TenantMiddleware
from app.infra.db.session import init_db, close_db
from app.services.notion_read import NotionReadService
from app.services.notion_read_client import (
    ControlledNotionReadClient,
    build_notion_mcp_child_env,
)


def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _configure_logging(app_env: str, log_level: str) -> None:
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s tenant_id=%(tenant_id)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    handler.setFormatter(formatter)

    handler.addFilter(TenantContextFilter())

    root = logging.getLogger()
    root.handlers = []
    root.setLevel(numeric_level)
    root.addHandler(handler)

    logging.getLogger("uvicorn").setLevel(numeric_level)
    logging.getLogger("uvicorn.error").setLevel(numeric_level)
    logging.getLogger("uvicorn.access").setLevel(numeric_level)

    root.info("logging configured", extra={"app_env": app_env, "log_level": log_level})


APP_ENV = _get_env("APP_ENV", "development")
LOG_LEVEL = _get_env("LOG_LEVEL", "INFO")
_configure_logging(APP_ENV, LOG_LEVEL)

logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("app starting application")
    init_db(app)          # <-- crea engine + sessionmaker en app.state

    # Initialize Notion Read service (optional, MVP)
    notion_mcp_client = None
    if settings.notion_mcp_enabled:
        try:
            logger.info("initializing Notion Read service")
            notion_mcp_client = ControlledNotionReadClient(
                command=settings.notion_mcp_server_command,
                args=settings.notion_mcp_server_args,
                cwd=settings.notion_mcp_server_cwd,
                env=build_notion_mcp_child_env(
                    os.environ,
                    settings.notion_allowed_page_ids,
                ),
                timeout_s=settings.notion_mcp_timeout_s,
            )
            await notion_mcp_client.start()
            service = NotionReadService(notion_mcp_client, settings)
            app.state.notion_read_service = service
            logger.info("Notion Read service initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Notion Read service: {e}")
            notion_mcp_client = None

    try:
        yield
    finally:
        # Shutdown Notion Read service
        if notion_mcp_client:
            try:
                logger.info("shutting down Notion Read service")
                await notion_mcp_client.stop()
            except Exception as e:
                logger.error(f"Error during Notion Read service shutdown: {e}")

        await close_db(app)  # <-- dispose engine


app = FastAPI(
    title="LLM Chat Platform API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(runtime_ops_router)

app.add_middleware(RequestContextMiddleware)
app.add_middleware(RequestSizeLimitMiddleware, max_bytes=settings.max_request_bytes)
app.add_middleware(StructuredJsonLoggingMiddleware, app_env=str(getattr(settings, "app_env", "unknown")))
app.add_middleware(TenantMiddleware)  # outermost — sets ContextVar before all inner middleware

app.include_router(ops_router, prefix="/ops")
app.include_router(api_router)


@app.get("/health", tags=["ops"])
def health():
    logger.info("health check")
    return {"app_env": APP_ENV}
