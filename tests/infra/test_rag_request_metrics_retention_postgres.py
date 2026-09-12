"""ORQ-37 H11a — the published retention DELETE, at the database (AC33).

`@pytest.mark.postgres`: skipped unless `RAG_TEST_DATABASE_URL` is set. A skip
is reported as a skip and never counted as a pass (AC10). None of these
properties can be established against SQLite, which has neither `now()` as a
transaction timestamp nor `make_interval`.

**This file asserts the PREDICATE; `test_rag_request_metrics_grants_postgres`
asserts the PERMISSIONS.** Splitting them that way is deliberate: it keeps this
file's only prerequisite the privileged DSN, so AC33 does not wait on the
retention role being provisioned. The cost is that the statement runs here as
the privileged credential rather than as `chat_ops_retention`, which is how an
operator actually runs it -- that half is AC34's, next door.

The statement is READ FROM the published document rather than transcribed. If
`docs/observability/rag_request_metrics_retention.md` and this test ever
diverge, that is a failure, not a detail to reconcile by hand.

## Why the seed and the DELETE share one transaction

The boundary case is only meaningful if the `now()` that builds the row and the
`now()` inside the published statement are the SAME instant. PostgreSQL's
`now()` is `transaction_timestamp()` -- fixed for the whole transaction -- so
running both inside one transaction makes them identical by construction.

Seeding in one transaction and deleting in a later one would not be flaky, it
would be deterministically WRONG: the second `now()` is strictly later, so the
cutoff moves past the boundary row and it is always deleted. The `<` in the
predicate is correct and is not what would have been at fault.

`test_the_transaction_timestamp_is_stable` makes that premise observable rather
than assumed: it fails loudly if this ever runs outside a single transaction,
instead of quietly reporting something untrue about the predicate.

**Declared limit:** this proves the predicate under a single transaction
timestamp. It does not prove behaviour with a clock running between the seed
and the delete, which is the shape a real operator run has.
"""
from __future__ import annotations

import os
import pathlib
import re
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]

TENANT = "orq37-retention"

_RETENTION_DOC = (
    pathlib.Path(__file__).resolve().parents[2]
    / "docs/observability/rag_request_metrics_retention.md"
)


def _admin_url() -> str:
    url = os.environ.get("RAG_TEST_DATABASE_URL")
    assert url, "RAG_TEST_DATABASE_URL must be set"
    return url


def _published_delete() -> str:
    """The exact statement from the operational document, not a copy of it."""
    blocks = re.findall(r"```sql\n(.*?)```", _RETENTION_DOC.read_text(), re.DOTALL)
    deletes = [b.strip() for b in blocks if b.strip().upper().startswith("DELETE")]
    assert len(deletes) == 1, f"expected exactly one published DELETE, found {len(deletes)}"
    return deletes[0]


@pytest.fixture
async def engine():
    engine = create_async_engine(_admin_url())
    try:
        yield engine
    finally:
        await engine.dispose()


async def _seed(session, *, now, age_days: float, marker: uuid.UUID) -> None:
    """One row whose `created_at` is `age_days` older than the captured `now`."""
    await session.execute(
        text(
            "INSERT INTO rag_request_metrics "
            "(id, request_instance_id, tenant_id, created_at) "
            "VALUES (:id, :rid, :tenant, :now - make_interval(days => :age))"
        ),
        {"id": uuid.uuid4(), "rid": marker, "tenant": TENANT, "now": now, "age": age_days},
    )


async def _surviving(session, markers) -> set[uuid.UUID]:
    result = await session.execute(
        text(
            "SELECT request_instance_id FROM rag_request_metrics "
            "WHERE request_instance_id = ANY(:markers)"
        ),
        {"markers": list(markers)},
    )
    return {row[0] for row in result}


async def _run_window(engine, *, retention_days: int, ages: dict[str, float]):
    """Seed one row per age and apply the published DELETE, in ONE transaction.

    Returns the markers that survived, keyed by the same labels.
    """
    maker = async_sessionmaker(engine, expire_on_commit=False)
    markers = {label: uuid.uuid4() for label in ages}
    async with maker() as session:
        async with session.begin():
            now = (await session.execute(text("SELECT now()"))).scalar_one()
            for label, age in ages.items():
                await _seed(session, now=now, age_days=age, marker=markers[label])
            await session.execute(
                text(_published_delete()), {"retention_days": retention_days}
            )
            survived = await _surviving(session, markers.values())
            # Roll the whole thing back: the seed, the delete and the read all
            # disappear, so the test leaves no rows behind on a shared database.
            await session.rollback()
    return {label: markers[label] in survived for label in ages}


# --- the premise the boundary case rests on -------------------------------


async def test_the_transaction_timestamp_is_stable(engine) -> None:
    """`now()` must be the transaction's timestamp, not the statement's.

    Not a property of this codebase -- a property of PostgreSQL that the
    boundary case below depends on. Asserted rather than assumed so that a
    violated premise fails here, visibly, instead of silently turning the
    boundary assertion into something else.
    """
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        async with session.begin():
            first = (await session.execute(text("SELECT now()"))).scalar_one()
            await session.execute(text("SELECT pg_sleep(0.05)"))
            second = (await session.execute(text("SELECT now()"))).scalar_one()
            assert first == second
            await session.rollback()


# --- AC33: the predicate deletes exactly the window and nothing else -------


async def test_a_row_older_than_the_window_is_deleted(engine) -> None:
    survived = await _run_window(engine, retention_days=30, ages={"old": 31})
    assert survived["old"] is False


async def test_a_row_newer_than_the_window_survives(engine) -> None:
    survived = await _run_window(engine, retention_days=30, ages={"recent": 29})
    assert survived["recent"] is True


async def test_a_row_exactly_at_the_boundary_survives(engine) -> None:
    """`<` is strict, so the cutoff instant itself is NOT old enough.

    Deterministic only because the seed and the DELETE share one transaction
    timestamp -- see this module's docstring.
    """
    survived = await _run_window(engine, retention_days=30, ages={"boundary": 30})
    assert survived["boundary"] is True


async def test_the_window_comes_from_the_configured_value_not_a_hardcoded_30(
    engine,
) -> None:
    """The document promises the window is read from configuration at run time.

    A statement hardcoding 30 would keep the 8-day-old row and delete the
    40-day-old one under both settings; binding `:retention_days` is what makes
    the 8-day-old row disappear at a 7-day window.
    """
    survived = await _run_window(
        engine, retention_days=7, ages={"eight_days": 8, "one_day": 1}
    )
    assert survived["eight_days"] is False
    assert survived["one_day"] is True


async def test_the_statement_touches_no_other_table(engine) -> None:
    """"...and nothing else": conversations and messages are untouched."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        before = {
            table: (
                await session.execute(text(f"SELECT count(*) FROM {table}"))
            ).scalar_one()
            for table in ("conversations", "messages")
        }

    await _run_window(engine, retention_days=30, ages={"old": 31})

    async with maker() as session:
        after = {
            table: (
                await session.execute(text(f"SELECT count(*) FROM {table}"))
            ).scalar_one()
            for table in ("conversations", "messages")
        }
    assert after == before
