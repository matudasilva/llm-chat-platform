"""MLflow-compatible metric store for ORQ-26, outside the Alembic chain.

The schema is created by the idempotent DDL below and never by a migration
(ADR-009 decision 5): an experiment must not be able to introduce a revision
into the chain that serves the product, nor gain a write path into business
tables. `mission.md` §Excluded defers MLflow — this shape is MLflow-*compatible*
and adds no MLflow dependency.

Provenance lives in `runs` as NOT NULL columns rather than in `tags`, so the
database refuses a run that cannot say which registration and which corpus
produced it. In `tags` that would be a convention; here it is a constraint.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

SCHEMA = "evaluation"

_PROVENANCE_FIELDS = (
    "registration_sha256",
    "registration_commit",
    "golden_set_sha256",
    "ingestion_commit",
    "code_commit",
    "runner_commit",
)


def build_ddl(schema: str = SCHEMA) -> tuple[str, ...]:
    """Idempotent DDL for the metric store.

    A schema name is a Postgres identifier, not a value, so it cannot be a bound
    parameter. It is validated instead. The only caller that passes a
    non-default is the test suite, which needs its own schema so that a teardown
    can never drop a real store.
    """
    if not schema.isidentifier():
        raise ValueError(f"invalid schema identifier: {schema!r}")
    return (
        f"CREATE SCHEMA IF NOT EXISTS {schema}",
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.runs (
            run_id              uuid PRIMARY KEY,
            experiment_name     text        NOT NULL,
            status              text        NOT NULL,
            start_time          timestamptz NOT NULL,
            end_time            timestamptz,
            registration_sha256 text        NOT NULL,
            registration_commit text        NOT NULL,
            golden_set_sha256   text        NOT NULL,
            ingestion_commit    text        NOT NULL,
            code_commit         text        NOT NULL,
            runner_commit       text        NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.metrics (
            run_id    uuid             NOT NULL REFERENCES {schema}.runs (run_id) ON DELETE CASCADE,
            key       text             NOT NULL,
            value     double precision NOT NULL,
            step      bigint           NOT NULL DEFAULT 0,
            timestamp timestamptz      NOT NULL,
            PRIMARY KEY (run_id, key, step)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.params (
            run_id uuid NOT NULL REFERENCES {schema}.runs (run_id) ON DELETE CASCADE,
            key    text NOT NULL,
            value  text NOT NULL,
            PRIMARY KEY (run_id, key)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {schema}.tags (
            run_id uuid NOT NULL REFERENCES {schema}.runs (run_id) ON DELETE CASCADE,
            key    text NOT NULL,
            value  text NOT NULL,
            PRIMARY KEY (run_id, key)
        )
        """,
        # For a store created before runner_commit existed. Added nullable and
        # then backfilled, because a NOT NULL column cannot be added to a table
        # that already holds rows. The sentinel is deliberately not a plausible
        # commit: those rows were written by a runner that did not verify its own
        # source, and must not be readable as though they had.
        f"ALTER TABLE {schema}.runs ADD COLUMN IF NOT EXISTS runner_commit text",
        f"UPDATE {schema}.runs SET runner_commit = 'unverified-pre-guard' "
        f"WHERE runner_commit IS NULL",
        f"ALTER TABLE {schema}.runs ALTER COLUMN runner_commit SET NOT NULL",
        # Reporting every registration's runs, never only the last, is the point
        # of ADR-009 decision 3; this index keeps that query cheap enough to be
        # routine rather than something a reader skips.
        f"CREATE INDEX IF NOT EXISTS runs_registration_idx "
        f"ON {schema}.runs (registration_sha256, start_time)",
    )


@dataclass(frozen=True)
class RunProvenance:
    """What a run must be able to prove about itself before it may be written."""

    registration_sha256: str
    registration_commit: str
    golden_set_sha256: str
    ingestion_commit: str
    code_commit: str
    runner_commit: str

    def __post_init__(self) -> None:
        for field_name in _PROVENANCE_FIELDS:
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required to write a run")


class SuperuserStoreError(RuntimeError):
    """The store DSN resolves to a superuser role."""


