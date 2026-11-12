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
- After that, it must succeed, with no output.
- A `403` (`Forbidden`) means another account owns the name. Stop and do not run `init` in any root: change the bucket name in every backend block, in `data.terraform_remote_state.permanent` in `infra/aws/lab`, and in the `state_bucket_name` variables, in a pull request.

The CI plan role is refused every S3 bucket that another account owns, so even a wrong name cannot leak state from CI.

## First apply, then move the state into the bucket

The backend block points at the bucket this root creates, so the first apply runs with local state. Run these from your admin terminal, on `main`, with the admin profile.

1. Check the name is free (above).
2. Create a local override, which `.gitignore` keeps out of Git:

   ```bash
   cat > infra/aws/bootstrap/backend_override.tf <<'EOF'
   terraform {
     backend "local" {}
   }
   EOF
   ```

3. Initialize, plan and apply with local state:

   ```bash
   terraform -chdir=infra/aws/bootstrap init
   terraform -chdir=infra/aws/bootstrap plan -out=bootstrap.tfplan
   terraform -chdir=infra/aws/bootstrap apply bootstrap.tfplan
   ```

4. Check the bucket is now yours: the `head-bucket` command above must succeed.
5. Delete the override, then move the local state into the bucket. Answer `yes` when Terraform asks to copy the state:

   ```bash
   rm infra/aws/bootstrap/backend_override.tf
   terraform -chdir=infra/aws/bootstrap init -migrate-state
   ```

6. Check that the state is in the bucket, and remove the local copies:

   ```bash
   aws s3 ls s3://multi-cloud-agentic-sre-tfstate/bootstrap/
   terraform -chdir=infra/aws/bootstrap plan    # expect: No changes.
   rm -f infra/aws/bootstrap/terraform.tfstate infra/aws/bootstrap/terraform.tfstate.backup infra/aws/bootstrap/bootstrap.tfplan
   ```

## Later changes

Plan and apply this root like any other, from `main`. It is not planned in CI: the CI plan job covers `permanent` and `lab` only. The bucket has `prevent_destroy`, so a plan that would delete it fails.

## Rollback

A revert pull request, then apply again. To restore an earlier state file, copy one of its older versions over the current one with `aws s3api copy-object`; versions are kept 90 days.
