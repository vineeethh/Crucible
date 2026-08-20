# A generic Cloud Run v2 service (used for both the API and the worker), each
# with its OWN service account so their IAM blast radius is disjoint (the worker
# never needs presign/CORS surface; the API never needs the microVM control
# credential). Images are always referenced by DIGEST for deterministic
# rollback. Secrets are mounted from Secret Manager, never baked into the image.

variable "project_id" { type = string }
variable "region" { type = string }
variable "name" { type = string }
variable "image" {
  type        = string
  description = "Full image reference by digest: REGISTRY/repo@sha256:..."
}
variable "service_account_email" { type = string }
variable "vpc_connector_id" { type = string }
variable "env" {
  type    = map(string)
  default = {}
}
variable "secret_env" {
  type        = map(object({ secret = string, version = string }))
  default     = {}
  description = "Env vars sourced from Secret Manager secrets."
}
variable "ingress" {
  type    = string
  default = "INGRESS_TRAFFIC_ALL" # the API; the worker overrides to internal
}
variable "min_instances" {
  type    = number
  default = 0
}
variable "max_instances" {
  type    = number
  default = 4
}
variable "allow_unauthenticated" {
  type    = bool
  default = false
}

resource "google_cloud_run_v2_service" "svc" {
  project  = var.project_id
  name     = var.name
  location = var.region
  ingress  = var.ingress

  # Deploys are digest-pinned; refuse to reconcile a half-ready revision.
  deletion_protection = false

  template {
    service_account = var.service_account_email
    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }
    vpc_access {
      connector = var.vpc_connector_id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.image

      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value.secret
              version = env.value.version
            }
          }
        }
      }

      # Liveness/readiness map to the app's own probes (Phase 1/6).
      startup_probe {
        http_get { path = "/healthz" }
        initial_delay_seconds = 5
        failure_threshold     = 10
        period_seconds        = 3
      }
      liveness_probe {
        http_get { path = "/healthz" }
        period_seconds = 30
      }
    }
  }
}

# Public invokers only when explicitly allowed (the API behind a load balancer;
# the worker is never public).
resource "google_cloud_run_v2_service_iam_member" "invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.svc.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "uri" { value = google_cloud_run_v2_service.svc.uri }
output "service_name" { value = google_cloud_run_v2_service.svc.name }
