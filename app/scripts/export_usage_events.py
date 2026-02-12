import argparse
import asyncio
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# NOTE: adjust these imports only if your paths differ
from core.settings import settings


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    # Accept ISO8601 like: 2026-02-12 or 2026-02-12T00:00:00
    try:
        return datetime.fromisoformat(value)
    except ValueError as e:
        raise SystemExit(f"Invalid datetime format: {value}. Use ISO8601.") from e


def _ensure_parent_dir(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


async def export_usage_events(
    out_path: str,
    since: Optional[datetime],
    until: Optional[datetime],
    provider: Optional[str],
    status: Optional[str],
    limit: int,
) -> int:
    # NOTE: adjust to your actual DB url attribute name if needed
    db_url = getattr(settings, "database_url_override", None)
    if not db_url:
        raise SystemExit("DATABASE_URL is not set (settings.database_url_override is empty).")

    engine = create_async_engine(db_url, pool_pre_ping=True)

    where_clauses = []
    params: Dict[str, Any] = {"limit": limit}

    if since:
        where_clauses.append("timestamp >= :since")
        params["since"] = since
    if until:
        where_clauses.append("timestamp < :until")
        params["until"] = until
    if provider:
        where_clauses.append("provider = :provider")
        params["provider"] = provider
    if status:
        where_clauses.append("status = :status")
        params["status"] = status

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    # Columns based on your Appendix A schema for usage_events
    sql = text(f"""
        SELECT
          id,
          provider,
          model_version,
          prompt_version,
          request_id,
          conversation_id,
          message_id,
          input_tokens,
          output_tokens,
          total_tokens,
          latency_ms,
          status,
          error_message,
          timestamp
        FROM usage_events
        {where_sql}
        ORDER BY timestamp ASC
        LIMIT :limit
    """)

    count = 0
    _ensure_parent_dir(out_path)

    async with engine.connect() as conn:
        result = await conn.execute(sql, params)

        with open(out_path, "w", encoding="utf-8") as f:
            for row in result.mappings():
                obj = dict(row)

                # Normalize datetimes/UUIDs to JSON-safe strings
                if obj.get("timestamp") is not None:
                    obj["timestamp"] = obj["timestamp"].isoformat()

                for k in ["id", "request_id", "conversation_id", "message_id"]:
                    if obj.get(k) is not None:
                        obj[k] = str(obj[k])

                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
                count += 1

    await engine.dispose()
    return count


def main() -> None:
    p = argparse.ArgumentParser(description="Export usage_events to JSONL (read-only).")
    p.add_argument("--out", default="reports/usage_events.jsonl", help="Output path (JSONL).")
    p.add_argument("--since", default=None, help="ISO datetime (inclusive).")
    p.add_argument("--until", default=None, help="ISO datetime (exclusive).")
    p.add_argument("--provider", default=None, help="Filter provider.")
    p.add_argument("--status", default=None, help="Filter status (success/error).")
    p.add_argument("--limit", type=int, default=5000, help="Max rows to export.")
    args = p.parse_args()

    since = _parse_dt(args.since)
    until = _parse_dt(args.until)

    n = asyncio.run(
        export_usage_events(
            out_path=args.out,
            since=since,
            until=until,
            provider=args.provider,
            status=args.status,
            limit=args.limit,
        )
    )
    print(f"[OK] exported {n} usage_events -> {args.out}")


if __name__ == "__main__":
    main()
