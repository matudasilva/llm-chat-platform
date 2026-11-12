"""Local image/source inventory; never starts the API or opens a connection."""
import asyncio
import hashlib
from importlib.metadata import distributions
import json
import os
from pathlib import Path
import sys

from sqlalchemy.dialects.postgresql.asyncpg import dialect
from app.core.providers.pgvector_store import PgVectorStore
from experiments.production_graduation.gate_validation.validate_g123 import check_p2


class Capture:
    calls = 0

    async def execute(self, statement, parameters):
        self.calls += 1
        self.statement, self.parameters = statement, parameters
        return []


async def main():
    check_p2()
    root = Path('/app/app')
    sources = {}
    for path in sorted(root.rglob('*')):
        assert not path.is_symlink(), 'Unexpected application symlink'
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            sources[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    source = root/'core/providers/pgvector_store.py'
    compile(source.read_text(), str(source), 'exec')
    capture = Capture()
    result = await PgVectorStore(capture).hybrid_search('alpha', [1.0]+[0.0]*1535)
    assert result == [] and capture.calls == 1
    compiled = capture.statement.compile(dialect=dialect())
    assert list(compiled.positiontup) == ['query_embedding', 'top_k', 'query_text', 'rrf_k']
    installed = sorted((dist.metadata['Name'], dist.version) for dist in distributions())
    print(json.dumps(dict(status='IMAGE_INVENTORY_AND_ADAPTER_IMPORT_PASS',
        app_files=sources, installed_distributions=installed, python=sys.version,
        provider_sha256=sources['core/providers/pgvector_store.py'],
        compiled_sql_sha256=hashlib.sha256(str(compiled).encode()).hexdigest(),
        adapter_capture_calls=1, database_connections=0, api_requests=0,
        provider_calls=0, interfaces=sorted(line.split(':',1)[0].strip()
            for line in Path('/proc/self/net/dev').read_text().splitlines()[2:]),
        dotenv_disabled=os.environ.get('APP_SETTINGS_ENV_FILE')=='',
        metadata_discovery_disabled=os.environ.get('AWS_EC2_METADATA_DISABLED')=='true'), sort_keys=True))


asyncio.run(main())
