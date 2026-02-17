from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text

from app.infra.db import session as db_session


class ReadinessChecker(Protocol):
    async def check(self) -> dict: ...


@dataclass(frozen=True)
class DefaultReadinessChecker:
    db_timeout_s: float = 0.5

    async def check(self) -> dict:
        checks: dict[str, str] = {}

        try:
            await asyncio.wait_for(_check_db(), timeout=self.db_timeout_s)
            checks["db"] = "ok"
        except Exception:
            checks["db"] = "error"
            return {"status": "error", "checks": checks, "detail": "db unavailable"}

        checks["redis"] = "skipped"
        return {"status": "ok", "checks": checks}


async def _check_db() -> None:
    engine = db_session.engine
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


def get_readiness_checker() -> ReadinessChecker:
    return DefaultReadinessChecker()
