# Sign-in to Rancher: an Amazon Cognito user pool that requires MFA with an
# authenticator app, holding only your operator user (infrastructure-design Q2,
# REQ-021.1). tools/lab/configure_rancher.py connects Rancher to it after each
# lab rebuild, and refuses to while the pool does not require MFA.

resource "aws_cognito_user_pool" "sre_lab" {
  name                     = "sre-lab"
  deletion_protection      = "ACTIVE"
  user_pool_tier           = "ESSENTIALS"
  mfa_configuration        = "ON"
  alias_attributes         = ["email"]
  auto_verified_attributes = ["email"]

  software_token_mfa_configuration {
    enabled = true
  }

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 3
  }

  username_configuration {
    case_sensitive = false
  }

  user_attribute_update_settings {
    attributes_require_verification_before_update = ["email"]
  }
}

# The hosted sign-in pages. Version 1 is the classic hosted UI, which needs no
# branding resource and supports setting up an authenticator app at first sign-in.
resource "aws_cognito_user_pool_domain" "sre_lab" {
  domain                = var.cognito_domain_prefix
  user_pool_id          = aws_cognito_user_pool.sre_lab.id
  managed_login_version = 1
}

# Your user. Cognito emails a temporary password to the address in the SSM
# parameter; at first sign-in you set a password and an authenticator app.
resource "aws_cognito_user" "operator" {
  user_pool_id             = aws_cognito_user_pool.sre_lab.id
  username                 = var.operator_username
  desired_delivery_mediums = ["EMAIL"]

  attributes = {
    email          = data.aws_ssm_parameter.cognito_user_email.value
    email_verified = "true"
  }
}

# Rancher's app client. Rancher's Cognito provider requires a client secret
# (clientSecret is a required field of its OIDC configuration in Rancher 2.15.3),
# so the client is confidential. The configuration script reads the secret from
# Cognito when it runs; Terraform keeps it in state, marked sensitive
# (cicd-pipeline.md accepts this for Phase 1).
resource "aws_cognito_user_pool_client" "rancher" {
  name                                 = "rancher"
  user_pool_id                         = aws_cognito_user_pool.sre_lab.id
  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]
  callback_urls                        = ["${local.rancher_url}/verify-auth"]
  explicit_auth_flows                  = ["ALLOW_USER_SRP_AUTH", "ALLOW_REFRESH_TOKEN_AUTH"]
  prevent_user_existence_errors        = "ENABLED"
  enable_token_revocation              = true
  access_token_validity                = 60
  id_token_validity                    = 60
  refresh_token_validity               = 1

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }
}
