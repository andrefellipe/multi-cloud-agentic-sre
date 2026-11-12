# The workload cluster (LC16): EKS on a Kubernetes version in standard support
# (REQ-020), with a private API endpoint plus public access for your allow-list
# only (REQ-020.1, SD-7), and two Graviton nodes in a managed node group whose
# instances require IMDSv2 with a hop limit of 1, so pods cannot reach the node's
# credentials. Pods get AWS access through EKS Pod Identity instead.

data "aws_iam_policy_document" "eks_cluster_trust" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eks_cluster" {
  name               = "sre-lab-eks-cluster"
  description        = "EKS control plane role for the lab cluster."
  assume_role_policy = data.aws_iam_policy_document.eks_cluster_trust.json
}

resource "aws_iam_role_policy_attachment" "eks_cluster" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_eks_cluster" "lab" {
  name     = local.cluster_name
  version  = var.kubernetes_version
  role_arn = aws_iam_role.eks_cluster.arn

  # The add-ons below are managed by EKS, so the cluster starts without its own copies.
  bootstrap_self_managed_addons = false

  access_config {
    authentication_mode = "API"
    # Whoever applies (you, with the admin profile) becomes cluster admin, so you
    # can run Rancher's registration command. CI cannot apply.
    bootstrap_cluster_creator_admin_permissions = true
  }

  # When standard support ends, upgrade instead of paying for extended support.
  upgrade_policy {
    support_type = "STANDARD"
  }

  vpc_config {
    subnet_ids              = aws_subnet.public[*].id
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = local.allowlist_cidrs
  }

  lifecycle {
    precondition {
      condition     = contains(data.aws_eks_cluster_versions.standard.cluster_versions[*].cluster_version, var.kubernetes_version)
      error_message = "Kubernetes ${var.kubernetes_version} is not in EKS standard support here. Move kubernetes_version to a standard-support version that Rancher supports (REQ-020, BR8.1)."
    }

    precondition {
      condition     = local.allowlist_is_valid
      error_message = "The SSM parameter /sre-lab/allowlist-cidrs must hold one or more comma-separated IPv4 CIDRs, each /16 or narrower (REQ-020.1)."
    }
  }

  depends_on = [aws_iam_role_policy_attachment.eks_cluster]
}

data "aws_iam_policy_document" "eks_nodes_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eks_nodes" {
  name               = "sre-lab-eks-nodes"
  description        = "EKS worker nodes of the lab cluster."
  assume_role_policy = data.aws_iam_policy_document.eks_nodes_trust.json
}

resource "aws_iam_role_policy_attachment" "eks_nodes" {
  for_each = toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEKS_CNI_Policy",
    "AmazonEC2ContainerRegistryPullOnly",
  ])

  role       = aws_iam_role.eks_nodes.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/${each.key}"
}

# Encrypted root volumes, IMDSv2 only with a hop limit of 1, and the project tags
# on the instances and volumes the node group launches.
resource "aws_launch_template" "eks_nodes" {
  name_prefix            = "sre-lab-eks-nodes-"
  description            = "Lab EKS nodes: IMDSv2 with hop limit 1, encrypted gp3 root volume."
  update_default_version = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = 20
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  dynamic "tag_specifications" {
    for_each = toset(["instance", "volume", "network-interface"])

    content {
      resource_type = tag_specifications.value
      tags          = merge(local.default_tags, { Name = "sre-lab-eks-node" })
    }
  }
}

# Managed add-ons, pinned. These three run before the nodes join, so that nodes
# become ready; CoreDNS follows once there are nodes to schedule it on.
resource "aws_eks_addon" "vpc_cni" {
  cluster_name                = aws_eks_cluster.lab.name
  addon_name                  = "vpc-cni"
  addon_version               = var.eks_addon_versions.vpc_cni
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"
}

resource "aws_eks_addon" "kube_proxy" {
  cluster_name                = aws_eks_cluster.lab.name
  addon_name                  = "kube-proxy"
  addon_version               = var.eks_addon_versions.kube_proxy
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"
}

resource "aws_eks_addon" "pod_identity_agent" {
  cluster_name                = aws_eks_cluster.lab.name
  addon_name                  = "eks-pod-identity-agent"
  addon_version               = var.eks_addon_versions.pod_identity_agent
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"
}

resource "aws_eks_node_group" "default" {
  cluster_name    = aws_eks_cluster.lab.name
  node_group_name = "default"
  node_role_arn   = aws_iam_role.eks_nodes.arn
  subnet_ids      = aws_subnet.public[*].id
  # Graviton families carry a "g" after the generation (t4g, m7g); the fallback
  # t3.large in infrastructure-specification.md needs the x86 image.
  ami_type       = can(regex("^[a-z]+[0-9]+g", var.node_instance_type)) ? "AL2023_ARM_64_STANDARD" : "AL2023_x86_64_STANDARD"
  capacity_type  = "ON_DEMAND"
  instance_types = [var.node_instance_type]

  scaling_config {
    desired_size = var.node_count
    min_size     = var.node_count
    max_size     = var.node_count
  }

  update_config {
    max_unavailable = 1
  }

  launch_template {
    id      = aws_launch_template.eks_nodes.id
    version = aws_launch_template.eks_nodes.latest_version
  }

  depends_on = [
    aws_iam_role_policy_attachment.eks_nodes,
    aws_eks_addon.vpc_cni,
    aws_eks_addon.kube_proxy,
    aws_eks_addon.pod_identity_agent,
  ]
}

resource "aws_eks_addon" "coredns" {
  cluster_name                = aws_eks_cluster.lab.name
  addon_name                  = "coredns"
  addon_version               = var.eks_addon_versions.coredns
  resolve_conflicts_on_create = "OVERWRITE"
  resolve_conflicts_on_update = "OVERWRITE"

  depends_on = [aws_eks_node_group.default]
}
