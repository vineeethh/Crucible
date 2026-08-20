# Secret Manager entries. Terraform declares the secret *containers* and who
# may read them; the secret *values* are added out-of-band (gcloud / a break-
# glass admin), never committed to state or VCS. State should still use a
# backend with restricted access.

variable "project_id" { type = string }
variable "name_prefix" { type = string }
variable "secret_ids" {
  type = list(string)
  default = [
    "database-url",
    "redis-url",
    "s3-secret-key",
    "oidc-audience",
    "model-provider-api-key",
  ]
}
variable "accessor_members" {
  type        = list(string)
  description = "serviceAccount:... principals allowed to read every secret."
  default     = []
}

resource "google_secret_manager_secret" "secret" {
  for_each  = toset(var.secret_ids)
  project   = var.project_id
  secret_id = "${var.name_prefix}-${each.value}"
  replication {
    auto {}
  }
}

# Runtime service accounts get read access to every declared secret.
resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = {
    for pair in setproduct(var.secret_ids, var.accessor_members) :
    "${pair[0]}::${pair[1]}" => { secret = pair[0], member = pair[1] }
  }
  project   = var.project_id
  secret_id = google_secret_manager_secret.secret[each.value.secret].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.member
}

output "secret_ids" {
  value = { for id, s in google_secret_manager_secret.secret : id => s.secret_id }
}
