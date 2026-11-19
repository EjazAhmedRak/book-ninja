# Static credentials are a local emulator accommodation. AWS workload identity
# must be configured separately; no IAM access keys are managed in Terraform.
resource "aws_iam_user" "external_secrets_local" {
  count = var.local_validation ? 1 : 0
  name  = "${local.name_prefix}-external-secrets"
  tags  = local.common_tags
}

resource "aws_iam_user_policy" "external_secrets_local" {
  count = var.local_validation ? 1 : 0
  name  = "ReadBackendRuntime"
  user  = aws_iam_user.external_secrets_local[0].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      Resource = aws_secretsmanager_secret.backend.arn
    }]
  })
}