class EvaluationStore:
    """Writes evaluation runs to the `evaluation` schema.

    The schema is fixed. `Settings.validate_evaluation_store_url` rejects a DSN
    string-equal to the application database, but that check is ergonomic only —
    an equivalent DSN differing in a query parameter, host alias or password
    encoding passes it. The authoritative control is `_assert_not_superuser`,
    which asks the server who it is actually connected as, and which gates every
    public method that touches the database — not only `ensure_schema`. Guarding
    the DDL alone would still let a superuser DSN write to an already-created
    schema (ADR-009 decision 5).
    """

    def __init__(self, dsn: str) -> None:
        self._schema = SCHEMA
        self._ddl = build_ddl(SCHEMA)
        self._engine: AsyncEngine = create_async_engine(dsn)
        # None until checked. Guarding only ensure_schema would leave the hole
        # review round 2 found: once a legitimate schema exists, a superuser DSN
        # could write to it by never calling ensure_schema at all.
        self._role_checked = False

    @classmethod
    def _for_test(cls, dsn: str, schema: str) -> "EvaluationStore":
        """Test-only seam: a throwaway schema so a teardown cannot drop a real store.

        Deliberately not part of the public surface. Production code has exactly
        one schema, which is what ADR-009 decision 5 declares the harness owns.
        """
        store = cls(dsn)
        store._schema = schema
        store._ddl = build_ddl(schema)
        return store

    async def dispose(self) -> None:
        await self._engine.dispose()

    async def _assert_not_superuser(self) -> None:
        """Gate on every public entry point that touches the database.

        Checked at connection time rather than at settings time because this is
        the first point at which the *actual* connected role is knowable. A DSN
        string can lie by being merely equivalent to the superuser's; `rolsuper`
        cannot. Cached after the first successful check — the role of an open
        engine's connections does not change underneath us, and re-querying on
        every metric write would be a round trip per row.
        """
        if self._role_checked:
            return
        if await self.is_superuser():
            raise SuperuserStoreError(
                "the evaluation store must not connect as a superuser; "
                "provision the rag_evaluation role (ADR-009 decision 5)"
            )
        self._role_checked = True

    async def ensure_schema(self) -> None:
        await self._assert_not_superuser()
        async with self._engine.begin() as conn:
            for statement in self._ddl:
                await conn.execute(text(statement))

    async def is_superuser(self) -> bool:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            )
            return bool(result.scalar_one())

    async def create_run(
        self,
        *,
        experiment_name: str,
        provenance: RunProvenance,
        params: dict[str, str] | None = None,
        tags: dict[str, str] | None = None,
    ) -> uuid.UUID:
        await self._assert_not_superuser()
        run_id = uuid.uuid4()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    f"INSERT INTO {self._schema}.runs "
                    "(run_id, experiment_name, status, start_time, registration_sha256, "
                    " registration_commit, golden_set_sha256, ingestion_commit, code_commit, runner_commit) "
                    "VALUES (:run_id, :experiment_name, 'RUNNING', :start_time, :registration_sha256, "
                    " :registration_commit, :golden_set_sha256, :ingestion_commit, :code_commit, :runner_commit)"
                ),
                {
                    "run_id": run_id,
                    "experiment_name": experiment_name,
                    "start_time": _now(),
                    **{field: getattr(provenance, field) for field in _PROVENANCE_FIELDS},
                },
            )
            await self._insert_kv(conn, "params", run_id, params or {})
            await self._insert_kv(conn, "tags", run_id, tags or {})
        return run_id

    async def log_metrics(
        self, run_id: uuid.UUID, metrics: dict[str, float], *, step: int = 0
    ) -> None:
        await self._assert_not_superuser()
        if not metrics:
            return
        timestamp = _now()
        async with self._engine.begin() as conn:
            for key, value in metrics.items():
                await conn.execute(
                    text(
                        f"INSERT INTO {self._schema}.metrics (run_id, key, value, step, timestamp) "
                        "VALUES (:run_id, :key, :value, :step, :timestamp)"
                    ),
                    {
                        "run_id": run_id,
                        "key": key,
                        "value": float(value),
                        "step": step,
                        "timestamp": timestamp,
                    },
                )

    async def finish_run(self, run_id: uuid.UUID, *, status: str) -> None:
        await self._assert_not_superuser()
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    f"UPDATE {self._schema}.runs SET status = :status, end_time = :end_time "
                    "WHERE run_id = :run_id"
                ),
                {"run_id": run_id, "status": status, "end_time": _now()},
            )

    async def _insert_kv(
        self, conn, table: str, run_id: uuid.UUID, values: dict[str, str]
    ) -> None:
        for key, value in values.items():
            await conn.execute(
                text(
                    f"INSERT INTO {self._schema}.{table} (run_id, key, value) "
                    "VALUES (:run_id, :key, :value)"
                ),
                {"run_id": run_id, "key": key, "value": str(value)},
            )


def _now() -> datetime:
    return datetime.now(timezone.utc)
