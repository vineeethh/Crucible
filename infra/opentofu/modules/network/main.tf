# Private networking: a VPC with a Serverless VPC Access connector so Cloud Run
# reaches Cloud SQL and Memorystore over private IP, plus a Private Service
# Access range for the managed services. No public database endpoints (T5/T6).

variable "project_id" { type = string }
variable "region" { type = string }
variable "name_prefix" { type = string }
variable "connector_cidr" {
  type    = string
  default = "10.8.0.0/28" # /28 is the required size for a VPC connector
}

resource "google_compute_network" "vpc" {
  project                 = var.project_id
  name                    = "${var.name_prefix}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "primary" {
  project       = var.project_id
  name          = "${var.name_prefix}-subnet"
  region        = var.region
  network       = google_compute_network.vpc.id
  ip_cidr_range = "10.0.0.0/20"

  # Flow logs are cheap evidence for an incident review.
  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
  private_ip_google_access = true
}

resource "google_vpc_access_connector" "connector" {
  project       = var.project_id
  name          = "${var.name_prefix}-vpcconn"
  region        = var.region
  network       = google_compute_network.vpc.name
  ip_cidr_range = var.connector_cidr
  min_instances = 2
  max_instances = 3
}

# Reserved range Google's managed services peer into (Cloud SQL private IP).
resource "google_compute_global_address" "private_services" {
  project       = var.project_id
  name          = "${var.name_prefix}-psa"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

# Explicit, default-deny firewall (never rely on the implied default rules,
# CKV2_GCP_18). Ingress is denied; egress to Google APIs / the private ranges is
# what the workloads use, which the private connectivity above provides.
resource "google_compute_firewall" "deny_all_ingress" {
  project       = var.project_id
  name          = "${var.name_prefix}-deny-ingress"
  network       = google_compute_network.vpc.name
  direction     = "INGRESS"
  priority      = 65534
  source_ranges = ["0.0.0.0/0"]
  deny { protocol = "all" }
  log_config { metadata = "INCLUDE_ALL_METADATA" }
}

# Allow internal traffic within the subnet (Cloud Run connector → managed
# services over private IP).
resource "google_compute_firewall" "allow_internal" {
  project       = var.project_id
  name          = "${var.name_prefix}-allow-internal"
  network       = google_compute_network.vpc.name
  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["10.0.0.0/8"]
  allow { protocol = "tcp" }
  allow { protocol = "udp" }
  allow { protocol = "icmp" }
  log_config { metadata = "INCLUDE_ALL_METADATA" }
}

output "network_id" { value = google_compute_network.vpc.id }
output "network_name" { value = google_compute_network.vpc.name }
output "connector_id" { value = google_vpc_access_connector.connector.id }
output "private_vpc_connection" { value = google_service_networking_connection.private_services.id }
