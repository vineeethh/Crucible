# Data retention & erasure policy

Status: Phase 10 · Owner: project owner / DPO
Related: [data-processing-notice.md](../legal/data-processing-notice.md) ·
[disaster-recovery.md](disaster-recovery.md) · enforced by
`crucible_worker.jobs.retention` and `scripts/admin.py`

Crucible minimizes retained data by default: it keeps what an operator needs to
run, debug, and account for the platform, and deletes the rest on a schedule.
This policy is executable — the retention job and the admin CLI implement it,
and the integration tests assert it.

## What is kept, and for how long

| Data | Default retention | Notes |
|---|---|---|
| Terminal runs + evidence (events, attempts, checkpoints, verification, scores) | **90 days** | Deleted by the daily retention job. Per-tenant override via `retention_days`. |
| Exact-cache entries | Same window | Derived state; safe to delete any time. |
| Datasets & versions | Until deleted | User assets; removed on explicit deletion or full erasure. |
| Audit events | Retained | Security/compliance evidence; out of the retention job's scope. |
| Backups (Cloud SQL) | 30 days + 7-day PITR | Recovery, not analytics (see disaster-recovery). |

Non-terminal (in-flight) runs are **never** reaped, regardless of age.

## How retention runs

- **Automatically:** the worker runs `apply_retention` daily (04:30). It deletes
  terminal runs and their child evidence older than the window (per-tenant
  cutoff honoured), plus old cache entries. Audit and datasets are untouched.
- **On demand / dry run:** `uv run python scripts/admin.py retention` (dry run)
  or `--apply`. The dry run reports what *would* be deleted, per tenant.
- **Configuration:** the platform default is `CRUCIBLE_RETENTION_DAYS` (worker);
  a tenant override is `organizations.retention_days`
  (`scripts/admin.py set-retention --slug … --days …`).

## Erasure (data-deletion request)

A tenant's right-to-erasure is handled by the admin CLI, always dry-run first:

```bash
uv run python scripts/admin.py purge-org --slug acme            # dry run: counts
uv run python scripts/admin.py purge-org --slug acme --apply    # irreversible
```

`purge-org` deletes **all** of a tenant's data — runs and evidence, datasets and
versions, API keys, memberships, budgets, cache, scores, and the org's audit
events — then the organization row itself, inside one transaction. Global user
records (identified by OIDC subject) are left intact; a user with no remaining
memberships simply has no access. Object-storage objects for the tenant are
removed by the storage lifecycle / a companion sweep (the DB purge removes the
version rows that reference them).

## User-data boundaries (what never leaves)

- Prompts and dataset contents never enter traces or third-party telemetry: the
  redaction boundary (threat T8) emits a tenant *pseudonym*, hashes, and bounded
  excerpts only.
- Sampled online evaluation records deterministic scores, **not** raw data.
- Backups and logs inherit the same tenant scoping; a restore targets a scratch
  database first (DR drill), never exposing one tenant's data to another.

## Verification

`tests/integration/test_retention_and_lifecycle.py`: old terminal runs and all
their evidence are deleted while recent runs survive; a non-terminal run is
never reaped; a dry run deletes nothing; `purge-org` removes every tenant table
and the org, and the org's key stops authenticating.
