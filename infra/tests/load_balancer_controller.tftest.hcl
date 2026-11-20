mock_provider "aws" {}

override_resource {
  override_during = plan
  target          = aws_lb_target_group.backend
  values = {
    arn = "arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/backend/1234567890abcdef"
  }
}

variables {
  environment      = "local"
  local_validation = true
  aws_region       = "us-east-1"
}

run "controller_target_permissions" {
  command = plan
  assert {
    condition = (
      length(aws_iam_user.load_balancer_controller_local) == 1 &&
      jsondecode(aws_iam_user_policy.load_balancer_controller_local[0].policy).Statement[1].Resource == "arn:aws:elasticloadbalancing:us-east-1:000000000000:targetgroup/backend/1234567890abcdef" &&
      toset(jsondecode(aws_iam_user_policy.load_balancer_controller_local[0].policy).Statement[1].Action) == toset(["elasticloadbalancing:RegisterTargets", "elasticloadbalancing:DeregisterTargets"])
    )
    error_message = "Local controller writes must be limited to registering/deregistering the backend target group."
  }
  assert {
    condition     = !contains(flatten([for statement in jsondecode(aws_iam_user_policy.load_balancer_controller_local[0].policy).Statement : statement.Action]), "elasticloadbalancing:CreateLoadBalancer")
    error_message = "The target controller must not be able to create another ALB."
  }
}

run "no_static_controller_in_aws" {
  command = plan
  variables {
    environment      = "prod"
    local_validation = false
  }
  assert {
    condition     = length(aws_iam_user.load_balancer_controller_local) == 0 && length(aws_iam_user_policy.load_balancer_controller_local) == 0
    error_message = "Production must not create the local static-key controller user."
  }
}
