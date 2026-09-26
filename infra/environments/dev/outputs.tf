output "github_oidc_role_arn" {
  value = module.github_oidc.role_arn
}

output "vpc_id" {
  value = module.network.vpc_id
}

output "db_instance_endpoint" {
  value = module.data.db_instance_endpoint
}
