from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class ReadinessChecker(Protocol):
    async def check(self) -> dict: ...


@dataclass(frozen=True)
class DefaultReadinessChecker:
    app: object
    db_timeout_s: float = 5.0

    async def check(self) -> dict:
        checks: dict[str, str] = {}

        try:
            await asyncio.wait_for(_check_db(self.app), timeout=self.db_timeout_s)
            checks["db"] = "ok"
        except Exception:
            checks["db"] = "error"
            return {"status": "error", "checks": checks, "detail": "db unavailable"}

        checks["redis"] = "skipped"
        return {"status": "ok", "checks": checks}


async def _check_db(app: object) -> None:
    engine = getattr(app.state, "db_engine", None)
    if engine is None or not isinstance(engine, AsyncEngine):
        raise RuntimeError("DB engine not initialized")
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


def get_readiness_checker(request: Request) -> ReadinessChecker:
    return DefaultReadinessChecker(app=request.app)
