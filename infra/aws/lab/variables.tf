variable "kubernetes_version" {
  description = "EKS version. 1.36: in EKS standard support until 2027-08-02 (eks:DescribeClusterVersions, us-east-1, 2026-11-11), and the newest that Rancher 2.15.3 supports for imported clusters (SUSE support matrix; EKS 1.37 is not certified). The plan fails once it leaves standard support (REQ-020, BR8.1)."
  type        = string
  default     = "1.36"
}

variable "eks_addon_versions" {
  description = "EKS add-on versions, pinned to the defaults that eks:DescribeAddonVersions gave for Kubernetes 1.36 in us-east-1 on 2026-11-11."
  type = object({
    vpc_cni            = string
    kube_proxy         = string
    coredns            = string
    pod_identity_agent = string
  })
  default = {
    vpc_cni            = "v1.22.4-eksbuild.14"
    kube_proxy         = "v1.36.0-eksbuild.65"
    coredns            = "v1.14.7-eksbuild.35"
    pod_identity_agent = "v1.4.1-eksbuild.3"
  }
}

variable "node_instance_type" {
  description = "EKS node type (Graviton, 8 GiB). infrastructure-specification.md falls back to t3.large if a demo image has no arm64 build."
  type        = string
  default     = "t4g.large"
}

variable "node_count" {
  description = "Number of EKS nodes."
  type        = number
  default     = 2

  validation {
    condition     = var.node_count >= 1 && var.node_count <= 3
    error_message = "The lab runs 1 to 3 nodes."
  }
}

variable "rancher_instance_type" {
  description = "Instance type of the Rancher host, as in the Phase 0 spike."
  type        = string
  default     = "t3.large"
}

variable "k3s_version" {
  description = "K3s on the Rancher host: the newest v1.36 release (2026-11-03). Rancher 2.15.3 supports K3s v1.34 to v1.36 for its own cluster, and its chart requires Kubernetes below 1.37."
  type        = string
  default     = "v1.36.6+k3s1"
}

variable "k3s_sha256" {
  description = "SHA-256 of the k3s amd64 binary of k3s_version, as published in that release's sha256sum-amd64.txt."
  type        = string
  default     = "66ceb8e67edfa547195135d74783bfadc2ecc04a91059e90ae5f70a3dbc98c15"

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.k3s_sha256))
    error_message = "Give a SHA-256 as 64 lowercase hex digits."
  }
}

variable "k3s_install_script_sha256" {
  description = "SHA-256 of install.sh at the k3s_version tag of k3s-io/k3s. The project publishes no checksum for the script, so this one was computed from the tagged file on 2026-11-11."
  type        = string
  default     = "46177d4c99440b4c0311b67233823a8e8a2fc09693f6c89af1a7161e152fbfad"

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.k3s_install_script_sha256))
    error_message = "Give a SHA-256 as 64 lowercase hex digits."
  }
}

variable "rancher_chart_version" {
  description = "Rancher Helm chart: 2.15.3 (app v2.15.3, 2026-10-29), the newest 2.15 release."
  type        = string
  default     = "2.15.3"
}

variable "rancher_chart_sha256" {
  description = "SHA-256 of rancher-<version>.tgz: the digest the stable chart repository's index.yaml publishes for it."
  type        = string
  default     = "343888c66421a9f5666b562cdfeca751d63da994edbe7b1b36752f8ffcf5ecd4"

  validation {
    condition     = can(regex("^[0-9a-f]{64}$", var.rancher_chart_sha256))
    error_message = "Give a SHA-256 as 64 lowercase hex digits."
  }
}

variable "coding_agent_permission_set_name" {
  description = "IAM Identity Center permission set the coding agent signs in with. Its role is refused the values of the two Rancher secrets (REQ-013.1)."
  type        = string
  default     = "SreLabReadOnly"

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,32}$", var.coding_agent_permission_set_name))
    error_message = "A permission set name is 1 to 32 characters: letters, digits and +=,.@_-"
  }
}
