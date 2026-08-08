#!/bin/sh
# Runs once, only against a freshly initialized (empty) data directory, via the
# official Postgres image's docker-entrypoint-initdb.d mechanism.
#
# Provisions the ORQ-26 evaluation store role (ADR-009 decision 5). Like
# 10-rag-app-role.sh, this lives here and not in an Alembic migration because
# roles are cluster-level and CREATE ROLE is not idempotent per database — and
# because the evaluation schema is deliberately outside the migration chain.
#
# This script covers local development only. It does NOT run against an existing
# data directory or a managed Postgres; ADR-009 documents the manual
# CREATE ROLE / GRANT path for those, which is the common case in staging.
#
# The role is deliberately NOT a superuser and gets no privilege on the
# application tables: an experiment must never hold a write path into business
# data. It owns the `evaluation` schema and nothing else.
#
# SQL is piped via stdin, not passed with -c: psql only performs variable
# interpolation (:'eval_password') when reading a script from stdin/-f, not in
# single-command (-c) mode.
set -e

if [ -z "${POSTGRES_EVALUATION_PASSWORD:-}" ]; then
  echo "20-evaluation-role.sh: POSTGRES_EVALUATION_PASSWORD is not set, skipping evaluation role provisioning" >&2
  exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v eval_password="$POSTGRES_EVALUATION_PASSWORD" -v db_name="$POSTGRES_DB" <<'SQL'
SELECT format(
  'ALTER ROLE rag_evaluation WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
  :'eval_password'
) AS stmt
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_evaluation')
\gexec

SELECT format(
  'CREATE ROLE rag_evaluation WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
  :'eval_password'
) AS stmt
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_evaluation')
\gexec

GRANT CONNECT ON DATABASE :"db_name" TO rag_evaluation;

-- The harness creates the `evaluation` schema itself on first run, so the role
-- needs CREATE on the database. It is granted nothing on `public`, where the
-- application's tables live.
GRANT CREATE ON DATABASE :"db_name" TO rag_evaluation;

-- The evaluation role gets nothing on `public`, where the application's tables
-- live. Stated as an explicit revoke rather than left to defaults, because the
-- default privileges on `public` have changed across Postgres major versions
-- and this must not depend on which one is running.
--
-- The converse — rag_app holding no privilege on `evaluation` — needs no
-- statement here: the schema does not exist yet at init time, and the harness
-- creates it as rag_evaluation, so rag_app never acquires anything on it.
REVOKE ALL ON SCHEMA public FROM rag_evaluation;
SQL
