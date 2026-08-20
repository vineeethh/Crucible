# Runbook: Deployment (staging → production)

Status: Phase 9 · Owner: on-call / project owner
Related: [rollback-runbook.md](rollback-runbook.md) ·
[migration-runbook.md](migration-runbook.md) ·
[disaster-recovery.md](disaster-recovery.md) ·
[ADR-007](../adr/ADR-007-gcp-reference-deployment.md)

Deployment is a protected, credential-minimal pipeline. No one deploys from a
laptop; there are no long-lived cloud keys. This runbook is the human view of
`.github/workflows/deploy-staging.yml` and `promote-production.yml`.

## Principles

- **Short-lived credentials only.** GitHub Actions federates to GCP via OIDC
  (Workload Identity Federation, `infra/opentofu/modules/wif`). The deployer
  service account is least-privilege and usable only from this repo on `main`.
- **Deploy by digest.** Images are referenced by `@sha256:…`, never a moving
  tag, so what runs is exactly what was built, signed, and tested.
- **Expand/contract migrations.** Schema changes are backward-compatible with
  the previous code revision, so a code rollback never needs a data rollback
  (see [migration-runbook.md](migration-runbook.md)).
- **Verify then keep; else roll back.** Every deploy runs smoke + canary + a
  smoke evaluation; failure auto-reverts traffic to the prior revision.

## One-time bootstrap (admin, not the CI deployer)

1. Create the Terraform state bucket and the WIF pool/provider + deployer SA
   (`infra/opentofu/README.md`).
2. Add secret *values* to Secret Manager (`gcloud secrets versions add …`).
3. Configure the GitHub `staging` and `production` environments: required
   reviewers, and the `vars`/`secrets` the workflows read (`GCP_PROJECT_ID`,
   `GCP_WIF_PROVIDER`, `GCP_DEPLOYER_SA`, `TF_STATE_BUCKET`, `STAGING_API_URL`,
   `DB_APP_USER_PASSWORD`, …).

## Deploy gating (until GCP is provisioned)

The `deploy` job is guarded by `if: ${{ vars.GCP_WIF_PROVIDER != '' }}`. Until the
one-time bootstrap above is done and that repository/environment **variable** is
set, the job is **skipped** — the `deploy-staging` workflow run succeeds without
attempting to authenticate, so pushes to `main` stay green while `pr-validate`
and `security` continue to enforce every code and security gate. Setting
`GCP_WIF_PROVIDER` (with the other `vars`/`secrets` listed above) is what turns
staging deploys on; nothing else changes.

## Staging deploy (automatic on merge to `main`)

`deploy-staging.yml` runs on push to `main` (or manual dispatch):

1. OIDC auth to GCP (no key).
2. Build API + worker images; capture their digests.
3. Sign the images (cosign, keyless) and attach a CycloneDX SBOM.
4. Run the **migrate** Cloud Run job (expand phase) — explicit, before the new
   revision serves.
5. `tofu apply` the staging stack pinned to the new digests.
6. **Verify**: `scripts/deploy_smoke.sh` checks `/healthz`, `/readyz` (all
   dependencies green), and `/version` (a real git SHA).
7. On any post-apply failure, **auto-rollback** to the previously serving
   revision.

Watch: the workflow run, then `STAGING_API_URL/readyz` and the reliability
dashboard. A red `/readyz` or a firing SEV1/SEV2 alert after deploy is a stop.

## Production promotion (manual, reviewed)

`promote-production.yml` is a manual dispatch that takes the **exact digests**
that passed staging (no rebuild):

1. It is gated by the `production` environment — a required reviewer approves.
2. **cosign verify** the signatures before anything is applied.
3. Migrate (expand) → `tofu apply` production pinned to those digests → smoke.
4. On smoke failure, auto-rollback the traffic split.

Record the promoted digests and the approver in the release notes.

## If a deploy goes wrong

- Post-deploy smoke red, or a SEV alert fires → the workflow already rolled back;
  confirm traffic is on the prior revision (`gcloud run services describe`), then
  triage the bad build off the serving path.
- Need to roll back after the window → [rollback-runbook.md](rollback-runbook.md).
- Data looks wrong / a migration is suspect → **do not** blind-rollback the DB;
  see [migration-runbook.md](migration-runbook.md) and
  [disaster-recovery.md](disaster-recovery.md).

## Verification before closing

- [ ] `/readyz` is 200 on the deployed environment.
- [ ] `/version` reports the intended git SHA.
- [ ] No SEV1/SEV2 alert firing after the deploy settles.
- [ ] Smoke evaluation gate passed (no correctness/policy regression).
- [ ] Promoted digests + approver recorded.
