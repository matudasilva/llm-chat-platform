import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.settings import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)

async def test_db_connection(
    retries: int = 10,
    delay: float = 2.0,
) -> None:
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
