# Memorystore for Redis (the arq job queue + rate limiter). Private, on the
# same VPC. AUTH + in-transit encryption on; a queue loss is survivable (the
# queue-loss game day proves redelivery/idempotency), so a single node is
# acceptable for staging and STANDARD_HA for production.

variable "project_id" { type = string }
variable "region" { type = string }
variable "name_prefix" { type = string }
variable "network_id" { type = string }
variable "tier" {
  type    = string
  default = "STANDARD_HA"
}
variable "memory_size_gb" {
  type    = number
  default = 1
}

resource "google_redis_instance" "queue" {
  project            = var.project_id
  name               = "${var.name_prefix}-redis"
  region             = var.region
  tier               = var.tier
  memory_size_gb     = var.memory_size_gb
  authorized_network = var.network_id
  connect_mode       = "PRIVATE_SERVICE_ACCESS"

  auth_enabled            = true
  transit_encryption_mode = "SERVER_AUTHENTICATION"
  redis_version           = "REDIS_7_2"
}

output "host" { value = google_redis_instance.queue.host }
output "port" { value = google_redis_instance.queue.port }
