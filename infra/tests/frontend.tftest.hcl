mock_provider "aws" {}

variables {
  environment      = "local"
  local_validation = true
  aws_region       = "us-east-1"
}

run "private_frontend" {
  command = plan
  assert {
    condition     = aws_s3_bucket_public_access_block.frontend.block_public_acls && aws_s3_bucket_public_access_block.frontend.block_public_policy && aws_s3_bucket_public_access_block.frontend.restrict_public_buckets && aws_s3_bucket_public_access_block.frontend.ignore_public_acls
    error_message = "All public bucket access must be blocked."
  }
  assert {
    condition     = aws_cloudfront_origin_access_control.frontend.signing_behavior == "always"
    error_message = "CloudFront must sign S3 origin requests."
  }
  assert {
    condition     = aws_s3_bucket_versioning.frontend.versioning_configuration[0].status == "Enabled"
    error_message = "Frontend object versioning must be enabled."
  }
  assert {
    condition     = aws_secretsmanager_secret.backend.recovery_window_in_days == 7
    error_message = "Runtime secret metadata must have a recovery window."
  }
}

run "aws_https" {
  command = plan
  variables {
    environment      = "prod"
    local_validation = false
  }
  assert {
    condition     = aws_cloudfront_distribution.frontend.default_cache_behavior[0].viewer_protocol_policy == "redirect-to-https"
    error_message = "AWS viewer traffic must redirect to HTTPS."
  }
}
