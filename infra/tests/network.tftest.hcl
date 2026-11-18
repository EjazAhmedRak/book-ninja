mock_provider "aws" {}

variables {
  environment      = "local"
  local_validation = true
  aws_region       = "us-east-1"
}

run "local_private_network" {
  command = plan

  assert {
    condition     = length(aws_subnet.private) == 2 && length(aws_subnet.public) == 2
    error_message = "The network must span two public/private subnet pairs."
  }
  assert {
    condition     = alltrue([for subnet in aws_subnet.private : !subnet.map_public_ip_on_launch])
    error_message = "Private subnets must never assign public IPs."
  }
  assert {
    condition     = length(aws_nat_gateway.main) == 1
    error_message = "Local validation uses one emulated NAT gateway."
  }
  assert {
    condition     = aws_subnet.public[0].cidr_block == "10.60.0.0/20" && aws_subnet.private[0].cidr_block == "10.60.128.0/20"
    error_message = "Public and private CIDRs must use distinct ranges."
  }
  assert {
    condition     = aws_security_group_rule.backend_from_alb.from_port == 8000 && aws_security_group_rule.backend_from_alb.cidr_blocks == null
    error_message = "Backend ingress must be security-group based and restricted to port 8000."
  }
}

run "aws_az_resilience" {
  command = plan
  variables {
    environment      = "prod"
    local_validation = false
  }
  assert {
    condition     = length(aws_nat_gateway.main) == 2
    error_message = "AWS environments require independent NAT gateways in both AZs."
  }
  assert {
    condition     = !aws_eks_cluster.main.vpc_config[0].endpoint_public_access && aws_eks_cluster.main.vpc_config[0].endpoint_private_access
    error_message = "Real AWS cluster APIs must remain private."
  }
  assert {
    condition     = aws_eks_node_group.main.scaling_config[0].min_size == 2 && aws_ecr_repository.backend.image_tag_mutability == "IMMUTABLE"
    error_message = "AWS requires at least two workers and immutable backend tags."
  }
}

run "reject_duplicate_zones" {
  command = plan
  variables {
    availability_zones = ["us-east-1a", "us-east-1a"]
  }
  expect_failures = [var.availability_zones]
}

run "reject_small_cidr" {
  command = plan
  variables {
    vpc_cidr = "10.42.0.0/28"
  }
  expect_failures = [var.vpc_cidr]
}

run "reject_k3s_overlap" {
  command = plan
  variables {
    vpc_cidr = "10.42.0.0/16"
  }
  expect_failures = [aws_vpc.main]
}
