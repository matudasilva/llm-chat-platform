"""Capture actual adapter SQL/parameter order without opening a connection."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from sqlalchemy.dialects.postgresql.asyncpg import dialect
from app.core.providers.pgvector_store import PgVectorStore

OUT = Path('/validation')
PRIOR = Path('/app/.framework/orqs/ORQ-41-production-retrieval-graduation/paid-execution/controlled-g6/261106225237/diagnosis/blocked-runs/261109162430/execution-review')
WORKER = PRIOR / 'driver-diagnostic/driver_worker.py'
spec = importlib.util.spec_from_file_location('unchanged_driver_probe', WORKER)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class Capture:
    calls = 0

    async def execute(self, statement, parameters):
        self.calls += 1
        self.statement, self.parameters = statement, parameters
        return []


async def main():
    label = sys.argv[1]
    assert label in ('original', 'candidate-2')
    capture = Capture()
    await PgVectorStore(capture).hybrid_search('alpha', [1.0] + [0.0] * 1535)
    assert capture.calls == 1
    compiled = capture.statement.compile(dialect=dialect())
    query = str(compiled)
    (OUT / (label + '-compiled-query.sql')).write_text(query)
    result = worker.probe()
    result.update(compiled_sql_sha256=hashlib.sha256(query.encode()).hexdigest(),
                  actual_bind_order=list(compiled.positiontup), retrieval_selects=1)
    (OUT / (label + '-source-probe.json')).write_text(json.dumps(result, indent=2) + '\n')
    print(label, 'SOURCE_SQL_CAPTURE_PASS')


asyncio.run(main())
