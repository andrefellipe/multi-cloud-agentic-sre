# infra/aws/bootstrap

The Terraform state bucket that every other root under `infra/aws` keeps its state in. You apply this root once, then never tear it down.

## What it creates

- The bucket `multi-cloud-agentic-sre-tfstate`, in `us-east-1`:
  - versioned, so earlier state can be restored;
  - encrypted with SSE-S3;
  - closed to public access, with ACLs turned off;
  - refusing any request made without TLS;
  - refusing the coding agent's read-only role (the IAM Identity Center permission set `SreLabReadOnly`) any read or write of a state object, because state can hold configuration secrets (REQ-013.1);
  - keeping old state versions for 90 days, then removing them.
- No lock table. Every root locks with a lock file next to its state (`use_lockfile = true`).

## Before any init: check that the bucket is yours

Bucket names are global and this repository is public, so someone else could create a bucket with this name first. Run this in your admin terminal before every first `terraform init` on a machine, with your own account ID typed in your shell, never written to a file:

```bash
aws s3api head-bucket --bucket multi-cloud-agentic-sre-tfstate --expected-bucket-owner "$ACCOUNT_ID"
```

- Before the first apply of this root, it must fail with `404` (`Not Found`): the name is free.
- After that, it must succeed. It prints the bucket's ARN and Region.
- A `403` (`Forbidden`) means another account owns the name. Stop and do not run `init` in any root: change the bucket name in every backend block, in `data.terraform_remote_state.permanent` in `infra/aws/lab`, and in the `state_bucket_name` variables, in a pull request.

The CI plan role is refused every S3 bucket that another account owns, so even a wrong name cannot leak state from CI.

## First apply, then move the state into the bucket

The backend block points at the bucket this root creates, so the first apply runs with local state. Run these from your admin terminal, on `main`, with the admin profile. Paste each block on its own, and check its result before the next: a shell keeps running the lines after one that fails, and a command that asks you to type `yes` reads the next pasted line as your answer.

1. Check the name is free (above).
2. Create a local override, which `.gitignore` keeps out of Git:

   ```bash
   cat > infra/aws/bootstrap/backend_override.tf <<'EOF'
   terraform {
     backend "local" {}
   }
   EOF
   ```

3. Initialize and plan with local state:

   ```bash
   terraform -chdir=infra/aws/bootstrap init
   terraform -chdir=infra/aws/bootstrap plan -out=bootstrap.tfplan
   ```

   The plan must end with `Plan: 7 to add, 0 to change, 0 to destroy.`
4. Apply it, and wait for `Apply complete!`:

   ```bash
   terraform -chdir=infra/aws/bootstrap apply bootstrap.tfplan
   ```

5. Check the bucket is now yours: the `head-bucket` command above must succeed.
6. Delete the override, then move the local state into the bucket. When Terraform asks whether to copy the existing state to the new backend, type `yes`:

   ```bash
   rm infra/aws/bootstrap/backend_override.tf
   terraform -chdir=infra/aws/bootstrap init -migrate-state
   ```

   It must end with `Terraform has been successfully initialized!`
7. Check that the state reached the bucket:

   ```bash
   aws s3 ls s3://multi-cloud-agentic-sre-tfstate/bootstrap/
   terraform -chdir=infra/aws/bootstrap plan
   ```

   `aws s3 ls` must list `terraform.tfstate`, and the plan must end with `No changes. Your infrastructure matches the configuration.`
8. Only when both checks in step 7 pass, delete the local copies. Until then, they are the only copy of the state:

   ```bash
   rm -f infra/aws/bootstrap/terraform.tfstate infra/aws/bootstrap/terraform.tfstate.backup infra/aws/bootstrap/bootstrap.tfplan
   ```

## If the state is lost before it reaches the bucket

If the local state was deleted before step 6 copied it, the bucket still exists and works. Only Terraform's record of it is gone, so a plan would try to create the bucket again: never apply that plan. Rebuild the record from the bucket instead, from your admin terminal.

1. Check that `infra/aws/bootstrap/backend_override.tf` is deleted. Then point the root at the bucket, and list what Terraform knows:

   ```bash
   terraform -chdir=infra/aws/bootstrap init -reconfigure
   terraform -chdir=infra/aws/bootstrap state list
   ```

   If `state list` prints `aws_s3_bucket.state` and the other resources, the state is safe: stop here. If it prints `No state file was found!`, go on.
2. Import the seven resources from the bucket. Each import ends with `Import successful!` and writes straight into the bucket:

   ```bash
   terraform -chdir=infra/aws/bootstrap import aws_s3_bucket.state multi-cloud-agentic-sre-tfstate
   terraform -chdir=infra/aws/bootstrap import aws_s3_bucket_ownership_controls.state multi-cloud-agentic-sre-tfstate
   terraform -chdir=infra/aws/bootstrap import aws_s3_bucket_public_access_block.state multi-cloud-agentic-sre-tfstate
   terraform -chdir=infra/aws/bootstrap import aws_s3_bucket_versioning.state multi-cloud-agentic-sre-tfstate
   terraform -chdir=infra/aws/bootstrap import aws_s3_bucket_server_side_encryption_configuration.state multi-cloud-agentic-sre-tfstate
   terraform -chdir=infra/aws/bootstrap import aws_s3_bucket_lifecycle_configuration.state multi-cloud-agentic-sre-tfstate
   terraform -chdir=infra/aws/bootstrap import aws_s3_bucket_policy.state multi-cloud-agentic-sre-tfstate
   ```

3. Check that the record matches the bucket. The plan must end with `No changes. Your infrastructure matches the configuration.`

   ```bash
   terraform -chdir=infra/aws/bootstrap plan
   ```

## Later changes

Plan and apply this root like any other, from `main`. It is not planned in CI: the CI plan job covers `permanent` and `lab` only. The bucket has `prevent_destroy`, so a plan that would delete it fails.

## Rollback

A revert pull request, then apply again. To restore an earlier state file, copy one of its older versions over the current one with `aws s3api copy-object`; versions are kept 90 days.
