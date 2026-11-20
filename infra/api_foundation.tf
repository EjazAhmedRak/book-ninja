# Terraform owns the load balancer and target group. Future Kubernetes target
# registration must use TargetGroupBinding rather than also creating this ALB
# through an Ingress. No application targets or API integrations are created yet.
resource "aws_lb" "backend" {
  name_prefix                = "bnapi-"
  internal                   = true
  load_balancer_type         = "application"
  subnets                    = aws_subnet.private[*].id
  security_groups            = [aws_security_group.alb.id]
  idle_timeout               = 300
  enable_deletion_protection = !var.local_validation && var.environment == "prod"
  tags                       = merge(local.common_tags, { Name = "${local.name_prefix}-api" })
}

resource "aws_lb_target_group" "backend" {
  name_prefix          = "bnapi-"
  vpc_id               = aws_vpc.main.id
  protocol             = "HTTP"
  port                 = 8000
  target_type          = "ip"
  deregistration_delay = 60
  health_check {
    enabled             = true
    protocol            = "HTTP"
    path                = "/livez"
    port                = "traffic-port"
    matcher             = "200"
    healthy_threshold   = 2
    unhealthy_threshold = 2
    interval            = 15
    timeout             = 5
  }
  tags = local.common_tags
}

resource "aws_lb_listener" "backend" {
  load_balancer_arn = aws_lb.backend.arn
  protocol          = "HTTP"
  port              = 80
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }
  tags = local.common_tags
}

# V2 is the VPC-link generation, not a choice of HTTP API. AWS REST APIs also
# support V2 links with ALBs. Binding the streaming REST integration is separate.
resource "aws_apigatewayv2_vpc_link" "backend" {
  name               = "${local.name_prefix}-api"
  subnet_ids         = aws_subnet.private[*].id
  security_group_ids = [aws_security_group.vpc_link.id]
  tags               = local.common_tags
}

resource "aws_api_gateway_rest_api" "backend" {
  name        = "${local.name_prefix}-api"
  description = "Regional streaming API foundation; routes/integrations require separate validation"
  endpoint_configuration {
    types = ["REGIONAL"]
  }
  tags = local.common_tags
}
