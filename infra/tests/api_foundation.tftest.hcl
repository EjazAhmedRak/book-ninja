mock_provider "aws" {}

override_resource {
  override_during = plan
  target          = aws_subnet.private[0]
  values          = { id = "subnet-private-a" }
}
override_resource {
  override_during = plan
  target          = aws_subnet.private[1]
  values          = { id = "subnet-private-b" }
}
override_resource {
  override_during = plan
  target          = aws_security_group.alb
  values          = { id = "sg-private-alb" }
}
override_resource {
  override_during = plan
  target          = aws_security_group.vpc_link
  values          = { id = "sg-private-link" }
}

variables {
  environment      = "local"
  local_validation = true
  aws_region       = "us-east-1"
}

run "private_api_foundation" {
  command = plan
  assert {
    condition     = aws_lb.backend.internal && aws_lb.backend.load_balancer_type == "application" && aws_lb.backend.subnets == toset(["subnet-private-a", "subnet-private-b"])
    error_message = "The ALB must be internal and use only the two private subnets."
  }
  assert {
    condition     = aws_lb.backend.security_groups == toset(["sg-private-alb"]) && aws_apigatewayv2_vpc_link.backend.security_group_ids == toset(["sg-private-link"])
    error_message = "ALB and VPC Link must use their separate restricted security groups."
  }
  assert {
    condition     = aws_apigatewayv2_vpc_link.backend.subnet_ids == toset(["subnet-private-a", "subnet-private-b"])
    error_message = "VPC Link ENIs must stay in private subnets."
  }
  assert {
    condition     = aws_lb_target_group.backend.target_type == "ip" && aws_lb_target_group.backend.port == 8000 && aws_lb_target_group.backend.health_check[0].path == "/livez"
    error_message = "Targets must be pod-compatible IPs on port 8000 with lightweight health checks."
  }
  assert {
    condition     = contains(aws_api_gateway_rest_api.backend.endpoint_configuration[0].types, "REGIONAL") && length(aws_api_gateway_rest_api.backend.endpoint_configuration[0].types) == 1 && aws_lb_listener.backend.port == 80 && aws_lb.backend.idle_timeout == 300
    error_message = "Use a Regional REST API foundation and private HTTP listener with an explicit idle timeout."
  }
}

run "production_deletion_protection" {
  command = plan
  variables {
    environment      = "prod"
    local_validation = false
  }
  assert {
    condition     = aws_lb.backend.enable_deletion_protection
    error_message = "Production ALBs require deletion protection."
  }
}
