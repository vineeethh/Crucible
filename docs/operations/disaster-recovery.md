# Runbook: Disaster recovery

Status: Phase 9 · Owner: on-call / project owner
Related: [migration-runbook.md](migration-runbook.md) ·
[deployment-runbook.md](deployment-runbook.md) · evidence: `evidence/dr-drill-*.md`

Postgres is the system of record (ADR-002). Redis (the queue) and the sandbox
are recoverable/derived: a queue loss is survivable (the run store re-drives —
proven by the queue-loss game day), and the cache is derived state. So DR is
principally **database recovery**, plus re-deploying stateless services from
immutable images.

## Objectives

- **RPO (max data loss):** ≤ 5 minutes — Cloud SQL point-in-time recovery
  (transaction log retention) plus daily automated backups (30 retained). See
  `infra/opentofu/modules/database`.
- **RTO (max downtime):** ≤ 60 minutes for a full restore + redeploy.

## Backups

- **Cloud:** Cloud SQL automated backups (daily, 03:00) + PITR, retained 30
  days. Buckets are versioned; images are immutable in Artifact Registry.
- **Portable / pre-change:** `scripts/backup_db.sh` produces a
  `pg_dump --format=custom` archive, restorable with `scripts/restore_db.sh`.

## Recovery procedures

### A. Point-in-time restore (data corruption / bad write, cloud)

1. Identify the last-good timestamp (before the corrupting event).
2. Clone the instance to that timestamp:
   `gcloud sql instances clone crucible-<env>-pg crucible-<env>-pg-recovered --point-in-time <RFC3339>`.
3. Verify the clone (row counts, spot-check the affected tables).
4. Cut over: repoint the `database-url` secret to the recovered instance and
   redeploy (digest-pinned), or promote the clone. Keep the original for
   forensics.

### B. Full restore from a logical backup (portable / local)

```bash
scripts/restore_db.sh <backup.dump> crucible_restore   # into a scratch DB first
# verify, then repoint the app at the restored database and redeploy
```

### C. Lost queue (Redis)

No restore needed. Bring Redis back (Memorystore failover / re-provision) and
re-drive non-terminal runs from the store — the queue-loss game day
(`tests/integration/test_resilience_gameday.py`) is the exact recovery, proven
idempotent (a re-delivered job that already terminated is a no-op).

## The recovery drill (evidence)

`scripts/dr_drill.sh` is a **non-destructive, repeatable** proof of the
backup→restore path: it plants a marker row, backs up, restores into a scratch
database, verifies the marker and table counts survived, cleans up, and writes
`docs/operations/evidence/dr-drill-<timestamp>.md`. Run it before any release
that changes the data model, and on a schedule. The live database is never
touched (the restore targets a scratch DB).

Latest committed evidence: see `evidence/dr-drill-*.md` (the drill has been
executed and passed — org and run counts matched between live and restore, and
the planted marker was recovered).

## Verification before closing

- [ ] Restored/recovered database passes the marker + count checks.
- [ ] Application `/readyz` green against the recovered database.
- [ ] Original/corrupted instance preserved for forensics.
- [ ] RPO/RTO actuals recorded against the targets; timeline written up.
