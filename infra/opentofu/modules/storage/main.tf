# Object storage: one bucket for datasets, one for evaluation/report artifacts.
# Uniform bucket-level access (no per-object ACLs), versioning for recovery, and
# a lifecycle rule so old versions do not accumulate cost forever.

variable "project_id" { type = string }
variable "region" { type = string }
variable "name_prefix" { type = string }
variable "force_destroy" {
  type    = bool
  default = false # production buckets are never emptied by `tofu destroy`
}

resource "google_storage_bucket" "datasets" {
  project  = var.project_id
  name     = "${var.name_prefix}-datasets"
  location = var.region
  # checkov:skip=CKV_GCP_62:access is captured by Cloud Audit Logs (Data Access);
  # a dedicated log-sink bucket is provisioned per deployment, not in this module.
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy

  versioning { enabled = true }

  lifecycle_rule {
    condition { num_newer_versions = 5 }
    action { type = "Delete" }
  }
}

resource "google_storage_bucket" "artifacts" {
  project  = var.project_id
  name     = "${var.name_prefix}-artifacts"
  location = var.region
  # checkov:skip=CKV_GCP_62:access is captured by Cloud Audit Logs (Data Access);
  # a dedicated log-sink bucket is provisioned per deployment, not in this module.
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy

  versioning { enabled = true }
}

output "datasets_bucket" { value = google_storage_bucket.datasets.name }
output "artifacts_bucket" { value = google_storage_bucket.artifacts.name }
