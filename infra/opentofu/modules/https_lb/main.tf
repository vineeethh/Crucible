# Global external HTTPS load balancer fronting the API Cloud Run service, with
# a Google-managed TLS certificate and the Cloud Armor policy attached (master
# plan Phase 10: domain / TLS / WAF). HTTP is redirected to HTTPS.

variable "project_id" { type = string }
variable "region" { type = string }
variable "name_prefix" { type = string }
variable "domain" {
  type        = string
  description = "The public hostname (e.g. api.crucible.example). A managed cert is issued for it."
}
variable "cloud_run_service" {
  type        = string
  description = "Name of the API Cloud Run service to route to."
}
variable "security_policy_id" { type = string }

# Serverless NEG pointing at the Cloud Run service.
resource "google_compute_region_network_endpoint_group" "api" {
  project               = var.project_id
  name                  = "${var.name_prefix}-api-neg"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run { service = var.cloud_run_service }
}

resource "google_compute_backend_service" "api" {
  project               = var.project_id
  name                  = "${var.name_prefix}-api-backend"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"
  security_policy       = var.security_policy_id

  backend {
    group = google_compute_region_network_endpoint_group.api.id
  }
  log_config {
    enable      = true
    sample_rate = 1.0
  }
}

resource "google_compute_url_map" "api" {
  project         = var.project_id
  name            = "${var.name_prefix}-api-urlmap"
  default_service = google_compute_backend_service.api.id
}

resource "google_compute_managed_ssl_certificate" "api" {
  project = var.project_id
  name    = "${var.name_prefix}-api-cert"
  managed { domains = [var.domain] }
}

resource "google_compute_target_https_proxy" "api" {
  project          = var.project_id
  name             = "${var.name_prefix}-api-https"
  url_map          = google_compute_url_map.api.id
  ssl_certificates = [google_compute_managed_ssl_certificate.api.id]
}

resource "google_compute_global_address" "api" {
  project = var.project_id
  name    = "${var.name_prefix}-api-ip"
}

resource "google_compute_global_forwarding_rule" "https" {
  project               = var.project_id
  name                  = "${var.name_prefix}-api-https-fr"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  target                = google_compute_target_https_proxy.api.id
  ip_address            = google_compute_global_address.api.id
  port_range            = "443"
}

# HTTP → HTTPS redirect so no plaintext ever serves.
resource "google_compute_url_map" "redirect" {
  project = var.project_id
  name    = "${var.name_prefix}-api-redirect"
  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "redirect" {
  project = var.project_id
  name    = "${var.name_prefix}-api-http"
  url_map = google_compute_url_map.redirect.id
}

resource "google_compute_global_forwarding_rule" "http" {
  project               = var.project_id
  name                  = "${var.name_prefix}-api-http-fr"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  target                = google_compute_target_http_proxy.redirect.id
  ip_address            = google_compute_global_address.api.id
  port_range            = "80"
}

output "public_ip" { value = google_compute_global_address.api.address }
output "domain" { value = var.domain }
