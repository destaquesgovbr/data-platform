# Cloud Composer Terraform Replacement Issue - Analysis

> **Date**: 2026-01-05
> **Trigger**: `terraform init -upgrade` in infra repo
> **Impact**: Terraform wants to replace running Composer environment (HIGH RISK)

## Executive Summary

When we ran `terraform init -upgrade` in the infra repo, Terraform updated from Google Provider v5.45.2 to v6.50.0. This major version upgrade introduced **breaking changes** to the `google_composer_environment` resource schema, specifically around `ip_allocation_policy` configuration. Terraform now incorrectly detects our existing Composer configuration as incompatible and proposes destruction + recreation.

**This is a provider schema migration artifact, NOT a real infrastructure change.**

## Root Cause

### Provider Version Jump
```
Provider         Before      After       Impact
google           5.45.2  →   6.50.0     Breaking change in v6.0.0
google-beta      5.45.2  →   6.50.0     Breaking change in v6.0.0
```

### Breaking Change in v6.0.0

The `ip_allocation_policy` block schema was fundamentally changed:

- **Before v6.0.0**: Multiple configuration patterns were valid, including empty arrays `[]`
- **After v6.0.0**: Strict validation rules introduced that conflict with existing configurations
- **Bug**: The validation logic has conflicting requirements:
  - When specifying CIDR blocks, requires secondary range names
  - When providing secondary range names, reports "Conflicting configuration arguments"

### Our Configuration

