output "state_bucket_name" {
  description = "The Terraform state bucket every root's backend uses."
  value       = aws_s3_bucket.state.id
}

output "state_bucket_arn" {
  description = "ARN of the state bucket (S3 bucket ARNs carry no account ID)."
  value       = aws_s3_bucket.state.arn
}
