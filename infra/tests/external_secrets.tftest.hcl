mock_provider "aws" {}

variables {
  environment      = "local"
  local_validation = true
  aws_region       = "us-east-1"
}

run "local_reader_identity" {
  command = plan
  assert {
    condition     = length(aws_iam_user.external_secrets_local) == 1 && aws_iam_user.external_secrets_local[0].name == "book-ninja-local-external-secrets"
    error_message = "The emulator must have a dedicated reader identity."
  }
}

run "no_static_reader_in_aws" {
  command = plan
  variables {
    environment      = "prod"
    local_validation = false
  }
  assert {
    condition     = length(aws_iam_user.external_secrets_local) == 0 && length(aws_iam_user_policy.external_secrets_local) == 0
    error_message = "The local static-key accommodation must not be provisioned in AWS."
  }
}
