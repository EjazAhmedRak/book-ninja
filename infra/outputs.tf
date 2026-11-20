output "environment" {
  description = "Environment managed by this state."
  value       = var.environment
}

output "frontend_bucket_name" {
  value = aws_s3_bucket.frontend.id
}

output "frontend_distribution_id" {
  value = aws_cloudfront_distribution.frontend.id
}

output "frontend_url" {
  description = "Local HTTP delivery for Floci; HTTPS CloudFront domain in AWS."
  value       = var.local_validation ? "http://${lower(aws_cloudfront_distribution.frontend.id)}.cloudfront.localhost.floci.io:4566/" : "https://${aws_cloudfront_distribution.frontend.domain_name}"
}

output "backend_secret_arn" {
  value = aws_secretsmanager_secret.backend.arn
}

output "api_foundation" {
  description = "Private API foundation only; no deployed API stage or application targets yet."
  value = {
    rest_api_id      = aws_api_gateway_rest_api.backend.id
    vpc_link_id      = aws_apigatewayv2_vpc_link.backend.id
    alb_arn          = aws_lb.backend.arn
    alb_dns_name     = aws_lb.backend.dns_name
    listener_arn     = aws_lb_listener.backend.arn
    target_group_arn = aws_lb_target_group.backend.arn
  }
}

output "cluster_name" {
  value = aws_eks_cluster.main.name
}

output "backend_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "public_subnet_ids" {
  value = aws_subnet.public[*].id
}

output "nat_public_ips" {
  description = "AWS NAT egress IPs for MongoDB allowlisting; Floci addresses are emulated."
  value       = aws_eip.nat[*].public_ip
}

output "security_group_ids" {
  value = {
    vpc_link = aws_security_group.vpc_link.id
    alb      = aws_security_group.alb.id
    backend  = aws_security_group.backend.id
  }
}
