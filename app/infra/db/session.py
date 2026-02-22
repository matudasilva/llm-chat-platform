# app/infra/db/session.py
from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.settings import settings

logger = logging.getLogger(__name__)

_ENGINE_KEY = "db_engine"
_SESSIONMAKER_KEY = "db_sessionmaker"


def init_db(app) -> None:
    """
    Create engine + sessionmaker and store them on app.state.
    This MUST be called in FastAPI lifespan startup.
    """
    engine: AsyncEngine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
    )
    sessionmaker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    setattr(app.state, _ENGINE_KEY, engine)
    setattr(app.state, _SESSIONMAKER_KEY, sessionmaker)


async def close_db(app) -> None:
    """
    Dispose engine on shutdown to avoid event-loop / connection leaks in tests.
    """
    engine: AsyncEngine | None = getattr(app.state, _ENGINE_KEY, None)
    if engine is not None:
        await engine.dispose()


def _get_sessionmaker_from_app(app) -> async_sessionmaker[AsyncSession]:
    sm = getattr(app.state, _SESSIONMAKER_KEY, None)
    if sm is None:
        raise RuntimeError("DB is not initialized. Did you forget to call init_db(app) in lifespan?")
    return sm


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    SessionLocal = _get_sessionmaker_from_app(request.app)
    async with SessionLocal() as session:
        yield session


async def test_db_connection(app, retries: int = 10, delay: float = 2.0) -> None:
    """
    Optional: use the app-bound engine (not a module-global engine).
    """
    engine: AsyncEngine | None = getattr(app.state, _ENGINE_KEY, None)
    if engine is None:
        raise RuntimeError("DB engine not initialized")

    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database connection successful")
            return
        except OperationalError:
            logger.warning(
                "Database not ready (attempt %s/%s). Retrying in %.1fs...",
                attempt,
                retries,
                delay,
            )
            if attempt == retries:
                logger.error("Database connection failed after retries")
                raise
            await asyncio.sleep(delay)