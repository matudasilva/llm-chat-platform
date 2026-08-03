from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.settings import settings


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

        if settings.rag_enabled:
            try:
                await asyncio.wait_for(_check_rag_role(self.app), timeout=self.db_timeout_s)
                checks["rag_db_role"] = "ok"
            except Exception:
                checks["rag_db_role"] = "error"
                return {
                    "status": "error",
                    "checks": checks,
                    "detail": "rag app role is superuser or bypasses RLS",
                }

        checks["redis"] = "skipped"
        return {"status": "ok", "checks": checks}


async def _check_db(app: object) -> None:
    engine = getattr(app.state, "db_engine", None)
    if engine is None or not isinstance(engine, AsyncEngine):
        raise RuntimeError("DB engine not initialized")
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_rag_role(app: object) -> None:
    """
    Turns "RLS is enforced" from a documentation claim into a runtime
    invariant (spec.md §Design decisions 4, ADR-006 §2): the RAG connection
    must hold neither rolsuper nor rolbypassrls, or every policy on
    documents/chunks is silently inert.
    """
    engine = getattr(app.state, "rag_db_engine", None)
    if engine is None or not isinstance(engine, AsyncEngine):
        raise RuntimeError("RAG DB engine not initialized")
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
        )
        row = result.one()
        if row.rolsuper or row.rolbypassrls:
            raise RuntimeError(
                "RAG app role must not hold SUPERUSER or BYPASSRLS: RLS would be inert"
            )


def get_readiness_checker(request: Request) -> ReadinessChecker:
    return DefaultReadinessChecker(app=request.app)
