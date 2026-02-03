# Runbook: Cloud Composer Recovery

> **Last Updated**: 2026-02-03
> **Owner**: Data Platform Team
> **Severity**: P1 (Critical)

---

## Overview

This runbook covers recovery procedures for Cloud Composer issues, particularly when DAGs are missing from the Airflow UI.

## Quick Recovery

If DAGs are missing, run this workflow to redeploy them:

```bash
gh workflow run composer-deploy-dags.yaml --repo destaquesgovbr/data-platform
```

Or trigger manually via GitHub Actions UI:
1. Go to [Actions > Deploy DAGs to Composer](https://github.com/destaquesgovbr/data-platform/actions/workflows/composer-deploy-dags.yaml)
2. Click "Run workflow"
3. Select `main` branch
4. Click "Run workflow"

---

## Symptoms

| Symptom | Likely Cause |
|---------|--------------|
| No DAGs visible in Airflow UI | Composer recreated, bucket changed |
| "DAG not found" errors | DAGs not deployed to new bucket |
| DAG runs failing | Missing connections or packages |
| Airflow UI unavailable | Composer environment down |

---

## Diagnosis Steps

### 1. Check if Composer was recently recreated

```bash
# Check Cloud Audit Logs for Composer create events
gcloud logging read \
  "resource.type=cloud_composer_environment AND protoPayload.methodName:Create" \
  --project=inspire-7-finep \
  --limit=5 \
  --format="table(timestamp,protoPayload.methodName)"
```

### 2. Verify current DAGs bucket

```bash
# Get the current DAGs bucket path
gcloud composer environments describe destaquesgovbr-composer \
  --location=us-central1 \
  --format="value(config.dagGcsPrefix)"
```

### 3. Check if DAGs exist in bucket

```bash
# List DAG files in the bucket
DAGS_BUCKET=$(gcloud composer environments describe destaquesgovbr-composer \
  --location=us-central1 \
  --format="value(config.dagGcsPrefix)")

gsutil ls -l "$DAGS_BUCKET/*.py"
```

### 4. Check Composer environment status

```bash
gcloud composer environments describe destaquesgovbr-composer \
  --location=us-central1 \
  --format="table(state,config.airflowUri)"
```

---

## Recovery Procedures

### Scenario 1: DAGs missing (Composer healthy)

**Cause**: Composer was recreated, new bucket hash, DAGs not deployed.

**Fix**:
```bash
# Option 1: Trigger GitHub workflow
gh workflow run composer-deploy-dags.yaml --repo destaquesgovbr/data-platform

# Option 2: Manual deploy (if workflow unavailable)
cd /path/to/data-platform
DAGS_BUCKET=$(gcloud composer environments describe destaquesgovbr-composer \
  --location=us-central1 \
  --format="value(config.dagGcsPrefix)")

gsutil -m rsync -r -d \
  -x "requirements\.txt$" \
  src/data_platform/dags/ "$DAGS_BUCKET/"
```

**Verification**:
```bash
# Wait 60 seconds for Airflow to parse DAGs
sleep 60

# Verify DAGs are visible
gcloud composer environments run destaquesgovbr-composer \
  --location=us-central1 \
  dags list
```

### Scenario 2: Airflow connections missing

**Cause**: Secrets not properly configured in Secret Manager.

**Diagnosis**:
```bash
# List available connections
gcloud composer environments run destaquesgovbr-composer \
  --location=us-central1 \
  connections list
```

**Fix**:
1. Verify secrets exist in Secret Manager with correct prefix:
   - `airflow-connections-postgres_default`
   - `airflow-connections-huggingface_default`

2. Re-run Terraform in infra repo to sync secrets:
   ```bash
   cd /path/to/infra/terraform
   terraform apply
   ```

### Scenario 3: Composer environment down

**Diagnosis**:
```bash
gcloud composer environments describe destaquesgovbr-composer \
  --location=us-central1 \
  --format="yaml(state,config.softwareConfig.imageVersion)"
```

**If state is UPDATING**:
- Wait for update to complete (can take 30-60 minutes)
- Monitor: `watch -n 30 "gcloud composer environments describe destaquesgovbr-composer --location=us-central1 --format='value(state)'"`

**If state is ERROR**:
1. Check GCP Console for error details
2. Review Cloud Logging for errors
3. Contact GCP Support if needed

---

## Preventive Measures

### Automated Recovery

The following automation is in place:

1. **Health Check** (`composer-health-check.yaml`)
   - Runs every 6 hours
   - Checks if DAGs exist in bucket
   - Auto-triggers deploy if empty

2. **Infrastructure Trigger**
   - When infra repo applies Composer changes
   - Automatically triggers DAG deploy via `repository_dispatch`

3. **Protection**
   - `prevent_destroy = true` in Terraform prevents accidental deletion
   - CI/CD blocks any plan that would replace Composer

### Manual Verification

Run weekly sanity check:
```bash
# Verify DAG count
gh workflow run composer-health-check.yaml --repo destaquesgovbr/data-platform
```

---

## Contacts

| Role | Contact |
|------|---------|
| On-call | Check PagerDuty |
| Platform Team | #data-platform (Slack) |
| GCP Support | console.cloud.google.com/support |

---

## Related Documentation

- [Composer Resilience Plan](../../_plan/COMPOSER_RESILIENCE_PLAN.md)
- [DAG Development Guide](../typesense/development.md)
- [Terraform Infra](https://github.com/destaquesgovbr/infra)
