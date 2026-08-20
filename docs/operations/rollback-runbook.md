# Runbook: Rollback

Status: Phase 9 · Owner: on-call · Related:
[deployment-runbook.md](deployment-runbook.md) ·
[migration-runbook.md](migration-runbook.md)

A rollback here is a **traffic shift to a previous, known-good revision** — fast
and reversible. Because migrations are expand/contract, the prior revision is
compatible with the current schema, so a *code* rollback never requires a *data*
rollback.

## When to roll back

- Post-deploy smoke failed (the deploy workflow already auto-rolled back —
  verify it did).
- A SEV1/SEV2 alert started firing right after a deploy (containment, trace
  completeness, technical completion; see
  [alert-runbook.md](alert-runbook.md)).
- Error rate or latency regressed sharply and correlates with the release.

## How (automatic)

The staging deploy and production promotion workflows record the serving
revision before applying and revert to it on any post-apply failure. Confirm:

```bash
gcloud run services describe crucible-<env>-api --region "$REGION" \
  --format='value(status.traffic[].revisionName, status.traffic[].percent)'
```

## How (manual)

Use the **rollback** workflow (`.github/workflows/rollback.yml`): dispatch with
the target environment, service (`api`/`worker`), and the revision to shift 100%
of traffic to. It runs under OIDC in the protected environment (a reviewer
approves a rollback too). Equivalent CLI for a break-glass:

```bash
gcloud run services update-traffic crucible-<env>-<service> \
  --region "$REGION" --to-revisions "<REVISION>=100"
```

List candidate revisions with `gcloud run revisions list --service … --region …`.

## What a rollback does NOT do

- It does not revert the database. Expand-phase migrations are additive and
  backward-compatible, so this is safe. A **contract** migration is only run
  *after* the expanding code has been stable for a full release — never in the
  same deploy — so at any moment the prior revision still fits the schema.
- If you believe data was corrupted (not just code misbehaving), stop and go to
  [disaster-recovery.md](disaster-recovery.md); do not attempt a schema
  downgrade against production.

## Verification before closing

- [ ] Traffic is 100% on the known-good revision.
- [ ] `/readyz` green; the firing alert has cleared.
- [ ] The bad build is off the serving path and captured for triage.
- [ ] Incident timeline recorded; a fix-forward plan noted.
