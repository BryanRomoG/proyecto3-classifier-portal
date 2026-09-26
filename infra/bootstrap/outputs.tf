output "tfstate_bucket_name" {
  value = module.tfstate.bucket_id
}

output "tflock_table_name" {
  value = aws_dynamodb_table.tflock.name
}
