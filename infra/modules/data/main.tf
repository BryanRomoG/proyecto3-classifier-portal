# Data layer: RDS MariaDB, in the private subnets, with its master
# credentials managed by RDS's native Secrets Manager integration rather
# than a hand-rolled secret — one less place for a password to leak into
# state or a variable file.

resource "aws_db_subnet_group" "this" {
  name       = "dataset-quality-${var.environment}-db"
  subnet_ids = var.private_subnet_ids

  tags = merge(var.tags, {
    Environment = var.environment
  })
}

resource "aws_security_group" "rds" {
  name        = "dataset-quality-${var.environment}-rds"
  description = "Allow MariaDB access from within the VPC only."
  vpc_id      = var.vpc_id

  ingress {
    description = "MariaDB from the VPC"
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, {
    Environment = var.environment
  })
}

resource "aws_db_instance" "this" {
  identifier     = "dataset-quality-${var.environment}"
  engine         = "mariadb"
  engine_version = var.engine_version
  instance_class = var.instance_class

  allocated_storage = var.allocated_storage_gb
  db_name           = var.db_name
  username          = var.db_username

  # RDS creates and rotates the master password in Secrets Manager itself —
  # this is what satisfies "Secrets Manager configuration exists" here.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  multi_az                  = var.multi_az
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "dataset-quality-${var.environment}-final"

  tags = merge(var.tags, {
    Environment = var.environment
  })
}
