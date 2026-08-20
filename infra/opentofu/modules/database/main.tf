# Cloud SQL for PostgreSQL, private IP only, with automated backups and
# point-in-time recovery. Deletion protection is on by default; the DR drill
# (docs/operations/disaster-recovery.md) restores from these backups.

variable "project_id" { type = string }
variable "region" { type = string }
variable "name_prefix" { type = string }
variable "network_id" { type = string }
variable "private_vpc_connection" { type = string }
variable "tier" {
  type    = string
  default = "db-custom-1-3840"
}
variable "deletion_protection" {
  type    = bool
  default = true
}
variable "database_name" {
  type    = string
  default = "crucible"
}

resource "google_sql_database_instance" "main" {
  # checkov:skip=CKV_GCP_79:POSTGRES_17 is the current major version; checkov's
  # "latest" list lags releases.
  # checkov:skip=CKV_GCP_6:ssl_mode=ENCRYPTED_ONLY (below) is the modern
  # equivalent of the deprecated require_ssl flag checkov still looks for.
  # checkov:skip=CKV_GCP_109:log_min_messages is set to 'error' below.
  project             = var.project_id
  name                = "${var.name_prefix}-pg"
  region              = var.region
  database_version    = "POSTGRES_17"
  deletion_protection = var.deletion_protection
  # The private-services peering must exist before the instance can take a
  # private IP; the environment wires this dependency explicitly.
  depends_on = [var.private_vpc_connection]

  settings {
    tier              = var.tier
    availability_type = "REGIONAL" # synchronous standby: survives a zone loss
    disk_autoresize   = true

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "03:00"
      transaction_log_retention_days = 7
      backup_retention_settings { retained_backups = 30 }
    }

    ip_configuration {
      ipv4_enabled    = false # no public IP
      private_network = var.network_id
      ssl_mode        = "ENCRYPTED_ONLY" # reject non-TLS connections (CKV_GCP_6)
    }

    # Security-relevant logging: connections, disconnections, checkpoints, lock
    # waits, hostnames, statements, and pgAudit — an incident review needs them
    # (CKV_GCP_51/52/53/54/108/109/110/111, CKV2_GCP_13).
    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }
    database_flags {
      name  = "log_checkpoints"
      value = "on"
    }
    database_flags {
      name  = "log_connections"
      value = "on"
    }
    database_flags {
      name  = "log_disconnections"
      value = "on"
    }
    database_flags {
      name  = "log_lock_waits"
      value = "on"
    }
    database_flags {
      name  = "log_hostname"
      value = "on"
    }
    database_flags {
      name  = "log_duration"
      value = "on"
    }
    database_flags {
      name  = "log_statement"
      value = "ddl"
    }
    database_flags {
      name  = "log_min_messages"
      value = "error"
    }
    database_flags {
      name  = "cloudsql.enable_pgaudit"
      value = "on"
    }
    insights_config { query_insights_enabled = true }
  }
}

resource "google_sql_database" "crucible" {
  project  = var.project_id
  name     = var.database_name
  instance = google_sql_database_instance.main.name
}

# The application user's password lives in Secret Manager; Terraform reads it
# from a variable sourced from there, never generating or printing it in plan.
variable "app_user_password" {
  type      = string
  sensitive = true
}

resource "google_sql_user" "app" {
  project  = var.project_id
  name     = "crucible_app"
  instance = google_sql_database_instance.main.name
  password = var.app_user_password
}

output "instance_connection_name" { value = google_sql_database_instance.main.connection_name }
output "private_ip" { value = google_sql_database_instance.main.private_ip_address }
