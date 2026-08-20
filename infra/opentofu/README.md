# OpenTofu environments (Phase 9)

Infrastructure as code for the GCP reference deployment (ADR-007). No
console-click infrastructure: staging and production are reproduced from these
files, and a `tofu plan` is the artifact a reviewer reads before any deploy.

## Layout

```
modules/
  network/            VPC, subnet (flow logs), Serverless VPC connector, PSA range
  database/           Cloud SQL Postgres 17 — private IP, HA, PITR + 30d backups
  redis/              Memorystore Redis — private, AUTH + TLS
  storage/            GCS datasets/artifacts buckets — UBLA, versioned, PAP enforced
  secrets/            Secret Manager containers + accessor IAM (values out-of-band)
  artifact_registry/  Docker repo with immutable tags (deploy by digest)
  wif/                Workload Identity Federation for GitHub OIDC + least-priv deployer SA
  cloud_run_service/  Generic Cloud Run v2 service (API and worker, separate SAs)
environments/
  staging/            Full stack, single-node Redis, smaller DB tier
  production/          Regional HA Redis, larger DB tier, higher floors
```

## Security posture baked in

- **No long-lived cloud keys.** GitHub Actions federates via WIF/OIDC
  (`modules/wif`); the deployer SA is least-privilege (run.developer,
  artifactregistry.writer, serviceAccountUser, cloudsql.client) and usable only
  from `OWNER/crucible` on `refs/heads/main` (threat T9).
- **No public data plane.** Cloud SQL and Redis are private-IP only; Cloud Run
  reaches them through the VPC connector. Buckets enforce public-access
  prevention and uniform bucket-level access (T5).
- **Separate runtime identities.** The API and worker each run as their own
  service account with disjoint IAM (ADR-003, T4).
- **Deterministic rollback.** Images are referenced by digest; the registry
  uses immutable tags.
- **Recoverable data.** Cloud SQL has PITR + 30 days of retained backups; the
  DR drill (`docs/operations/disaster-recovery.md`) restores from them.

## Bootstrap (once, by an admin — not the CI deployer)

The state bucket and the WIF pool are chicken-and-egg with CI, so an admin
creates them first:

```bash
# 1. State bucket (versioned, restricted IAM).
gsutil mb -p "$PROJECT" -b on "gs://crucible-tfstate-$PROJECT"
gsutil versioning set on "gs://crucible-tfstate-$PROJECT"

# 2. Init + apply staging (from environments/staging).
tofu init -backend-config="bucket=crucible-tfstate-$PROJECT"
tofu plan  -var-file=terraform.tfvars      # reviewed
tofu apply -var-file=terraform.tfvars
```

Thereafter the deploy workflow supplies `api_image`/`worker_image`/`git_sha`
and runs `tofu apply` under the federated deployer identity. Secret *values*
(`*-database-url`, etc.) are written with `gcloud secrets versions add`, never
through Terraform state.

## Validate locally

```bash
tofu fmt -recursive -check
cd environments/staging && tofu init -backend=false && tofu validate
```

> These files are authored against the `hashicorp/google ~> 6.0` provider.
> CI runs `tofu fmt -check` and `tofu validate` (see `.github/workflows/iac.yml`);
> `tofu plan` for a real project runs in the deploy workflow behind OIDC.
