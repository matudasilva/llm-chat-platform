"""ORQ-37 H11b — the split grants on `rag_request_metrics` (AC34, B2 half).

The companion to `test_ops_role_grants_postgres.py`, which covers Gate B1 and
says in its own header that the `rag_request_metrics` grants and the separate
retention credential are asserted at B2, alongside the table T14 creates. The
table has existed since T14; this is that file.

`@pytest.mark.postgres`: skipped unless `RAG_TEST_DATABASE_URL` is set. A skip
is reported as a skip and never counted as a pass (AC10). SQLite has neither
roles nor grants, so none of this is expressible there.

**Asserted by CONNECTING AS each role, never from `information_schema`.** A
catalog row says a grant was written; a denied `DELETE` says the boundary
holds. `e4b7f21c9a06` already writes the grants and
`test_rag_request_metrics_migration.py` already parses that source -- what is
missing, and what this file supplies, is evidence that they are in effect.

Three DSNs, two of which the B1 file already uses:

  * `RAG_TEST_DATABASE_URL` -- privileged, to seed and to clean up.
  * `CHAT_OPS_TEST_DATABASE_URL` -- the runtime role, `chat_ops`.
  * `CHAT_OPS_RETENTION_TEST_DATABASE_URL` -- the retention credential,
    `chat_ops_retention`. New with this file; provisioned by
    `scripts/postgres-init/40-chat-ops-retention-role.sh`, which skips itself
    unless `POSTGRES_OPS_RETENTION_PASSWORD` is set in the environment.

Each role's block skips individually, with its own message, when its DSN is
absent -- rather than degrading into catalog reads that would pass while the
boundary was open.

**Scope.** AC34 reads "the separate retention credential can `SELECT`/`DELETE`
that table and nothing else". Read literally, "that table and nothing else"
bounds the OBJECTS, which is what `test_the_retention_role_cannot_read_*`
asserts. It is not read here as bounding the privilege SET: no
`INSERT`-denied case is claimed as AC34 evidence. Pinning one ungranted
privilege and not `UPDATE` or `TRUNCATE` would suggest the set is bounded when
it is not -- the false confidence of H6's structural test. Either the whole
privilege set is asserted or none of it is, and AC34 does not ask for it.
"""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]

TENANT = "orq37-grants"
RUNTIME_ROLE = "chat_ops"
RETENTION_ROLE = "chat_ops_retention"


def _admin_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL")
    assert url, "RAG_TEST_DATABASE_URL must be set"
    return url


def _runtime_url() -> str:
    url = os.environ.get("CHAT_OPS_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "CHAT_OPS_TEST_DATABASE_URL is not set; the grant boundary can only be "
            f"asserted by connecting AS {RUNTIME_ROLE}, never from the catalog alone"
        )
    return url


def _retention_url() -> str:
    url = os.environ.get("CHAT_OPS_RETENTION_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "CHAT_OPS_RETENTION_TEST_DATABASE_URL is not set; the retention "
            f"credential's boundary can only be asserted by connecting AS "
            f"{RETENTION_ROLE}, never from the catalog alone"
        )
    return url


@pytest.fixture
async def admin_engine():
    engine = create_async_engine(_admin_url())
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def runtime_engine():
    engine = create_async_engine(_runtime_url())
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def retention_engine():
    engine = create_async_engine(_retention_url())
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def seeded_row(admin_engine):
    """One metrics row, inserted and removed with the privileged credential."""
    marker = uuid.uuid4()
    maker = async_sessionmaker(admin_engine, expire_on_commit=False)
    try:
        async with maker() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO rag_request_metrics "
                        "(id, request_instance_id, tenant_id) VALUES (:id, :rid, :tenant)"
                    ),
                    {"id": uuid.uuid4(), "rid": marker, "tenant": TENANT},
                )
        yield marker
    finally:
        async with maker() as session:
            async with session.begin():
                await session.execute(
                    text(
                        "DELETE FROM rag_request_metrics WHERE request_instance_id = :rid"
                    ),
                    {"rid": marker},
                )


