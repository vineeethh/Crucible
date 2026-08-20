output "api_url" { value = module.api.uri }
output "worker_service" { value = module.worker.service_name }
output "registry_url" { value = module.artifact_registry.repository_url }
output "wif_provider" { value = module.wif.provider_name }
output "deployer_sa" { value = module.wif.deployer_sa_email }
output "db_connection_name" { value = module.database.instance_connection_name }
output "public_ip" { value = module.https_lb.public_ip }
output "api_domain" { value = module.https_lb.domain }
