# The TLS certificate for rancher.<domain>, used by both load balancers in the lab
# layer (infrastructure-design Q1, Q4). It lives here so that it, and its
# renewal, survive every teardown. ACM renews it on its own while the DNS
# validation record stays in the zone.

resource "aws_acm_certificate" "rancher" {
  domain_name       = local.rancher_fqdn
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

locals {
  # One name, so one validation record. Indexing the set keeps the sensitive
  # domain out of for_each, which Terraform refuses for sensitive values.
  rancher_validation = tolist(aws_acm_certificate.rancher.domain_validation_options)[0]
}

resource "aws_route53_record" "rancher_validation" {
  zone_id         = data.aws_route53_zone.public.zone_id
  name            = local.rancher_validation.resource_record_name
  type            = local.rancher_validation.resource_record_type
  records         = [local.rancher_validation.resource_record_value]
  ttl             = 300
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "rancher" {
  certificate_arn         = aws_acm_certificate.rancher.arn
  validation_record_fqdns = [aws_route53_record.rancher_validation.fqdn]
}
