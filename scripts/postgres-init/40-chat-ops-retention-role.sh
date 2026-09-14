#!/bin/sh
# Runs once, only against a freshly initialized (empty) data directory, via the
# official Postgres image's docker-entrypoint-initdb.d mechanism.
#
# Provisions the RETENTION role (ORQ-37 §Diseño 6/7) here -- NOT in an Alembic
# migration -- for the same reason as 30-chat-ops-role.sh: roles are
# cluster-level and CREATE ROLE is not idempotent per database. The grants
# themselves ARE in a migration (e4b7f21c9a06), guarded by a role-existence
# check so it stays reversible where this script never ran.
#
# This role is DELIBERATELY SEPARATE from chat_ops (the runtime role). Giving
# the request-serving credential SELECT/DELETE on the metrics table would let
# a compromised application path erase or read cross-tenant telemetry -- the
# opposite of the least-privilege boundary the split exists to hold. This
# role is operator-held and is NEVER placed in the application's
# configuration (no DATABASE_URL_* setting references it).
#
# The password is read from POSTGRES_OPS_RETENTION_PASSWORD at container
# start; it is never written to a versioned file (this repository is public).
set -e

if [ -z "${POSTGRES_OPS_RETENTION_PASSWORD:-}" ]; then
  echo "40-chat-ops-retention-role.sh: POSTGRES_OPS_RETENTION_PASSWORD is not set, skipping retention role provisioning" >&2
  exit 0
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v ret_password="$POSTGRES_OPS_RETENTION_PASSWORD" -v db_name="$POSTGRES_DB" <<'SQL'
SELECT format(
  'ALTER ROLE chat_ops_retention WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
  :'ret_password'
) AS stmt
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'chat_ops_retention')
\gexec

SELECT format(
  'CREATE ROLE chat_ops_retention WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS',
  :'ret_password'
) AS stmt
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'chat_ops_retention')
\gexec

GRANT CONNECT ON DATABASE :"db_name" TO chat_ops_retention;
SQL
