# The lab network (LC15): one VPC, two public subnets, an internet gateway and no
# NAT gateway (REQ-020, BR8.1). Nodes and the Rancher host reach the internet
# through their own public addresses; their security groups accept nothing from
# it (SD-7, REQ-020.1).

resource "aws_vpc" "lab" {
  cidr_block           = local.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "sre-lab"
  }
}

# The VPC's default security group keeps no rules, so nothing can use it by accident.
resource "aws_default_security_group" "lab" {
  vpc_id = aws_vpc.lab.id
}

resource "aws_internet_gateway" "lab" {
  vpc_id = aws_vpc.lab.id

  tags = {
    Name = "sre-lab"
  }
}

resource "aws_subnet" "public" {
  count = length(local.zone_ids)

  vpc_id                  = aws_vpc.lab.id
  availability_zone_id    = local.zone_ids[count.index]
  cidr_block              = local.subnet_cidrs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "sre-lab-public-${local.zone_ids[count.index]}"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.lab.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.lab.id
  }

  tags = {
    Name = "sre-lab-public"
  }
}

resource "aws_route_table_association" "public" {
  count = length(aws_subnet.public)

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Security groups. Rules are separate aws_security_group_rule resources: the
# allow-list is sensitive, so it is passed as one whole list (cidr_blocks) and
# never iterated over, and the groups reference each other.

resource "aws_security_group" "public_alb" {
  name        = "sre-lab-rancher-public-alb"
  description = "Public Rancher load balancer: HTTPS from the allow-list only"
  vpc_id      = aws_vpc.lab.id
}

resource "aws_security_group" "internal_alb" {
  name        = "sre-lab-rancher-internal-alb"
  description = "Internal Rancher load balancer: HTTPS from inside the lab VPC"
  vpc_id      = aws_vpc.lab.id
}

resource "aws_security_group" "rancher" {
  name        = "sre-lab-rancher-host"
  description = "Rancher host: HTTPS from the two load balancers only, no SSH"
  vpc_id      = aws_vpc.lab.id
}

resource "aws_security_group_rule" "public_alb_https_from_allowlist" {
  type              = "ingress"
  description       = "HTTPS from the addresses in /sre-lab/allowlist-cidrs (REQ-021.1)"
  security_group_id = aws_security_group.public_alb.id
  protocol          = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_blocks       = local.allowlist_cidrs

  lifecycle {
    precondition {
      condition     = local.allowlist_is_valid
      error_message = "The SSM parameter /sre-lab/allowlist-cidrs must hold one or more comma-separated IPv4 CIDRs, each /16 or narrower (REQ-021.1)."
    }
  }
}

resource "aws_security_group_rule" "public_alb_to_rancher" {
  type                     = "egress"
  description              = "HTTPS to the Rancher host"
  security_group_id        = aws_security_group.public_alb.id
  protocol                 = "tcp"
  from_port                = 443
  to_port                  = 443
  source_security_group_id = aws_security_group.rancher.id
}

resource "aws_security_group_rule" "internal_alb_https_from_vpc" {
  type              = "ingress"
  description       = "HTTPS from the lab VPC: cluster agents and the Kubernetes read server"
  security_group_id = aws_security_group.internal_alb.id
  protocol          = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_blocks       = [local.vpc_cidr]
}

resource "aws_security_group_rule" "internal_alb_to_rancher" {
  type                     = "egress"
  description              = "HTTPS to the Rancher host"
  security_group_id        = aws_security_group.internal_alb.id
  protocol                 = "tcp"
  from_port                = 443
  to_port                  = 443
  source_security_group_id = aws_security_group.rancher.id
}

resource "aws_security_group_rule" "rancher_from_public_alb" {
  type                     = "ingress"
  description              = "HTTPS from the public load balancer"
  security_group_id        = aws_security_group.rancher.id
  protocol                 = "tcp"
  from_port                = 443
  to_port                  = 443
  source_security_group_id = aws_security_group.public_alb.id
}

resource "aws_security_group_rule" "rancher_from_internal_alb" {
  type                     = "ingress"
  description              = "HTTPS from the internal load balancer"
  security_group_id        = aws_security_group.rancher.id
  protocol                 = "tcp"
  from_port                = 443
  to_port                  = 443
  source_security_group_id = aws_security_group.internal_alb.id
}

# Outbound for installs and operation: K3s, the Rancher chart and images, the
# AWS APIs (Secrets Manager, Session Manager), Ubuntu updates and Fleet's Git
# clone. DNS and time use the VPC's own services, which security groups do not filter.
resource "aws_security_group_rule" "rancher_https_out" {
  type              = "egress"
  description       = "HTTPS to the internet"
  security_group_id = aws_security_group.rancher.id
  protocol          = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_blocks       = ["0.0.0.0/0"]
}

resource "aws_security_group_rule" "rancher_http_out" {
  type              = "egress"
  description       = "HTTP to the internet, for Ubuntu package mirrors"
  security_group_id = aws_security_group.rancher.id
  protocol          = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_blocks       = ["0.0.0.0/0"]
}
