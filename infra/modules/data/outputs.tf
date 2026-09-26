output "db_instance_endpoint" {
  value = aws_db_instance.this.endpoint
}

output "db_instance_identifier" {
  value = aws_db_instance.this.identifier
}

output "master_user_secret_arn" {
  description = "Secrets Manager secret ARN holding the RDS master credentials."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "security_group_id" {
  value = aws_security_group.rds.id
}
