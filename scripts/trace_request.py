# scripts/trace_request.py
from __future__ import annotations

import asyncio
import json
import sys
from uuid import UUID

from app.infra.db.session import SessionLocal
from app.services.trace import TraceService


async def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/trace_request.py <request_id>", file=sys.stderr)
        return 2

    try:
        request_id = UUID(sys.argv[1])
    except Exception:
        print("Invalid UUID for request_id", file=sys.stderr)
        return 2

    async with SessionLocal() as db:
        try:
            report = await TraceService.reconstruct_by_request_id(db, request_id=request_id)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

    # Pretty print JSON
    payload = report.model_dump(mode="json")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    # Exit code por coherencia
    if report.coherence.errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
