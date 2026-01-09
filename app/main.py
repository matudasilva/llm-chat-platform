import logging
import os
import sys

from fastapi import FastAPI
from app.api.ops import router as ops_router



def _get_env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _configure_logging(app_env: str, log_level: str) -> None:
    # Logging to stdout for container/platform friendliness (even though we're not using Docker yet)
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

app = FastAPI(
    title="LLM Chat Platform API",
    version="0.1.0",
)
app.include_router(ops_router)

@app.on_event("startup")
async def startup() -> None:
    logger.info("starting application")
    # Dependency checks are intentionally deferred (LLD Day 4); /health is process-level only.


@app.get("/health", tags=["ops"])
def health():
    logger.info("health check")
    return {
        "status": "ok",
        "app_env": APP_ENV,
    }
    

