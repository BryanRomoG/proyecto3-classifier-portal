output "github_oidc_role_arn" {
  value = module.github_oidc.role_arn
}

output "vpc_id" {
  value = module.network.vpc_id
}

output "db_instance_endpoint" {
  value = module.data.db_instance_endpoint
}

output "classifier_portal_role_arn" {
  description = "ARN of the Project 3 GitHub Actions OIDC role (github-actions-classifier-portal). Register this in the Project 3 repo as the Actions variable AWS_ROLE_ARN."
  value       = aws_iam_role.classifier_portal.arn
}
