# Static credentials are restricted to local emulation. Production workload
# identity and its IAM role must be configured independently.
resource "aws_iam_user" "load_balancer_controller_local" {
  count = var.local_validation ? 1 : 0
  name  = "${local.name_prefix}-load-balancer-controller"
  tags  = local.common_tags
}

resource "aws_iam_user_policy" "load_balancer_controller_local" {
  count = var.local_validation ? 1 : 0
  name  = "ReconcileBackendTargets"
  user  = aws_iam_user.load_balancer_controller_local[0].name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["elasticloadbalancing:DescribeTargetGroups", "elasticloadbalancing:DescribeTargetHealth",
        "elasticloadbalancing:DescribeTargetGroupAttributes", "elasticloadbalancing:DescribeLoadBalancers",
      "elasticloadbalancing:DescribeListeners", "elasticloadbalancing:DescribeRules"]
      Resource = "*"
      }, {
      Effect   = "Allow"
      Action   = ["elasticloadbalancing:RegisterTargets", "elasticloadbalancing:DeregisterTargets"]
      Resource = aws_lb_target_group.backend.arn
      }, {
      Effect = "Allow"
      Action = ["ec2:DescribeVpcs", "ec2:DescribeSubnets", "ec2:DescribeInstances",
      "ec2:DescribeNetworkInterfaces", "ec2:DescribeSecurityGroups", "ec2:DescribeTags", "sts:GetCallerIdentity"]
      Resource = "*"
    }]
  })
}
