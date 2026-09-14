#!/bin/sh
# Runs once, only against a freshly initialized (empty) data directory, via the
# official Postgres image's docker-entrypoint-initdb.d mechanism.
#
# Provisions the OPERATIONAL role (ORQ-37 §Diseño 7) here — NOT in an Alembic
# migration — for the same reason as 10-rag-app-role.sh: roles are
# cluster-level and CREATE ROLE is not idempotent per database. The grants
# themselves ARE in a migration (they are per-database, per-table objects);
# that migration is guarded by a role-existence check so it stays
# side-effect-free where this script never ran.
#
# NOBYPASSRLS is kept even though §Diseño 7 introduces no RLS on
# conversations/messages: this role must not become a way around the policies
# that DO exist on documents/chunks.
#
# The password is read from POSTGRES_OPS_PASSWORD at container start; it is
# never written to a versioned file (this repository is public).
set -e

if [ -z "${POSTGRES_OPS_PASSWORD:-}" ]; then
  echo "30-chat-ops-role.sh: POSTGRES_OPS_PASSWORD is not set, skipping operational role provisioning" >&2
  exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v ops_password="$POSTGRES_OPS_PASSWORD" -v db_name="$POSTGRES_DB" <<'SQL'
SELECT format(
  'ALTER ROLE chat_ops WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
  :'ops_password'
) AS stmt
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'chat_ops')
\gexec

SELECT format(
  'CREATE ROLE chat_ops WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
  :'ops_password'
) AS stmt
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'chat_ops')
\gexec

GRANT CONNECT ON DATABASE :"db_name" TO chat_ops;
SQL
