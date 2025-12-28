#!/bin/bash
set -e

echo "Starting GovBR News Typesense server..."

# Fetch API key from Secret Manager only if not set or if interpolation failed
# If TYPESENSE_API_KEY is set (including the dev key), use it directly
if [ -z "$TYPESENSE_API_KEY" ] || [ "$TYPESENSE_API_KEY" = '${TYPESENSE_API_KEY}' ]; then
    echo "Fetching Typesense connection config from Secret Manager..."

    # Get access token from metadata service
    ACCESS_TOKEN=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token" \
        -H "Metadata-Flavor: Google" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

    # Get project ID from metadata
    PROJECT_ID=$(curl -s "http://metadata.google.internal/computeMetadata/v1/project/project-id" \
        -H "Metadata-Flavor: Google")

    # Fetch secret from Secret Manager (typesense-write-conn contains JSON with apiKey)
    SECRET_JSON=$(curl -s "https://secretmanager.googleapis.com/v1/projects/${PROJECT_ID}/secrets/typesense-write-conn/versions/latest:access" \
        -H "Authorization: Bearer ${ACCESS_TOKEN}" | python3 -c "import sys,json,base64; print(base64.b64decode(json.load(sys.stdin)['payload']['data']).decode())")

    # Extract apiKey from JSON (supports both new format 'apiKey' and old format 'searchOnlyApiKey')
    TYPESENSE_API_KEY=$(echo "$SECRET_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('apiKey') or d.get('searchOnlyApiKey', ''))")

    if [ -z "$TYPESENSE_API_KEY" ]; then
        echo "ERROR: Failed to fetch API key from Secret Manager"
        exit 1
    fi
    echo "API key fetched successfully from typesense-write-conn"
    # Export for subprocesses (Python scripts)
    export TYPESENSE_API_KEY
fi

# Start Typesense server in the background
echo "Launching Typesense server..."
/opt/typesense-server \
    --data-dir=${TYPESENSE_DATA_DIR:-/data} \
    --api-key=${TYPESENSE_API_KEY} \
    --enable-cors \
    --log-dir=/tmp &

TYPESENSE_PID=$!

# Wait for Typesense to be ready
echo "Waiting for Typesense to be ready..."
max_attempts=30
attempt=1

while [ $attempt -le $max_attempts ]; do
    if curl -s http://localhost:8108/health > /dev/null 2>&1; then
        echo "Typesense is ready!"
        break
    fi
    echo "Attempt ${attempt}/${max_attempts}: Typesense not ready yet..."
    sleep 2
    attempt=$((attempt + 1))
done

if [ $attempt -gt $max_attempts ]; then
    echo "ERROR: Typesense failed to start within expected time"
    exit 1
fi

# Check if data already exists (skip initialization if data directory has collections)
if [ -f "${TYPESENSE_DATA_DIR}/state/db/CURRENT" ]; then
    echo "Data directory contains existing data - skipping initialization"
else
    echo "Fresh data directory detected - running initialization..."

    # Get date range for initial load (default: last 30 days)
    START_DATE=${TYPESENSE_START_DATE:-$(date -d "30 days ago" +%Y-%m-%d 2>/dev/null || date -v-30d +%Y-%m-%d)}
    END_DATE=${TYPESENSE_END_DATE:-$(date +%Y-%m-%d)}

    echo "Running Typesense sync for date range: ${START_DATE} to ${END_DATE}"

    # Use the data-platform CLI to sync data
    cd /app && data-platform sync-typesense \
        --start-date "${START_DATE}" \
        --end-date "${END_DATE}" \
        --full-sync

    echo "Initialization completed!"
fi

# Keep the container running by waiting on the Typesense process
echo "Typesense server is running and ready to accept connections!"
echo "Port: 8108"

wait $TYPESENSE_PID
