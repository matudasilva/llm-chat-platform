"""ORQ-26 AC6: the metric store is isolated by schema, role, and migration chain.

Runs against a throwaway schema, never `evaluation` itself, so a teardown here
can never drop a real store.

The store fixture connects as the **evaluation role**, not the superuser.
Review round 1 found that using the privileged DSN made AC6 self-defeating: it
would have proved the DDL runs, under exactly the privilege level the ADR
forbids. `ensure_schema` now refuses a superuser outright, so the earlier
fixture could not work anyway.

Skipped unless RAG_TEST_DATABASE_URL (privileged, for inspection and teardown)
and EVALUATION_TEST_DATABASE_URL (the store role) are both set. The rag_app
isolation assertion additionally needs RAG_TEST_DATABASE_URL_APP.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from experiments.evaluation.store import (
    SCHEMA,
    EvaluationStore,
    RunProvenance,
    SuperuserStoreError,
    build_ddl,
)

pytestmark = pytest.mark.postgres

_TEST_SCHEMA = "evaluation_test"


def _privileged_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL")
    assert url, "RAG_TEST_DATABASE_URL must be set"
    return url


def _store_url() -> str:
    url = os.environ.get("EVALUATION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("EVALUATION_TEST_DATABASE_URL not set")
    return url


def _provenance(**overrides: str) -> RunProvenance:
    base = {
        "registration_sha256": "a" * 64,
        "registration_commit": "b" * 40,
        "golden_set_sha256": "c" * 64,
        "ingestion_commit": "d" * 40,
        "code_commit": "e" * 40,
        "runner_commit": "f" * 40,
    }
    return RunProvenance(**{**base, **overrides})


@pytest.fixture
async def store():
    store = EvaluationStore._for_test(_store_url(), _TEST_SCHEMA)
    try:
        await store.ensure_schema()
        yield store
    finally:
        engine = create_async_engine(_privileged_url())
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {_TEST_SCHEMA} CASCADE"))
        await engine.dispose()
        await store.dispose()


async def test_ensure_schema_is_idempotent(store) -> None:
    # The harness runs it on every invocation; a second call must not fail.
    await store.ensure_schema()
    await store.ensure_schema()


async def test_tables_carry_mlflow_compatible_columns(store) -> None:
    engine = create_async_engine(_privileged_url())
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema"
                ),
                {"schema": _TEST_SCHEMA},
            )
            columns: dict[str, set[str]] = {}
            for row in result:
                columns.setdefault(row.table_name, set()).add(row.column_name)
    finally:
        await engine.dispose()

    assert set(columns) == {"runs", "metrics", "params", "tags"}
    assert {"run_id", "key", "value", "step", "timestamp"} <= columns["metrics"]
    assert {"run_id", "key", "value"} <= columns["params"]
    assert {"run_id", "key", "value"} <= columns["tags"]
    assert {"run_id", "experiment_name", "status", "start_time", "end_time"} <= columns["runs"]


async def test_run_provenance_columns_are_not_nullable(store) -> None:
    # The point of putting provenance in columns rather than tags is that the
    # database, not a convention, refuses a run that cannot say where it came
    # from.
    engine = create_async_engine(_privileged_url())
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'runs' "
                    "AND is_nullable = 'NO'"
                ),
                {"schema": _TEST_SCHEMA},
            )
            not_null = {row.column_name for row in result}
    finally:
        await engine.dispose()

    assert {
        "registration_sha256",
        "registration_commit",
        "golden_set_sha256",
        "ingestion_commit",
        "code_commit",
        "runner_commit",
    } <= not_null


@pytest.mark.parametrize(
    "missing",
    [
        "registration_sha256",
        "registration_commit",
        "golden_set_sha256",
        "ingestion_commit",
        "code_commit",
        "runner_commit",
    ],
)
def test_provenance_refuses_a_missing_field(missing: str) -> None:
    with pytest.raises(ValueError, match=missing):
        _provenance(**{missing: ""})


async def test_run_and_metrics_round_trip(store) -> None:
    run_id = await store.create_run(
        experiment_name="orq-26",
        provenance=_provenance(),
        params={"k_values": "10,20,30"},
        tags={"tenant_id": "acme"},
    )
    await store.log_metrics(run_id, {"recall@10": 0.75, "MRR@10": 0.5})
    await store.finish_run(run_id, status="FINISHED")

    engine = create_async_engine(_privileged_url())
    try:
        async with engine.connect() as conn:
            metrics = dict(
                (row.key, row.value)
                for row in await conn.execute(
                    text(f"SELECT key, value FROM {_TEST_SCHEMA}.metrics WHERE run_id = :id"),
                    {"id": run_id},
                )
            )
            run = (
                await conn.execute(
                    text(
                        f"SELECT status, end_time, registration_sha256 "
                        f"FROM {_TEST_SCHEMA}.runs WHERE run_id = :id"
                    ),
                    {"id": run_id},
                )
            ).one()
            params = dict(
                (row.key, row.value)
                for row in await conn.execute(
                    text(f"SELECT key, value FROM {_TEST_SCHEMA}.params WHERE run_id = :id"),
                    {"id": run_id},
                )
            )
    finally:
        await engine.dispose()

    assert metrics == {"recall@10": 0.75, "MRR@10": 0.5}
    assert run.status == "FINISHED"
    assert run.end_time is not None
    assert run.registration_sha256 == "a" * 64
    assert params == {"k_values": "10,20,30"}


async def test_a_second_registration_adds_a_run_rather_than_replacing_one(store) -> None:
    # ADR-009 decision 3: runs under every registration hash are reported, never
    # only the last. Nothing in the schema may collapse them.
    first = await store.create_run(
        experiment_name="orq-26", provenance=_provenance(registration_sha256="a" * 64)
    )
    second = await store.create_run(
        experiment_name="orq-26", provenance=_provenance(registration_sha256="f" * 64)
    )
    assert first != second

    engine = create_async_engine(_privileged_url())
    try:
        async with engine.connect() as conn:
            count = (
                await conn.execute(text(f"SELECT count(*) FROM {_TEST_SCHEMA}.runs"))
            ).scalar_one()
    finally:
        await engine.dispose()
    assert count == 2


async def test_metrics_cascade_with_their_run(store) -> None:
    run_id = await store.create_run(experiment_name="orq-26", provenance=_provenance())
    await store.log_metrics(run_id, {"recall@10": 1.0})

    engine = create_async_engine(_privileged_url())
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(f"DELETE FROM {_TEST_SCHEMA}.runs WHERE run_id = :id"), {"id": run_id}
            )
        async with engine.connect() as conn:
            orphans = (
                await conn.execute(
                    text(f"SELECT count(*) FROM {_TEST_SCHEMA}.metrics WHERE run_id = :id"),
                    {"id": run_id},
                )
            ).scalar_one()
    finally:
        await engine.dispose()
    assert orphans == 0


async def test_a_metric_cannot_reference_a_missing_run(store) -> None:
    engine = create_async_engine(_privileged_url())
    try:
        with pytest.raises(DBAPIError):
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        f"INSERT INTO {_TEST_SCHEMA}.metrics (run_id, key, value, timestamp) "
                        "VALUES (:id, 'recall@10', 1.0, now())"
                    ),
                    {"id": uuid.uuid4()},
                )
    finally:
        await engine.dispose()


async def test_rag_app_cannot_reach_the_store(store) -> None:
    app_url = os.environ.get("RAG_TEST_DATABASE_URL_APP")
    if not app_url:
        pytest.skip("RAG_TEST_DATABASE_URL_APP not set")
    engine = create_async_engine(app_url)
    try:
        async with engine.connect() as conn:
            with pytest.raises((ProgrammingError, DBAPIError)):
                await conn.execute(text(f"SELECT count(*) FROM {_TEST_SCHEMA}.runs"))
    finally:
        await engine.dispose()


async def test_the_store_role_is_not_a_superuser() -> None:
    store = EvaluationStore(_store_url())
    try:
        assert await store.is_superuser() is False
    finally:
        await store.dispose()


async def test_superuser_cannot_write_to_an_existing_schema(store) -> None:
    # Review round 2 found the real hole: guarding only ensure_schema leaves a
    # superuser free to write to a schema someone else legitimately created, by
    # simply never calling it. The `store` fixture has already created the
    # schema, so this is exactly that path.
    intruder = EvaluationStore._for_test(_privileged_url(), _TEST_SCHEMA)
    try:
        with pytest.raises(SuperuserStoreError):
            await intruder.create_run(experiment_name="orq-26", provenance=_provenance())
        with pytest.raises(SuperuserStoreError):
            await intruder.log_metrics(uuid.uuid4(), {"recall@10": 1.0})
        with pytest.raises(SuperuserStoreError):
            await intruder.finish_run(uuid.uuid4(), status="FINISHED")
    finally:
        await intruder.dispose()


async def test_ensure_schema_refuses_a_superuser_connection() -> None:
    # The settings-time string check is ergonomic only: an equivalent DSN
    # differing in a query parameter, host alias or password encoding passes it.
    # This is the control that cannot be talked around, because it asks the
    # server who it is actually connected as.
    store = EvaluationStore._for_test(_privileged_url(), _TEST_SCHEMA)
    try:
        with pytest.raises(SuperuserStoreError, match="must not connect as a superuser"):
            await store.ensure_schema()
    finally:
        await store.dispose()


async def test_the_public_store_is_fixed_to_the_evaluation_schema() -> None:
    # The schema the harness owns is declared in ADR-009 decision 5. Letting a
    # caller redirect DDL and writes elsewhere would widen that boundary
    # silently, so configurability lives only in the test seam.
    store = EvaluationStore(_store_url())
    try:
        assert store._schema == SCHEMA
    finally:
        await store.dispose()


def test_ddl_rejects_an_unsafe_schema_identifier() -> None:
    with pytest.raises(ValueError, match="invalid schema identifier"):
        build_ddl("evaluation; DROP SCHEMA public CASCADE")
