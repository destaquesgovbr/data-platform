#!/bin/bash
set -e

echo "Starting GovBR News Typesense Sync Job..."

# Fetch connection config from Secret Manager if running on GCP
# If TYPESENSE_API_KEY is already set, skip this step
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

    # Extract connection details from JSON
    export TYPESENSE_HOST=$(echo "$SECRET_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('host', 'localhost'))")
    export TYPESENSE_PORT=$(echo "$SECRET_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('port', '8108'))")
    export TYPESENSE_API_KEY=$(echo "$SECRET_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('apiKey') or d.get('searchOnlyApiKey', ''))")

    if [ -z "$TYPESENSE_API_KEY" ]; then
        echo "ERROR: Failed to fetch API key from Secret Manager"
        exit 1
    fi
    echo "Connection config fetched successfully"
fi

# Execute the command passed to the container
# Default is "data-platform sync-typesense --help"
exec "$@"
