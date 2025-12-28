# PostgreSQL Test Plan - Post Terraform Apply

## Objective
Verify that the Cloud SQL PostgreSQL instance is correctly provisioned and accessible.

## Prerequisites
- Terraform apply completed successfully
- Cloud SQL instance `destaquesgovbr-postgres` is running
- Secrets are created in Secret Manager

## Test Cases

### 1. Infrastructure Validation

#### 1.1 Verify Cloud SQL Instance Exists
```bash
gcloud sql instances describe destaquesgovbr-postgres \
  --format="table(name,state,databaseVersion,region,settings.tier)"
```
**Expected:** Instance should be RUNNABLE with POSTGRES_15

#### 1.2 Verify Database Created
```bash
gcloud sql databases list --instance=destaquesgovbr-postgres
```
**Expected:** Database `govbrnews` with UTF8 charset

#### 1.3 Verify User Created
```bash
gcloud sql users list --instance=destaquesgovbr-postgres
```
**Expected:** User `govbrnews_app` exists

### 2. Secret Manager Validation

#### 2.1 Verify Secrets Exist
```bash
gcloud secrets list --filter="name:govbrnews-postgres"
```
**Expected:** Three secrets:
- govbrnews-postgres-connection-string
- govbrnews-postgres-host
- govbrnews-postgres-password

#### 2.2 Verify Secret Access (Connection String)
```bash
gcloud secrets versions access latest \
  --secret="govbrnews-postgres-connection-string"
```
**Expected:** Valid PostgreSQL connection string format

#### 2.3 Verify Secret Access (Password)
```bash
gcloud secrets versions access latest \
  --secret="govbrnews-postgres-password"
```
**Expected:** Random password (32 characters)

#### 2.4 Verify Secret Access (Host)
```bash
gcloud secrets versions access latest \
  --secret="govbrnews-postgres-host"
```
**Expected:** Private IP address (10.x.x.x format)

### 3. Network Configuration

#### 3.1 Verify Private IP Assigned
```bash
gcloud sql instances describe destaquesgovbr-postgres \
  --format="value(ipAddresses[0].ipAddress)"
```
**Expected:** IP in 10.0.0.0/24 range

#### 3.2 Verify VPC Peering
```bash
gcloud compute networks peerings list --network=destaquesgovbr-network
```
**Expected:** Peering connection to servicenetworking

### 4. Database Connection Tests

#### 4.1 Test Connection via Cloud SQL Proxy
```bash
# Start proxy in background
cloud-sql-proxy inspire-7-finep:southamerica-east1:destaquesgovbr-postgres &
PROXY_PID=$!

# Get password
PASSWORD=$(gcloud secrets versions access latest --secret="govbrnews-postgres-password")

# Test connection
PGPASSWORD=$PASSWORD psql -h 127.0.0.1 -U govbrnews_app -d govbrnews -c "SELECT version();"

# Cleanup
kill $PROXY_PID
```
**Expected:** PostgreSQL version output

#### 4.2 Test Database Accessibility
```bash
cloud-sql-proxy inspire-7-finep:southamerica-east1:destaquesgovbr-postgres &
PROXY_PID=$!

PASSWORD=$(gcloud secrets versions access latest --secret="govbrnews-postgres-password")

PGPASSWORD=$PASSWORD psql -h 127.0.0.1 -U govbrnews_app -d govbrnews -c "\dt"

kill $PROXY_PID
```
**Expected:** Empty list (no tables yet) or success message

#### 4.3 Test Write Permission
```bash
cloud-sql-proxy inspire-7-finep:southamerica-east1:destaquesgovbr-postgres &
PROXY_PID=$!

PASSWORD=$(gcloud secrets versions access latest --secret="govbrnews-postgres-password")

PGPASSWORD=$PASSWORD psql -h 127.0.0.1 -U govbrnews_app -d govbrnews -c "
CREATE TABLE test_connection (
  id SERIAL PRIMARY KEY,
  created_at TIMESTAMP DEFAULT NOW()
);
INSERT INTO test_connection DEFAULT VALUES;
SELECT * FROM test_connection;
DROP TABLE test_connection;
"

kill $PROXY_PID
```
**Expected:** Successful table creation, insert, select, and drop

### 5. IAM and Permissions

#### 5.1 Verify Service Account Access
```bash
# Check data-platform service account has Cloud SQL Client role
gcloud projects get-iam-policy inspire-7-finep \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:destaquesgovbr-data-platform@inspire-7-finep.iam.gserviceaccount.com AND bindings.role:roles/cloudsql.client"
```
**Expected:** Role binding exists

#### 5.2 Verify Secret Access for Service Account
```bash
gcloud secrets get-iam-policy govbrnews-postgres-connection-string \
  --filter="bindings.members:serviceAccount:destaquesgovbr-data-platform@inspire-7-finep.iam.gserviceaccount.com"
```
**Expected:** secretAccessor role binding exists

#### 5.3 Verify GitHub Actions Access
```bash
gcloud projects get-iam-policy inspire-7-finep \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:github-actions@inspire-7-finep.iam.gserviceaccount.com AND bindings.role:roles/cloudsql.client"
```
**Expected:** Role binding exists

### 6. Configuration Validation

#### 6.1 Verify Database Flags
```bash
gcloud sql instances describe destaquesgovbr-postgres \
  --format="value(settings.databaseFlags)"
```
**Expected:** Flags for max_connections, shared_buffers, etc.

#### 6.2 Verify Backup Configuration
```bash
gcloud sql instances describe destaquesgovbr-postgres \
  --format="yaml(settings.backupConfiguration)"
```
**Expected:**
- enabled: true
- startTime: "03:00"
- pointInTimeRecoveryEnabled: true

#### 6.3 Verify Deletion Protection
```bash
gcloud sql instances describe destaquesgovbr-postgres \
  --format="value(settings.deletionProtectionEnabled)"
```
**Expected:** true

## Summary Checklist

- [ ] Cloud SQL instance is RUNNABLE
- [ ] Database `govbrnews` exists
- [ ] User `govbrnews_app` exists
- [ ] All 3 secrets are created and accessible
- [ ] Private IP is assigned in VPC range
- [ ] Connection via Cloud SQL Proxy works
- [ ] Can create/insert/query/drop tables
- [ ] Service accounts have correct IAM roles
- [ ] Backup configuration is enabled
- [ ] Deletion protection is enabled

## Post-Test Actions

After successful validation:
1. Update PROGRESS.md with test results
2. Mark Phase 1 as fully complete
3. Proceed to Phase 2: Create database schema (run create_schema.sql)
