# Production environment. Identical topology to staging (same modules, same
# provider-neutral app) with production-grade knobs: regional HA Redis, deletion
# protection, higher floors, and NO force_destroy anywhere. Promotion deploys
# the exact image DIGEST that passed staging — never a rebuild (master plan §14).

locals {
  name_prefix = "crucible-prod"
}

module "network" {
  source      = "../../modules/network"
  project_id  = var.project_id
  region      = var.region
  name_prefix = local.name_prefix
}

module "artifact_registry" {
  source      = "../../modules/artifact_registry"
  project_id  = var.project_id
  region      = var.region
  name_prefix = local.name_prefix
}

module "wif" {
  source            = "../../modules/wif"
  project_id        = var.project_id
  project_number    = var.project_number
  name_prefix       = local.name_prefix
  github_repository = var.github_repository
  allowed_ref       = "refs/heads/main"
  impersonatable_service_accounts = [
    google_service_account.api.email,
    google_service_account.worker.email,
  ]
}

module "storage" {
  source        = "../../modules/storage"
  project_id    = var.project_id
  region        = var.region
  name_prefix   = local.name_prefix
  force_destroy = false
}

module "secrets" {
  source      = "../../modules/secrets"
  project_id  = var.project_id
  name_prefix = local.name_prefix
  accessor_members = [
    "serviceAccount:${google_service_account.api.email}",
    "serviceAccount:${google_service_account.worker.email}",
  ]
}

module "database" {
  source                 = "../../modules/database"
  project_id             = var.project_id
  region                 = var.region
  name_prefix            = local.name_prefix
  network_id             = module.network.network_id
  private_vpc_connection = module.network.private_vpc_connection
  app_user_password      = var.db_app_user_password
  deletion_protection    = true
  tier                   = "db-custom-2-7680"
}

module "redis" {
  source         = "../../modules/redis"
  project_id     = var.project_id
  region         = var.region
  name_prefix    = local.name_prefix
  network_id     = module.network.network_id
  tier           = "STANDARD_HA"
  memory_size_gb = 2
}

resource "google_service_account" "api" {
  project      = var.project_id
  account_id   = "${local.name_prefix}-api"
  display_name = "Crucible API (production)"
}

resource "google_service_account" "worker" {
  project      = var.project_id
  account_id   = "${local.name_prefix}-worker"
  display_name = "Crucible worker (production)"
}

resource "google_storage_bucket_iam_member" "api_datasets" {
  bucket = module.storage.datasets_bucket
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.api.email}"
}
resource "google_storage_bucket_iam_member" "worker_datasets" {
  bucket = module.storage.datasets_bucket
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.worker.email}"
}
resource "google_project_iam_member" "api_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.api.email}"
}
resource "google_project_iam_member" "worker_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

module "api" {
  source                = "../../modules/cloud_run_service"
  project_id            = var.project_id
  region                = var.region
  name                  = "${local.name_prefix}-api"
  image                 = var.api_image
  service_account_email = google_service_account.api.email
  vpc_connector_id      = module.network.connector_id
  ingress               = "INGRESS_TRAFFIC_ALL"
  allow_unauthenticated = true
  min_instances         = 2
  max_instances         = 10
  env = {
    CRUCIBLE_PROFILE = "production"
    GIT_SHA          = var.git_sha
    S3_BUCKET        = module.storage.datasets_bucket
  }
  secret_env = {
    CRUCIBLE_DATABASE_URL = { secret = module.secrets.secret_ids["database-url"], version = "latest" }
    CRUCIBLE_REDIS_URL    = { secret = module.secrets.secret_ids["redis-url"], version = "latest" }
  }
}

# Public edge (Phase 10): Cloud Armor WAF + global HTTPS LB + managed TLS in
# front of the API. Users reach the domain, never the raw Cloud Run URL.
module "waf" {
  source      = "../../modules/waf"
  project_id  = var.project_id
  name_prefix = local.name_prefix
}

module "https_lb" {
  source             = "../../modules/https_lb"
  project_id         = var.project_id
  region             = var.region
  name_prefix        = local.name_prefix
  domain             = var.api_domain
  cloud_run_service  = module.api.service_name
  security_policy_id = module.waf.security_policy_id
}

module "worker" {
  source                = "../../modules/cloud_run_service"
  project_id            = var.project_id
  region                = var.region
  name                  = "${local.name_prefix}-worker"
  image                 = var.worker_image
  service_account_email = google_service_account.worker.email
  vpc_connector_id      = module.network.connector_id
  ingress               = "INGRESS_TRAFFIC_INTERNAL_ONLY"
  allow_unauthenticated = false
  min_instances         = 2
  max_instances         = 8
  env = {
    CRUCIBLE_PROFILE = "production"
    GIT_SHA          = var.git_sha
    EXECUTOR_BACKEND = "microvm"
  }
  secret_env = {
    CRUCIBLE_DATABASE_URL = { secret = module.secrets.secret_ids["database-url"], version = "latest" }
    CRUCIBLE_REDIS_URL    = { secret = module.secrets.secret_ids["redis-url"], version = "latest" }
  }
}
