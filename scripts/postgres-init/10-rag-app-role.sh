#!/bin/sh
# Runs once, only against a freshly initialized (empty) data directory, via the
# official Postgres image's docker-entrypoint-initdb.d mechanism.
#
# Provisions the RAG application role here — NOT in an Alembic migration —
# because roles are cluster-level and CREATE ROLE is not idempotent per
# database (spec.md §Design decisions 4, ORQ-21). The password is read from
# POSTGRES_APP_PASSWORD at container start; it is never written to a
# versioned file (this repository is public).
#
# SQL is piped via stdin, not passed with -c: psql only performs variable
# interpolation (:'app_password') when reading a script from stdin/-f, not
# in single-command (-c) mode — verified empirically against psql 16.
set -e

if [ -z "${POSTGRES_APP_PASSWORD:-}" ]; then
  echo "10-rag-app-role.sh: POSTGRES_APP_PASSWORD is not set, skipping RAG app role provisioning" >&2
  exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$POSTGRES_APP_PASSWORD" -v db_name="$POSTGRES_DB" <<'SQL'
SELECT format(
  'ALTER ROLE rag_app WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
  :'app_password'
) AS stmt
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_app')
\gexec

SELECT format(
  'CREATE ROLE rag_app WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
  :'app_password'
) AS stmt
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rag_app')
\gexec

GRANT CONNECT ON DATABASE :"db_name" TO rag_app;
SQL
