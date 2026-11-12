"""Bounded local discovery of a genuine text-search computational error."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app/tests/core")
from test_pgvector_query_equivalence import _session, _url
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


async def main():
    results = []
    for size in (16384, 32768, 65536, 131072):
        query = " ".join("lexeme" + str(i) for i in range(size))
        try:
            async with _session(_url("RAG_TEST_DATABASE_URL_APP"), "orq37-t23", "force_generic_plan") as session:
                count = await session.scalar(text("SELECT numnode(plainto_tsquery('english', :query))"), {"query": query})
                results.append({"lexemes": size, "nodes": count, "result": "ok"})
        except DBAPIError as exc:
            results.append({"lexemes": size, "result": "error", "sqlstate": getattr(exc.orig, "sqlstate", None),
                            "message": str(exc.orig.__cause__)[:250]})
            break
    Path("/validation/error-fixture-probe.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results))


asyncio.run(main())
