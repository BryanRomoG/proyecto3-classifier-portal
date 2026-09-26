# Network layer: VPC across 2 AZs with public + private subnets.
#
# No NAT gateway here on purpose — nothing in the private subnets needs
# outbound internet access yet (RDS and the future ECS task talk to AWS
# services, which OPS-08 reaches via a VPC S3 Gateway Endpoint instead of
# NAT, per the architecture doc). Add a NAT gateway only if a real workload
# ends up needing arbitrary internet egress from the private subnets.

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = merge(var.tags, {
    Name        = "dataset-quality-${var.environment}-vpc"
    Environment = var.environment
  })
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, {
    Name        = "dataset-quality-${var.environment}-igw"
    Environment = var.environment
  })
}

resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.this.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true

  tags = merge(var.tags, {
    Name        = "dataset-quality-${var.environment}-public-${local.azs[count.index]}"
    Environment = var.environment
    Tier        = "public"
  })
}

resource "aws_subnet" "private" {
  count             = length(var.private_subnet_cidrs)
  vpc_id            = aws_vpc.this.id
  cidr_block        = var.private_subnet_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = merge(var.tags, {
    Name        = "dataset-quality-${var.environment}-private-${local.azs[count.index]}"
    Environment = var.environment
    Tier        = "private"
  })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = merge(var.tags, {
    Name        = "dataset-quality-${var.environment}-public-rt"
    Environment = var.environment
  })
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Private route table has no default route yet (no NAT) — it exists so
# OPS-08 can attach the S3 Gateway Endpoint's route without restructuring
# this module.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  tags = merge(var.tags, {
    Name        = "dataset-quality-${var.environment}-private-rt"
    Environment = var.environment
  })
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# Lets resources in the private subnets reach S3 without a NAT gateway (which
# this network deliberately doesn't have) and without the traffic leaving
# AWS's network at all — the OPS-08 requirement this module was built to
# support (see private_route_table_id's docstring in outputs.tf).
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = merge(var.tags, {
    Name        = "dataset-quality-${var.environment}-s3-endpoint"
    Environment = var.environment
  })
}
