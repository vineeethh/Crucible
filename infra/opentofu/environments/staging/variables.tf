variable "project_id" { type = string }
variable "project_number" { type = string }
variable "region" {
  type    = string
  default = "us-central1"
}
variable "github_repository" {
  type        = string
  description = "owner/repo permitted to deploy via OIDC."
}

# Images are passed by DIGEST from the deploy workflow (never a mutable tag).
variable "api_image" { type = string }
variable "worker_image" { type = string }
variable "git_sha" { type = string }

variable "db_app_user_password" {
  type      = string
  sensitive = true
}
