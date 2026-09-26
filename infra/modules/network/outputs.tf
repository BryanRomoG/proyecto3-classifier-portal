output "vpc_id" {
  value = aws_vpc.this.id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "private_route_table_id" {
  description = "The route table the S3 Gateway Endpoint below is attached to."
  value       = aws_route_table.private.id
}

output "s3_endpoint_id" {
  value = aws_vpc_endpoint.s3.id
}
