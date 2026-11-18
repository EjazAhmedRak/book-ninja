resource "aws_iam_role" "cluster" {
  name = "${local.name_prefix}-eks-cluster"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "eks.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_eks_cluster" "main" {
  name     = local.name_prefix
  role_arn = aws_iam_role.cluster.arn
  version  = "1.32"
  # k3s provides its own CoreDNS and metrics components locally.
  bootstrap_self_managed_addons = !var.local_validation
  vpc_config {
    subnet_ids              = aws_subnet.private[*].id
    endpoint_private_access = true
    # The emulated API binds a localhost port; real AWS stays private.
    endpoint_public_access = var.local_validation
  }
  depends_on = [aws_iam_role_policy_attachment.cluster, aws_route.private_egress]
  tags       = local.common_tags
}

resource "aws_iam_role" "nodes" {
  name = "${local.name_prefix}-eks-nodes"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  tags = local.common_tags
}

resource "aws_iam_role_policy_attachment" "nodes" {
  for_each   = toset(["AmazonEKSWorkerNodePolicy", "AmazonEKS_CNI_Policy", "AmazonEC2ContainerRegistryReadOnly"])
  role       = aws_iam_role.nodes.name
  policy_arn = "arn:aws:iam::aws:policy/${each.value}"
}

resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${local.name_prefix}-workers"
  node_role_arn   = aws_iam_role.nodes.arn
  subnet_ids      = aws_subnet.private[*].id
  instance_types  = ["t3.medium"]
  scaling_config {
    desired_size = var.local_validation ? 1 : 2
    min_size     = var.local_validation ? 1 : 2
    max_size     = 3
  }
  depends_on = [aws_iam_role_policy_attachment.nodes]
  tags       = local.common_tags
}
