# Split horizon for rancher.<domain> (infrastructure-specification.md, "Name
# resolution"): the public zone points the name at the public load balancer, and
# a private zone tied to the lab VPC points the same name at the internal one.

resource "aws_route53_record" "rancher_public" {
  zone_id = local.public_zone_id
  name    = local.rancher_fqdn
  type    = "A"

  alias {
    name                   = aws_lb.rancher["public"].dns_name
    zone_id                = aws_lb.rancher["public"].zone_id
    evaluate_target_health = true
  }
}

resource "aws_route53_zone" "rancher_private" {
  name          = local.rancher_fqdn
  comment       = "Split horizon: inside the lab VPC, Rancher resolves to the internal load balancer."
  force_destroy = true

  vpc {
    vpc_id = aws_vpc.lab.id
  }
}

resource "aws_route53_record" "rancher_private" {
  zone_id = aws_route53_zone.rancher_private.zone_id
  name    = local.rancher_fqdn
  type    = "A"

  alias {
    name                   = aws_lb.rancher["internal"].dns_name
    zone_id                = aws_lb.rancher["internal"].zone_id
    evaluate_target_health = true
  }
}
