# Immutable image registry. Deploys reference images by digest, never by
# mutable tag, so a rollback is deterministic (master plan §14).

variable "project_id" { type = string }
variable "region" { type = string }
variable "name_prefix" { type = string }

resource "google_artifact_registry_repository" "images" {
  # checkov:skip=CKV_GCP_84:images are encrypted with Google-managed keys; CMEK
  # is adopted only where the threat model requires it (ADR-007).
  project       = var.project_id
  location      = var.region
  repository_id = "${var.name_prefix}-images"
  format        = "DOCKER"
  description   = "Crucible API/worker images (deployed by digest)"

  docker_config {
    immutable_tags = true
  }
}

output "repository_url" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}