async def _assert_denied(connection, statement: str, params: dict) -> None:
    with pytest.raises(ProgrammingError) as excinfo:
        await connection.execute(text(statement), params)
    assert "permission denied" in str(excinfo.value).lower()


# --- the guards that keep this whole file from passing vacuously ----------


async def test_the_runtime_dsn_is_actually_chat_ops(runtime_engine) -> None:
    # A DSN that is really the superuser would satisfy every positive case and
    # fail every denial for the wrong reason.
    async with runtime_engine.connect() as connection:
        assert (
            await connection.execute(text("SELECT current_user"))
        ).scalar_one() == RUNTIME_ROLE
        assert (
            await connection.execute(
                text("SELECT usesuper FROM pg_user WHERE usename = current_user")
            )
        ).scalar_one() is False


async def test_the_retention_dsn_is_actually_chat_ops_retention(
    retention_engine,
) -> None:
    async with retention_engine.connect() as connection:
        assert (
            await connection.execute(text("SELECT current_user"))
        ).scalar_one() == RETENTION_ROLE
        assert (
            await connection.execute(
                text("SELECT usesuper FROM pg_user WHERE usename = current_user")
            )
        ).scalar_one() is False


# --- AC34: the runtime role is INSERT-only on this table ------------------


async def test_the_runtime_role_can_insert_metrics(runtime_engine) -> None:
    marker = uuid.uuid4()
    async with runtime_engine.connect() as connection:
        await connection.execute(
            text(
                "INSERT INTO rag_request_metrics "
                "(id, request_instance_id, tenant_id) VALUES (:id, :rid, :tenant)"
            ),
            {"id": uuid.uuid4(), "rid": marker, "tenant": TENANT},
        )
        # Rolled back rather than committed: the role cannot SELECT the row
        # back to clean it up, and leaving it would need the privileged
        # credential to find it.
        await connection.rollback()


async def test_the_runtime_role_cannot_read_metrics_back(
    runtime_engine, seeded_row
) -> None:
    # Append-only from the application's side: audit integrity does not depend
    # on the request path being uncompromised (`e4b7f21c9a06`).
    async with runtime_engine.connect() as connection:
        await _assert_denied(
            connection,
            "SELECT count(*) FROM rag_request_metrics WHERE request_instance_id = :rid",
            {"rid": seeded_row},
        )


async def test_the_runtime_role_cannot_delete_metrics(
    runtime_engine, seeded_row
) -> None:
    async with runtime_engine.connect() as connection:
        await _assert_denied(
            connection,
            "DELETE FROM rag_request_metrics WHERE request_instance_id = :rid",
            {"rid": seeded_row},
        )


# --- AC34: the retention credential reaches this table and no other -------


async def test_the_retention_role_can_select_metrics(
    retention_engine, seeded_row
) -> None:
    async with retention_engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT count(*) FROM rag_request_metrics "
                "WHERE request_instance_id = :rid"
            ),
            {"rid": seeded_row},
        )
        assert result.scalar_one() == 1


async def test_the_retention_role_can_delete_metrics(
    retention_engine, seeded_row
) -> None:
    async with retention_engine.connect() as connection:
        result = await connection.execute(
            text("DELETE FROM rag_request_metrics WHERE request_instance_id = :rid"),
            {"rid": seeded_row},
        )
        assert result.rowcount == 1
        # Rolled back so the fixture's own cleanup stays the single owner of
        # this row's lifetime.
        await connection.rollback()


@pytest.mark.parametrize("table", ["conversations", "messages"], ids=["conv", "msg"])
async def test_the_retention_role_cannot_read_other_tables(
    retention_engine, table
) -> None:
    """"...that table and nothing else", read as bounding the objects."""
    async with retention_engine.connect() as connection:
        await _assert_denied(connection, f"SELECT count(*) FROM {table}", {})


