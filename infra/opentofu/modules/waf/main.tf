# Cloud Armor security policy (WAF) for the public edge (master plan Phase 10).
# Attached to the HTTPS load balancer's backend. Provides per-IP rate limiting
# and the preconfigured OWASP rules for the highest-signal injection classes.
# The application's own defenses (RBAC, sandbox, redaction) are the real
# controls; this is edge defense in depth (threat T6).

variable "project_id" { type = string }
variable "name_prefix" { type = string }
variable "rate_limit_per_minute" {
  type    = number
  default = 600 # per client IP; app-level per-tenant limits are separate
}

resource "google_compute_security_policy" "edge" {
  project = var.project_id
  name    = "${var.name_prefix}-edge"

  # Default: allow (rules below deny/throttle specific traffic).
  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    description = "default allow"
  }

  # Per-IP rate limit: throttle abusive sources before they reach Cloud Run.
  rule {
    action   = "throttle"
    priority = 1000
    match {
      versioned_expr = "SRC_IPS_V1"
      config { src_ip_ranges = ["*"] }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = var.rate_limit_per_minute
        interval_sec = 60
      }
    }
    description = "per-IP rate limit"
  }

  # Preconfigured WAF rules for the highest-value injection classes.
  rule {
    action   = "deny(403)"
    priority = 900
    match {
      expr { expression = "evaluatePreconfiguredExpr('sqli-v33-stable')" }
    }
    description = "OWASP SQLi"
  }
  rule {
    action   = "deny(403)"
    priority = 901
    match {
      expr { expression = "evaluatePreconfiguredExpr('xss-v33-stable')" }
    }
    description = "OWASP XSS"
  }
  rule {
    action   = "deny(403)"
    priority = 902
    match {
      expr { expression = "evaluatePreconfiguredExpr('lfi-v33-stable')" }
    }
    description = "OWASP local-file-inclusion"
  }

  # Block the Log4Shell JNDI lookup pattern (CVE-2021-44228, CKV_GCP_73).
  rule {
    action   = "deny(403)"
    priority = 903
    match {
      expr { expression = "evaluatePreconfiguredExpr('cve-canary')" }
    }
    description = "Log4Shell / JNDI lookup (CVE-2021-44228)"
  }

  adaptive_protection_config {
    layer_7_ddos_defense_config { enable = true }
  }
}

output "security_policy_id" { value = google_compute_security_policy.edge.id }
