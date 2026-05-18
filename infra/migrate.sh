#!/bin/sh
# Transactional, idempotent migration runner for AGR.
#
# Each *.sql file under $MIGRATIONS_DIR is applied inside a single transaction
# via `psql --single-transaction -v ON_ERROR_STOP=1`. The same psql invocation
# also records the file's sha256 in `schema_migrations`, so a mid-file failure
# rolls back *both* the schema change and the bookkeeping row.
#
# Re-running the script is a no-op for already-applied files. If a file's
# content changes after it was applied, the runner aborts to prevent silent
# drift.
set -eu

PSQL_URL="postgresql://${POSTGRES_USER:-agr_svc_usr}:${POSTGRES_PASSWORD}@${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-agr_platform}"
PSQL="psql ${PSQL_URL}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-/migrations}"

# Bootstrap bookkeeping table.
$PSQL -v ON_ERROR_STOP=1 -q <<'SQL'
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename   TEXT PRIMARY KEY,
    sha256     TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
SQL

if command -v sha256sum >/dev/null 2>&1; then
    sha_cmd="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
    sha_cmd="shasum -a 256"
else
    echo "ERROR: need sha256sum or shasum on PATH" >&2
    exit 1
fi

echo "Running migrations from $MIGRATIONS_DIR ..."
for f in "$MIGRATIONS_DIR"/[0-9][0-9][0-9]_*.sql; do
    [ -f "$f" ] || continue
    name=$(basename "$f")
    hash=$($sha_cmd "$f" | awk '{print $1}')

    applied=$($PSQL -v ON_ERROR_STOP=1 -At \
        -c "SELECT sha256 FROM schema_migrations WHERE filename = '${name}';")

    if [ -n "$applied" ]; then
        if [ "$applied" != "$hash" ]; then
            echo "ERROR: ${name} already applied with a different content hash" >&2
            echo "       (db=${applied} file=${hash}). Refusing to re-apply." >&2
            exit 1
        fi
        echo "  ${name} skip (already applied)"
        continue
    fi

    echo "  ${name} applying..."
    # Pipe migration body + bookkeeping insert into one transactional psql call
    # so a mid-file error rolls back both the schema change and the row insert.
    {
        cat "$f"
        printf "\nINSERT INTO schema_migrations (filename, sha256) VALUES ('%s', '%s');\n" "$name" "$hash"
    } | $PSQL -v ON_ERROR_STOP=1 --single-transaction -q
    echo "  ${name} done"
done

echo "All migrations complete."
