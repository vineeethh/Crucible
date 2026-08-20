#!/usr/bin/env bash
# Logical backup of the Crucible database in the custom (compressed, selectively
# restorable) format. In cloud, Cloud SQL automated backups + PITR are the
# primary mechanism (see infra/opentofu/modules/database); this script is the
# portable, local/DR-drill equivalent and the "export before a risky migration"
# tool.
#
#   scripts/backup_db.sh [output.dump]
#
# Runs pg_dump inside the Postgres container so no host client is required.
set -euo pipefail

OUT="${1:-backup-$(date -u +%Y%m%dT%H%M%SZ).dump}"
CONTAINER="${PG_CONTAINER:-crucible-postgres-1}"
DB="${PGDATABASE:-crucible}"
USER="${PGUSER:-crucible}"
PASS="${PGPASSWORD:-crucible}"

echo "[backup] pg_dump ${DB} -> ${OUT} (via ${CONTAINER})"
docker exec -e PGPASSWORD="${PASS}" "${CONTAINER}" \
  pg_dump -U "${USER}" -d "${DB}" --format=custom --no-owner --no-privileges \
  > "${OUT}"

bytes=$(wc -c < "${OUT}")
echo "[backup] wrote ${OUT} (${bytes} bytes)"
if [ "${bytes}" -lt 1000 ]; then
  echo "[backup] FAILED: dump is suspiciously small" >&2
  exit 1
fi
