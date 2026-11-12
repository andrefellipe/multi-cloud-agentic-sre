# Two ways into Rancher, one name and one certificate (infrastructure-design Q1, Q4):
# - public: an internet-facing load balancer for you, open only to your
#   allow-list (network.tf);
# - internal: for clients inside the VPC, such as the cluster agents and the
#   Kubernetes read server, whose addresses no allow-list can hold.
# Both end TLS 1.2 or later with the ACM certificate from the permanent layer and
# re-encrypt to Rancher on 443 (REQ-021.1, SD-6).
#
# Health check: Rancher 2.15.3 answers /healthz with 200 for any host name (its
# own pod probes use it), but its ingress routes by host name, and a load
# balancer's health check sends the target's address as the host name. The
# Rancher host therefore adds a route for /healthz alone that matches any host
# name (templates/rancher-host-user-data.sh.tftpl).

locals {
  rancher_entry_points = {
    public = {
      internal          = false
      security_group_id = aws_security_group.public_alb.id
    }
    internal = {
      internal          = true
      security_group_id = aws_security_group.internal_alb.id
    }
  }
}

resource "aws_lb" "rancher" {
  for_each = local.rancher_entry_points

  name                       = "sre-lab-rancher-${each.key}"
  load_balancer_type         = "application"
  internal                   = each.value.internal
  subnets                    = aws_subnet.public[*].id
  security_groups            = [each.value.security_group_id]
  drop_invalid_header_fields = true
  # Rancher keeps long-lived WebSocket connections (agents, kubectl logs -f).
  idle_timeout = 300
}

resource "aws_lb_target_group" "rancher" {
  for_each = local.rancher_entry_points

  name        = "sre-lab-rancher-${each.key}"
  vpc_id      = aws_vpc.lab.id
  target_type = "instance"
  protocol    = "HTTPS"
  port        = 443

  health_check {
    protocol            = "HTTPS"
    port                = "traffic-port"
    path                = "/healthz"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_target_group_attachment" "rancher" {
  for_each = local.rancher_entry_points

  target_group_arn = aws_lb_target_group.rancher[each.key].arn
  target_id        = aws_instance.rancher.id
  port             = 443
}

resource "aws_lb_listener" "rancher_https" {
  for_each = local.rancher_entry_points

  load_balancer_arn = aws_lb.rancher[each.key].arn
  port              = 443
  protocol          = "HTTPS"
  # TLS 1.3 and 1.2 only (REQ-021.1).
  ssl_policy      = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn = local.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.rancher[each.key].arn
  }
}
