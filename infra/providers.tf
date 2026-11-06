provider "aws" {
  region = var.aws_region

  # Floci's AWS-compatible endpoint requires throwaway credentials. Leave these
  # unset for AWS so the provider uses the normal AWS credential chain.
  access_key = var.local_validation ? var.local_aws_access_key : null
  secret_key = var.local_validation ? var.local_aws_secret_key : null

  skip_credentials_validation = var.local_validation
  skip_metadata_api_check     = var.local_validation
  skip_requesting_account_id  = var.local_validation
  s3_use_path_style           = var.local_validation

  dynamic "endpoints" {
    for_each = var.local_validation ? [var.floci_endpoint] : []

    content {
      acm            = endpoints.value
      apigateway     = endpoints.value
      cloudwatch     = endpoints.value
      dynamodb       = endpoints.value
      ec2            = endpoints.value
      ecr            = endpoints.value
      eks            = endpoints.value
      elbv2          = endpoints.value
      iam            = endpoints.value
      logs           = endpoints.value
      route53        = endpoints.value
      s3             = endpoints.value
      secretsmanager = endpoints.value
      sts            = endpoints.value
      wafv2          = endpoints.value
    }
  }
}
