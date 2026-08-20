#!/usr/bin/env bash
# Restore a custom-format dump into a target database. Used by the DR drill and
# for a real recovery. Restoring into a *scratch* database is the safe default;
# restoring over the live database requires RESTORE_INTO to be set explicitly.
#
#   scripts/restore_db.sh <input.dump> [target_db]
set -euo pipefail

IN="${1:?usage: restore_db.sh <input.dump> [target_db]}"
TARGET="${2:-crucible_restore}"
CONTAINER="${PG_CONTAINER:-crucible-postgres-1}"
USER="${PGUSER:-crucible}"
PASS="${PGPASSWORD:-crucible}"

[ -f "${IN}" ] || { echo "[restore] no such dump: ${IN}" >&2; exit 1; }

echo "[restore] (re)creating target database ${TARGET}"
docker exec -e PGPASSWORD="${PASS}" "${CONTAINER}" \
  psql -U "${USER}" -d postgres -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${TARGET};"
docker exec -e PGPASSWORD="${PASS}" "${CONTAINER}" \
  psql -U "${USER}" -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${TARGET};"

echo "[restore] pg_restore ${IN} -> ${TARGET}"
docker exec -i -e PGPASSWORD="${PASS}" "${CONTAINER}" \
  pg_restore -U "${USER}" -d "${TARGET}" --no-owner --no-privileges --exit-on-error \
  < "${IN}"

echo "[restore] done -> ${TARGET}"
