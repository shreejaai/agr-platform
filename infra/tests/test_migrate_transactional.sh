#!/bin/sh
# Smoke test for the transactional migration runner.
#
# Skips automatically when no Postgres is reachable, so it is safe to run
# locally without infra. To run against a real DB:
#
#   POSTGRES_HOST=localhost POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres \
#   POSTGRES_DB=agr_migrate_test ./infra/tests/test_migrate_transactional.sh
#
# Asserts:
#   1. A clean run applies all files and records them in schema_migrations.
#   2. A second run is a no-op (idempotent).
#   3. A mid-file failure rolls back the partial schema change AND does not
#      record the file in schema_migrations.
#   4. Re-applying with mutated content is rejected with a clear error.
set -eu

POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-postgres}"
POSTGRES_DB="${POSTGRES_DB:-agr_migrate_test}"
export POSTGRES_HOST POSTGRES_PORT POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB

PSQL_BASE="psql postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/postgres"
PSQL_DB="psql postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"

if ! $PSQL_BASE -c 'SELECT 1' >/dev/null 2>&1; then
    echo "SKIP: postgres not reachable at ${POSTGRES_HOST}:${POSTGRES_PORT}"
    exit 0
fi

cleanup() {
    $PSQL_BASE -c "DROP DATABASE IF EXISTS ${POSTGRES_DB};" >/dev/null 2>&1 || true
    rm -rf "${WORKDIR:-}"
}
trap cleanup EXIT

$PSQL_BASE -c "DROP DATABASE IF EXISTS ${POSTGRES_DB};" >/dev/null
$PSQL_BASE -c "CREATE DATABASE ${POSTGRES_DB};" >/dev/null

WORKDIR=$(mktemp -d)
MIGRATIONS="${WORKDIR}/migrations"
mkdir -p "$MIGRATIONS"

cat > "${MIGRATIONS}/001_first.sql" <<'SQL'
CREATE TABLE t1 (id INT PRIMARY KEY);
SQL
cat > "${MIGRATIONS}/002_second.sql" <<'SQL'
CREATE TABLE t2 (id INT PRIMARY KEY);
SQL

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
RUNNER="${SCRIPT_DIR}/../migrate.sh"

echo "[1] clean run"
MIGRATIONS_DIR="$MIGRATIONS" "$RUNNER" >/dev/null
count=$($PSQL_DB -At -c "SELECT count(*) FROM schema_migrations;")
[ "$count" = "2" ] || { echo "FAIL: expected 2 rows, got $count"; exit 1; }

echo "[2] idempotent re-run"
MIGRATIONS_DIR="$MIGRATIONS" "$RUNNER" >/dev/null
count=$($PSQL_DB -At -c "SELECT count(*) FROM schema_migrations;")
[ "$count" = "2" ] || { echo "FAIL: re-run inserted rows"; exit 1; }

echo "[3] broken migration rolls back"
cat > "${MIGRATIONS}/003_broken.sql" <<'SQL'
CREATE TABLE t3 (id INT PRIMARY KEY);
SELECT 1 / 0;
SQL
set +e
MIGRATIONS_DIR="$MIGRATIONS" "$RUNNER" >/dev/null 2>&1
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAIL: broken migration did not fail"; exit 1; }
exists=$($PSQL_DB -At -c "SELECT to_regclass('t3') IS NOT NULL;")
[ "$exists" = "f" ] || { echo "FAIL: t3 leaked despite rollback"; exit 1; }
recorded=$($PSQL_DB -At -c "SELECT count(*) FROM schema_migrations WHERE filename='003_broken.sql';")
[ "$recorded" = "0" ] || { echo "FAIL: broken migration was recorded"; exit 1; }

echo "[4] content drift rejected"
rm "${MIGRATIONS}/003_broken.sql"
echo "CREATE TABLE t1_drift (id INT);" > "${MIGRATIONS}/001_first.sql"
set +e
out=$(MIGRATIONS_DIR="$MIGRATIONS" "$RUNNER" 2>&1)
rc=$?
set -e
[ "$rc" -ne 0 ] || { echo "FAIL: drift was not rejected"; exit 1; }
echo "$out" | grep -q "different content hash" \
    || { echo "FAIL: drift error message missing"; exit 1; }

echo "OK"
