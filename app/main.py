import logging
import os
import sys

from fastapi import FastAPI

from app.api.ops import router as ops_router
from app.infra.db.session import test_db_connection
from app.api.router import api_router
from app.core.settings import settings
from app.http.middleware.request_size_limit import RequestSizeLimitMiddleware
from app.http.middleware.structured_logging import StructuredJsonLoggingMiddleware




def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _configure_logging(app_env: str, log_level: str) -> None:
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = []  # avoid duplicate handlers on reload
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

logging.basicConfig(
    level=getattr(logging, str(getattr(settings, "log_level", "INFO")).upper(), logging.INFO),
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


app = FastAPI(
    title="LLM Chat Platform API",
    version="0.1.0",


)

app.add_middleware(
    StructuredJsonLoggingMiddleware,
    app_env=str(getattr(settings, "app_env", "unknown")),
)

app.add_middleware(
    RequestSizeLimitMiddleware,
    max_bytes=settings.MAX_REQUEST_BYTES,
)

# Routers (definí prefijos acá, no adentro del router)
app.include_router(ops_router, prefix="/ops")
app.include_router(api_router)


@app.on_event("startup")
async def startup() -> None:
    logger.info("starting application")
    # Ya que tu DB y alembic están andando, esto te ahorra sorpresas:
    await test_db_connection()


@app.get("/health", tags=["ops"])
def health():
    logger.info("health check")
    return {
        "app_env": APP_ENV,
    }
