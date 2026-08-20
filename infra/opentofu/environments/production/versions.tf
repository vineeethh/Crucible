terraform {
  required_version = ">= 1.7.0" # OpenTofu >= 1.7

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Remote state with locking. The bucket is created out-of-band (bootstrap) so
  # state never lives on a developer's laptop. Access is restricted to the
  # deployer identity and break-glass admins.
  backend "gcs" {
    prefix = "crucible/production"
    # bucket = "..." supplied via `-backend-config` at init time.
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