# --- the application's OWN write path, as the runtime role -----------------


async def test_the_shipped_writer_can_insert_as_the_runtime_role(
    admin_engine, runtime_engine, monkeypatch
) -> None:
    """`_write_rag_request_metrics` itself, connecting AS `chat_ops`.

    The tests above prove the GRANT: `chat_ops` may INSERT. They prove it with
    raw `text("INSERT INTO ...")`, which carries no `RETURNING`. The shipped
    writer used the ORM, whose `INSERT ... RETURNING created_at` needs SELECT --
    a privilege this role deliberately lacks -- so every real write raised
    `InsufficientPrivilegeError` and was swallowed by the best-effort boundary.
    Zero rows, silently, for as long as the flag was on.

    The grant was never wrong. The application's path was incompatible with it,
    and only a test that drives that path can tell the two apart.

    The assertion reads the row back with the PRIVILEGED credential on purpose:
    `chat_ops` cannot SELECT, and that is the property, not an obstacle.
    """
    import uuid as _uuid
    from types import SimpleNamespace

    import app.api.routes.chat as chat_routes
    from app.core.domain.chat_memory import ChatMemoryContext
    from app.core.domain.provider import ProviderResult
    from app.http import pipeline_metrics
    from sqlalchemy import text as _text
    from sqlalchemy.ext.asyncio import async_sessionmaker as _maker

    # `tests/conftest.py` pins a hermetic environment in which the metrics flag
    # is off, so without this the writer returns at its first guard and the
    # assertion below would fail for a reason that has nothing to do with
    # grants. Same switch the SQLite write-site tests use.
    monkeypatch.setattr(chat_routes.settings, "rag_request_metrics_enabled", True)

    instance_id = _uuid.uuid4()
    ops_sessionmaker = _maker(runtime_engine, expire_on_commit=False)
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(ops_db_sessionmaker=ops_sessionmaker))
    )

    instance, token = pipeline_metrics.init_collector(
        request_instance_id=str(instance_id), correlation_id=None
    )
    try:
        pipeline_metrics.record(memory_outcome="ok", ebm25_selected_count=2)
        await chat_routes._write_rag_request_metrics(
            request,
            tenant_id=TENANT,
            generation_outcome="ok",
            provider_result=ProviderResult(
                content="x",
                provider="bedrock",
                model_version="nvidia.nemotron-nano-12b-v2",
                prompt_version="v1",
                input_tokens=1000,
                output_tokens=500,
            ),
            memory_context=ChatMemoryContext(),
            total_latency_ms=42,
        )
    finally:
        pipeline_metrics.reset_collector(token)

    maker = _maker(admin_engine, expire_on_commit=False)
    try:
        async with maker() as session:
            row = (
                await session.execute(
                    _text(
                        "SELECT tenant_id, mode, memory_outcome, ebm25_selected_count, "
                        "estimated_cost_usd, total_latency_ms, created_at "
                        "FROM rag_request_metrics WHERE request_instance_id = :rid"
                    ),
                    {"rid": instance_id},
                )
            ).mappings().one_or_none()

        assert row is not None, (
            "the shipped writer persisted nothing as chat_ops -- the ORM's "
            "INSERT ... RETURNING needs a SELECT privilege this role lacks"
        )
        assert row["tenant_id"] == TENANT
        assert row["memory_outcome"] == "ok"
        assert row["ebm25_selected_count"] == 2
        assert row["total_latency_ms"] == 42
        # Priced from the frozen snapshot: 1000 in + 500 out on nemotron.
        assert float(row["estimated_cost_usd"]) == pytest.approx(0.000175)
        # Still generated by PostgreSQL; the writer just stops reading it back.
        assert row["created_at"] is not None
    finally:
        async with maker() as session:
            async with session.begin():
                await session.execute(
                    _text(
                        "DELETE FROM rag_request_metrics WHERE request_instance_id = :rid"
                    ),
                    {"rid": instance_id},
                )
