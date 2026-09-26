# Compute layer: the ECS Fargate cluster the quality gate runs on, and the
# task execution role every task definition will need.
#
# No task definition or service here yet — OPS-08 adds those once there's
# an actual container image (built from pipeline/Dockerfile) to run.

resource "aws_ecs_cluster" "this" {
  name = "dataset-quality-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = merge(var.tags, {
    Environment = var.environment
  })
}

data "aws_iam_policy_document" "ecs_tasks_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task_execution" {
  name               = "dataset-quality-${var.environment}-ecs-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume_role.json

  tags = merge(var.tags, {
    Environment = var.environment
  })
}

# Standard managed policy for pulling images and writing logs — the minimum
# a task execution role needs regardless of what the task itself does.
resource "aws_iam_role_policy_attachment" "task_execution_managed" {
  role       = aws_iam_role.task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}
