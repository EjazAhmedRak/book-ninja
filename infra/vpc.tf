locals {
  zones = length(var.availability_zones) == 0 ? ["${var.aws_region}a", "${var.aws_region}b"] : var.availability_zones
  # AWS environments use one NAT per AZ; local emulation needs only one.
  nat_count = var.local_validation ? 1 : 2
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(local.common_tags, { Name = local.name_prefix })

  lifecycle {
    precondition {
      condition     = !var.local_validation || (!startswith(var.vpc_cidr, "10.42.") && !startswith(var.vpc_cidr, "10.100."))
      error_message = "Floci VPC ranges must not overlap k3s pod (10.42/16) or service (10.100/16) networks."
    }
  }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.zones[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, count.index)
  map_public_ip_on_launch = false
  tags = merge(local.common_tags, {
    Name                     = "${local.name_prefix}-public-${count.index + 1}"
    "kubernetes.io/role/elb" = "1"
  })
}

resource "aws_subnet" "private" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.zones[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 4, count.index + 8)
  map_public_ip_on_launch = false
  tags = merge(local.common_tags, {
    Name                              = "${local.name_prefix}-private-${count.index + 1}"
    "kubernetes.io/role/internal-elb" = "1"
  })
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.common_tags, { Name = local.name_prefix })
  lifecycle {
    replace_triggered_by = [aws_vpc.main.id]
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = merge(local.common_tags, { Name = "${local.name_prefix}-public" })
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_eip" "nat" {
  count  = local.nat_count
  domain = "vpc"
  tags   = merge(local.common_tags, { Name = "${local.name_prefix}-nat-${count.index + 1}" })
}

resource "aws_nat_gateway" "main" {
  count         = local.nat_count
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  depends_on    = [aws_route.public_internet]
  tags          = merge(local.common_tags, { Name = "${local.name_prefix}-nat-${count.index + 1}" })
}

resource "aws_route_table" "private" {
  count  = 2
  vpc_id = aws_vpc.main.id
  tags   = merge(local.common_tags, { Name = "${local.name_prefix}-private-${count.index + 1}" })
}

resource "aws_route" "private_egress" {
  count                  = 2
  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main[count.index % local.nat_count].id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# These groups reserve the private inbound path for the later API/EKS layers.
# No inbound rules are granted to the VPC Link group itself.
resource "aws_security_group" "vpc_link" {
  name        = "${local.name_prefix}-vpc-link"
  description = "API Gateway VPC Link ENIs"
  vpc_id      = aws_vpc.main.id
  tags        = local.common_tags
}

resource "aws_security_group" "alb" {
  name        = "${local.name_prefix}-internal-alb"
  description = "Internal ALB accepts only VPC Link traffic"
  vpc_id      = aws_vpc.main.id
  tags        = local.common_tags
}

resource "aws_security_group" "backend" {
  name        = "${local.name_prefix}-backend"
  description = "Backend targets accept only internal ALB traffic"
  vpc_id      = aws_vpc.main.id
  tags        = local.common_tags
}

resource "aws_security_group_rule" "link_to_alb" {
  type                     = "egress"
  security_group_id        = aws_security_group.vpc_link.id
  source_security_group_id = aws_security_group.alb.id
  protocol                 = "tcp"
  from_port                = 80
  to_port                  = 80
}

resource "aws_security_group_rule" "alb_from_link" {
  type                     = "ingress"
  security_group_id        = aws_security_group.alb.id
  source_security_group_id = aws_security_group.vpc_link.id
  protocol                 = "tcp"
  from_port                = 80
  to_port                  = 80
}

resource "aws_security_group_rule" "alb_to_backend" {
  type                     = "egress"
  security_group_id        = aws_security_group.alb.id
  source_security_group_id = aws_security_group.backend.id
  protocol                 = "tcp"
  from_port                = 8000
  to_port                  = 8000
}

resource "aws_security_group_rule" "backend_from_alb" {
  type                     = "ingress"
  security_group_id        = aws_security_group.backend.id
  source_security_group_id = aws_security_group.alb.id
  protocol                 = "tcp"
  from_port                = 8000
  to_port                  = 8000
}
