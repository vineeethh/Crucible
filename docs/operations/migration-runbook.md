# Runbook: Database migrations (expand / contract)

Status: Phase 9 · Owner: on-call / project owner
Related: [deployment-runbook.md](deployment-runbook.md) ·
[rollback-runbook.md](rollback-runbook.md) ·
[ADR-002](../adr/ADR-002-postgres-system-of-record.md)

Migrations run as an **explicit deploy step, never on app startup** (plan §5.4;
the `no-app-startup-migrations` semgrep rule enforces this). The discipline is
**expand/contract**, so a code rollback is always safe against the live schema.

## The rule: never break the previous revision

At any instant, two code revisions may be serving (during a rollout, and after a
rollback). A migration must keep **both** working. That forbids, in a single
deploy: dropping/renaming a column still read by the old code, adding a NOT NULL
column without a default, or tightening a constraint the old code can violate.

## Expand → migrate data → contract (across separate deploys)

1. **Expand** (deploy N): add the new column/table/index, nullable/defaulted and
   backward-compatible. New code writes both old and new shapes; old code
   ignores the new. This is the migration the deploy workflow runs.
2. **Backfill** (between deploys): populate new columns for existing rows via a
   one-off job; verify.
3. **Contract** (deploy N+1, only after N is stable): now that no serving
   revision reads the old shape, drop it / add the constraint. This is a
   *separate, later* deploy — never bundled with the expand.

A destructive change and its expanding counterpart are never in the same
release, so rollback never needs a data downgrade.

## Running a migration

- **Cloud (staging/production):** the deploy/promote workflows deploy and
  execute the `crucible-<env>-migrate` Cloud Run job (`alembic upgrade head`)
  before the new revision serves.
- **Local:** `make migrate` (`alembic -c packages/db/alembic.ini upgrade head`).
- **Offline review:** `alembic … upgrade head --sql` renders the SQL for review
  in the PR (pr-validate runs this).

## Before a risky migration

1. Take a logical backup: `scripts/backup_db.sh` (Cloud SQL also has automated
   backups + PITR).
2. Confirm the migration is reversible in a scratch DB (the alembic
   `downgrade`/`upgrade` roundtrip is asserted in
   `tests/integration/test_migrations_postgres.py`).
3. Review the rendered SQL and the lock profile (a long `ALTER` that rewrites a
   large table needs a maintenance window or an online strategy).

## If a migration fails mid-way

- Alembic runs each migration in a transaction on Postgres, so a failed
  migration rolls itself back — the schema stays at the prior revision. Fix the
  migration and re-run; do not hand-edit the live schema.
- If a migration partially succeeded because it was split across transactions
  (large backfills), resume from the documented step; never leave the schema
  between two revisions.

## Verification before closing

- [ ] `alembic current` reports the intended head on the target DB.
- [ ] Both the new and previous code revisions read/write correctly.
- [ ] For a contract migration: no serving revision still needs the dropped
      shape.
- [ ] The migration head string in the two migration tests was bumped.
