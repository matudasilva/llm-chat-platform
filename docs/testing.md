# Test Environment Contract

The pytest suite is hermetic and must not depend on a developer's `.env`.

`tests/conftest.py` establishes test configuration before importing the
application:

- `.env` loading is disabled with `APP_SETTINGS_ENV_FILE=""`;
- the provider is the deterministic Stub provider;
- database access is replaced by an in-memory fake session;
- Redis access is replaced by an in-memory no-op fake;
- Notion MCP, Notion read/write, and controlled web read are disabled;
- uvloop is used consistently with the production Uvicorn installation.

Production behavior is unchanged. When `APP_SETTINGS_ENV_FILE` is not set, the
application continues to load `.env`. A non-empty value may select another
settings file for composition-level use.

Pytest has a global 60-second timeout per test. A future deadlock therefore
fails with diagnostic output instead of blocking the suite indefinitely.

## Local and CI parity

Install both runtime and development dependencies, then run:

```bash
python -m pip install -r app/requirements.txt -r app/requirements-dev.txt
python -m pytest
```

The same command must pass with a real `.env` present in the repository root.
Tests must never contact Bedrock, OpenAI, Notion, Redis, or an external
PostgreSQL instance unless a dedicated integration test explicitly opts in.

## Migration path note

The application image stores Alembic configuration at `app/alembic.ini`.
Deployment work in ORQ-20 must define the migration command explicitly, for
example `alembic -c app/alembic.ini upgrade head`, instead of assuming an
`alembic.ini` file at the image working-directory root.
