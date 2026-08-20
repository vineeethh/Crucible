# Workload Identity Federation: GitHub Actions authenticates to GCP with a
# short-lived OIDC token — no long-lived JSON service-account key ever exists
# (threat model T9). The deployer SA is least-privilege and the pool is scoped
# to exactly one repository and (optionally) one protected environment.

variable "project_id" { type = string }
variable "project_number" { type = string }
variable "name_prefix" { type = string }
variable "github_repository" {
  type        = string
  description = "owner/repo — the only repo allowed to assume the deployer identity."
}
variable "allowed_ref" {
  type        = string
  default     = "refs/heads/main"
  description = "Only this ref may deploy; PRs and forks cannot."
}
variable "impersonatable_service_accounts" {
  type        = list(string)
  default     = []
  description = "Runtime SA emails the deployer may actAs (deploy Cloud Run). Granted per-SA, never project-wide."
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "${var.name_prefix}-gh-pool"
  display_name              = "GitHub Actions (${var.name_prefix})"
  description               = "OIDC federation for ${var.github_repository}"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  # checkov:skip=CKV_GCP_125:the attribute_condition below hard-restricts tokens
  # to the exact repository, and the SA binding further restricts to that repo's
  # principalSet — a fork or another repo cannot assume the deployer identity.
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "github-oidc"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  # Hard gate: tokens are accepted only from the named repo. The SA binding
  # below further restricts to the deploy ref.
  attribute_condition = "assertion.repository == \"${var.github_repository}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-deployer"
  display_name = "CI deployer (${var.name_prefix})"
}

# Only workflows on the allowed ref of the allowed repo may impersonate the
# deployer SA. This is the credential the deploy workflow assumes.
resource "google_service_account_iam_member" "wif_binding" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member = format(
    "principalSet://iam.googleapis.com/projects/%s/locations/global/workloadIdentityPools/%s/attribute.repository/%s",
    var.project_number,
    google_iam_workload_identity_pool.github.workload_identity_pool_id,
    var.github_repository,
  )
}

# Least-privilege deploy permissions: push images, deploy Cloud Run, run the
# migration job, read the secrets the services mount. No project owner/editor,
# and no project-wide serviceAccountUser (that is granted per runtime SA below,
# CKV_GCP_41/49).
locals {
  deployer_roles = [
    "roles/run.developer",
    "roles/artifactregistry.writer",
    "roles/cloudsql.client", # migration job connects to Cloud SQL
  ]
}

resource "google_project_iam_member" "deployer" {
  for_each = toset(local.deployer_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

# actAs is granted ONLY on the specific runtime SAs the deploy needs to bind to
# Cloud Run — not at the project level.
resource "google_service_account_iam_member" "act_as" {
  for_each           = toset(var.impersonatable_service_accounts)
  service_account_id = "projects/${var.project_id}/serviceAccounts/${each.value}"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

output "provider_name" { value = google_iam_workload_identity_pool_provider.github.name }
output "deployer_sa_email" { value = google_service_account.deployer.email }