In [composer.tf:146-155](../../../infra/terraform/composer.tf#L146-L155):

```hcl
node_config {
  network         = google_compute_network.main.id
  subnetwork      = google_compute_subnetwork.composer_us_central1.id
  service_account = google_service_account.composer.email

  ip_allocation_policy {
    cluster_secondary_range_name  = "composer-pods"
    services_secondary_range_name = "composer-services"
  }

  tags = ["composer"]
}
```

This configuration references secondary ranges defined in our subnetwork (composer.tf:25-33), which is a valid GKE setup. However, provider v6.0.0 schema migration triggers `ForceNew` behavior due to internal representation changes.

## Why Only Composer Is Affected

The terraform plan output showed:
```
Plan: 5 to add, 8 to change, 2 to destroy
google_composer_environment.main must be replaced
```

Breakdown:
1. **Composer environment** marked for destruction + recreation (1 destroy, 1 add)
2. **Dependent resources** need updating when Composer changes:
   - Service account IAM bindings
   - Secrets IAM bindings
   - Network attachments
3. **New HuggingFace secrets** we added (4 new resources)

The HuggingFace connection secrets are NOT the cause - they would just reference the new Composer instance if it were recreated.

## Technical Details

### Affected Attributes

The provider detects incompatibility in:
- `config.0.node_config.0.ip_allocation_policy` (ForceNew=true)

### Provider Schema History

Analyzed via git history of [.terraform.lock.hcl](../../../infra/terraform/.terraform.lock.hcl):

- **Commit 4e8d599** (2025-12-28): "chore: upgrade to Composer 3.0" - Provider v5.45.2
- **Local run** (2026-01-05): `terraform init -upgrade` - Provider v6.50.0
- **Current HEAD**: Lock file shows v6.50.0

The upgrade was not committed to git - it happened during our local debugging session.

### Known Upstream Issues

- [GitHub Issue #12167](https://github.com/hashicorp/terraform-provider-google/issues/12167): "ip_allocation_policy causes force replacement"
- Multiple users report conflicting validation errors
- No fix as of v6.50.0 (current latest)

## Impact Assessment

### If Composer Is Replaced

**Downtime**: ~45-60 minutes
- Composer environment recreation takes 30-45 minutes
- DAGs need to be re-deployed
- Service interruption for all data pipelines

**Data Loss Risk**: LOW
- PostgreSQL database is separate (not affected)
- DAGs are in git (can be redeployed)
- Secrets are in Secret Manager (persist independently)

**Cost**: ~$5-10 for temporary duplicate resources during replacement

### If We Do Nothing

The change is blocked - we cannot apply any Terraform changes in the infra repo without either:
1. Accepting the Composer replacement
2. Implementing a mitigation

## Recommended Solutions

### Option 1: Add ignore_changes (RECOMMENDED)

Add to [composer.tf:41](../../../infra/terraform/composer.tf#L41) (google_composer_environment resource):

```hcl
resource "google_composer_environment" "main" {
  provider = google-beta
  name     = var.composer_environment_name
  region   = var.composer_region

  lifecycle {
    ignore_changes = [
      config[0].node_config[0].ip_allocation_policy,
      config[0].software_config[0].image_version
    ]
  }

  # ... rest of configuration
}
```

**Pros**:
- Safe - prevents unnecessary recreation
- Allows other Terraform changes to proceed
- Composer continues operating without interruption
- Can be removed once provider bug is fixed

**Cons**:
- Future intentional changes to IP allocation policy won't be detected
- Workaround rather than fix

**Verdict**: This is the pragmatic solution. The IP allocation policy is unlikely to change, and we can remove this ignore once HashiCorp fixes the schema bug.

### Option 2: Pin Provider Version

In [main.tf:7](../../../infra/terraform/main.tf#L7), change:

```hcl
required_providers {
  google = {
    source  = "hashicorp/google"
    version = "~> 5.45"  # Pin to v5.x
  }
  google-beta = {
    source  = "hashicorp/google-beta"
    version = "~> 5.45"  # Pin to v5.x
  }
}
```

Then run `terraform init -upgrade` to downgrade.

**Pros**:
- Avoids the issue entirely
- No workarounds in config

**Cons**:
- Blocks important security patches and bug fixes in v6.x
- Not sustainable long-term
- Delayed migration pain

**Verdict**: NOT recommended. Staying on v5.x indefinitely is not viable.

### Option 3: Re-import State

```bash
# Remove from state
terraform state rm google_composer_environment.main

# Re-import with v6.x schema
terraform import google_composer_environment.main \
  inspire-7-finep/us-central1/destaquesgovbr-composer
```

**Pros**:
- Refreshes state representation to match v6.x schema
- Might resolve the ForceNew trigger

**Cons**:
- Risky - state operations can corrupt terraform state
- No guarantee it will fix the issue (might still detect drift)
- Hard to undo

**Verdict**: Worth trying as a last resort, but Option 1 is safer.

### Option 4: Accept Replacement

Allow Terraform to destroy and recreate the Composer environment.

**Pros**:
- "Clean" from Terraform perspective
- Gets environment onto v6.x-compatible schema definitively

**Cons**:
- 45-60 minute downtime
- Risk of misconfiguration during recreation
- Unnecessary disruption

**Verdict**: NOT recommended. The existing environment is working perfectly - don't fix what isn't broken.

## Implementation Plan

### Recommended Approach: Option 1 (ignore_changes)

**Step 1**: Update composer.tf

```bash
cd /Users/nitai/Dropbox/dev-mgi/destaquesgovbr/infra
```

Add lifecycle block to google_composer_environment.main resource (see Option 1 above).

**Step 2**: Test Plan

```bash
cd terraform
terraform plan
```

Expected output:
```
No changes. Your infrastructure matches the configuration.
```

**Step 3**: Commit Change

```bash
git add terraform/composer.tf
git commit -m "fix: add lifecycle ignore for Composer ip_allocation_policy

Work around Terraform Google Provider v6.0.0 breaking change that
incorrectly triggers force replacement of Composer environment.

See: https://github.com/hashicorp/terraform-provider-google/issues/12167
See: _analysis/composer_recreation_issue.md"
```

**Step 4**: Create PR

```bash
gh pr create --title "Fix: Prevent unnecessary Composer replacement" \
  --body "Adds lifecycle ignore_changes workaround for provider v6.x schema migration issue."
```

**Step 5**: Verify

After merging, run workflow plan to confirm no replacement proposed.

## Monitoring Plan

1. **Watch upstream issue**: Monitor [GitHub Issue #12167](https://github.com/hashicorp/terraform-provider-google/issues/12167) for resolution
2. **Test future versions**: When v6.51+ is released, test in staging:
   ```bash
   terraform init -upgrade
   terraform plan  # Check if replacement still proposed
   ```
3. **Remove workaround**: Once provider bug is fixed, remove ignore_changes block

## Lessons Learned

1. **Never run `terraform init -upgrade` locally without committing** - should only be done in CI/CD
2. **Pin provider versions** in production - use `~>` constraints to control upgrades:
   ```hcl
   version = "~> 5.45"  # Allows 5.46, 5.47, etc. but blocks 6.0
   ```
3. **Test provider upgrades in staging first** - major version upgrades (5.x → 6.x) can have breaking changes
4. **Lock file should be committed** - .terraform.lock.hcl tracks exact versions

## References

- **Issue Report**: [terraform-provider-google #12167](https://github.com/hashicorp/terraform-provider-google/issues/12167)
- **Release Notes**: [v6.0.0 Release](https://github.com/hashicorp/terraform-provider-google/releases/tag/v6.0.0)
- **Upgrade Guide**: [Version 6 Upgrade Guide](https://registry.terraform.io/providers/hashicorp/google/latest/docs/guides/version_6_upgrade)
- **Resource Docs**: [google_composer_environment](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/composer_environment)

---

**Status**: Open (waiting for decision on mitigation approach)
**Next Action**: Implement Option 1 (ignore_changes) to unblock Terraform operations
