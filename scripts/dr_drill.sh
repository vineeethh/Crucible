#!/usr/bin/env bash
# Disaster-recovery drill (master plan Phase 9 DoD: "a documented recovery drill
# has evidence"). Proves the backup→restore path actually recovers data, without
# touching the live database: it plants a uniquely-tagged marker row, backs up,
# restores into a SCRATCH database, verifies the marker and the table counts
# survived, and writes a timestamped evidence file. Non-destructive and repeatable.
#
#   scripts/dr_drill.sh
set -euo pipefail

CONTAINER="${PG_CONTAINER:-crucible-postgres-1}"
USER="${PGUSER:-crucible}"
PASS="${PGPASSWORD:-crucible}"
DB="${PGDATABASE:-crucible}"
SCRATCH="crucible_dr_drill"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
MARKER="dr-drill-${STAMP}"
DUMP="/tmp/dr-${STAMP}.dump"
EVIDENCE_DIR="docs/operations/evidence"
EVIDENCE="${EVIDENCE_DIR}/dr-drill-${STAMP}.md"

psql_live() { docker exec -e PGPASSWORD="${PASS}" "${CONTAINER}" psql -U "${USER}" -d "${DB}" -tAc "$1"; }
psql_scratch() { docker exec -e PGPASSWORD="${PASS}" "${CONTAINER}" psql -U "${USER}" -d "${SCRATCH}" -tAc "$1"; }

echo "== DR drill ${STAMP} =="

# 1. Plant a marker: a real, restorable organization row we can look for.
echo "[1/5] planting marker organization slug=${MARKER}"
psql_live "INSERT INTO organizations (id, slug, name) VALUES (gen_random_uuid(), '${MARKER}', 'DR drill');" >/dev/null
live_orgs=$(psql_live "SELECT count(*) FROM organizations;")

# 2. Back up.
echo "[2/5] backing up ${DB}"
scripts/backup_db.sh "${DUMP}" >/dev/null

# 3. Restore into a scratch database (live DB untouched).
echo "[3/5] restoring into scratch db ${SCRATCH}"
scripts/restore_db.sh "${DUMP}" "${SCRATCH}" >/dev/null

# 4. Verify: the marker is present in the restore, and org counts match.
echo "[4/5] verifying restore"
restored_marker=$(psql_scratch "SELECT count(*) FROM organizations WHERE slug='${MARKER}';")
restored_orgs=$(psql_scratch "SELECT count(*) FROM organizations;")
restored_runs=$(psql_scratch "SELECT count(*) FROM agent_runs;")
live_runs=$(psql_live "SELECT count(*) FROM agent_runs;")

ok=1
[ "${restored_marker}" = "1" ] || { echo "  FAIL: marker missing in restore"; ok=0; }
[ "${restored_orgs}" = "${live_orgs}" ] || { echo "  FAIL: org count ${restored_orgs} != ${live_orgs}"; ok=0; }
[ "${restored_runs}" = "${live_runs}" ] || { echo "  FAIL: run count ${restored_runs} != ${live_runs}"; ok=0; }

# 5. Clean up scratch + marker; write evidence.
echo "[5/5] cleaning up and writing evidence"
docker exec -e PGPASSWORD="${PASS}" "${CONTAINER}" psql -U "${USER}" -d postgres -c "DROP DATABASE IF EXISTS ${SCRATCH};" >/dev/null
psql_live "DELETE FROM organizations WHERE slug='${MARKER}';" >/dev/null
docker exec "${CONTAINER}" rm -f "${DUMP}" 2>/dev/null || true

mkdir -p "${EVIDENCE_DIR}"
result=$([ "${ok}" = "1" ] && echo PASS || echo FAIL)
cat > "${EVIDENCE}" <<EOF
# DR drill evidence — ${STAMP}

Result: **${result}**

Procedure: plant marker org \`${MARKER}\` in the live database, \`pg_dump\`
(custom format), \`pg_restore\` into scratch database \`${SCRATCH}\`, verify.

| check | live | restored |
|---|---|---|
| organizations | ${live_orgs} | ${restored_orgs} |
| agent_runs | ${live_runs} | ${restored_runs} |
| marker present | planted | ${restored_marker} (expect 1) |

The live database was untouched (restore targeted a scratch database); the
marker and scratch database were removed after verification. Backup format is
\`pg_dump --format=custom\`, restorable with \`scripts/restore_db.sh\`.
EOF

echo "== DR drill ${result}: evidence -> ${EVIDENCE} =="
[ "${ok}" = "1" ]
