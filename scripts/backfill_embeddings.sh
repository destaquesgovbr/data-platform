#!/bin/bash
# Backfill embeddings for a date range
#
# Usage:
#   ./scripts/backfill_embeddings.sh START_DATE END_DATE
#
# Example:
#   ./scripts/backfill_embeddings.sh 2025-01-01 2025-01-31
#
# Requirements:
#   - DATABASE_URL environment variable must be set
#   - data-platform CLI must be available (poetry run or Docker)
#
# Phase 4.7: Embeddings Semânticos

set -e  # Exit on error
set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check arguments
if [ $# -ne 2 ]; then
    echo -e "${RED}Error: Missing arguments${NC}"
    echo "Usage: $0 START_DATE END_DATE"
    echo "Example: $0 2025-01-01 2025-01-31"
    exit 1
fi

START_DATE=$1
END_DATE=$2

# Validate date format (YYYY-MM-DD)
if ! [[ $START_DATE =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo -e "${RED}Error: Invalid START_DATE format${NC}"
    echo "Expected: YYYY-MM-DD (e.g., 2025-01-01)"
    exit 1
fi

if ! [[ $END_DATE =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo -e "${RED}Error: Invalid END_DATE format${NC}"
    echo "Expected: YYYY-MM-DD (e.g., 2025-01-31)"
    exit 1
fi

# Check DATABASE_URL
if [ -z "${DATABASE_URL:-}" ]; then
    echo -e "${RED}Error: DATABASE_URL environment variable is not set${NC}"
    exit 1
fi

# Detect execution mode (poetry or docker)
if command -v poetry &> /dev/null; then
    CLI_CMD="poetry run data-platform"
    echo -e "${GREEN}Using Poetry CLI${NC}"
elif command -v docker &> /dev/null && docker images | grep -q data-platform; then
    CLI_CMD="docker run --rm -e DATABASE_URL=\"\$DATABASE_URL\" data-platform:latest data-platform"
    echo -e "${GREEN}Using Docker CLI${NC}"
else
    echo -e "${RED}Error: Neither Poetry nor Docker CLI available${NC}"
    echo "Please install Poetry or build the Docker image"
    exit 1
fi

echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Backfill Embeddings${NC}"
echo -e "${YELLOW}========================================${NC}"
echo "Start date: $START_DATE"
echo "End date:   $END_DATE"
echo ""

# Statistics
total_days=0
successful_days=0
failed_days=0

# Process each day
current_date=$START_DATE
while [[ "$current_date" < "$END_DATE" ]] || [[ "$current_date" == "$END_DATE" ]]; do
    total_days=$((total_days + 1))

    echo -e "${YELLOW}----------------------------------------${NC}"
    echo -e "${YELLOW}Processing: $current_date${NC}"
    echo -e "${YELLOW}----------------------------------------${NC}"

    # Generate embeddings
    if eval $CLI_CMD generate-embeddings --start-date "$current_date" --end-date "$current_date"; then
        echo -e "${GREEN}✓ Embeddings generated successfully${NC}"
    else
        echo -e "${RED}✗ Embedding generation failed${NC}"
        failed_days=$((failed_days + 1))
        # Continue to next date (don't exit on failure)
        current_date=$(date -I -d "$current_date + 1 day" 2>/dev/null || date -v+1d -j -f "%Y-%m-%d" "$current_date" "+%Y-%m-%d")
        continue
    fi

    # Sync to Typesense (optional - check if TYPESENSE_API_KEY is set)
    if [ -n "${TYPESENSE_API_KEY:-}" ]; then
        echo "Syncing to Typesense..."
        if eval $CLI_CMD sync-embeddings-to-typesense --start-date "$current_date" --end-date "$current_date"; then
            echo -e "${GREEN}✓ Typesense sync successful${NC}"
            successful_days=$((successful_days + 1))
        else
            echo -e "${RED}✗ Typesense sync failed${NC}"
            failed_days=$((failed_days + 1))
        fi
    else
        echo -e "${YELLOW}⚠ Skipping Typesense sync (TYPESENSE_API_KEY not set)${NC}"
        successful_days=$((successful_days + 1))
    fi

    # Move to next day
    current_date=$(date -I -d "$current_date + 1 day" 2>/dev/null || date -v+1d -j -f "%Y-%m-%d" "$current_date" "+%Y-%m-%d")
done

# Summary
echo ""
echo -e "${YELLOW}========================================${NC}"
echo -e "${YELLOW}Backfill Summary${NC}"
echo -e "${YELLOW}========================================${NC}"
echo "Total days:      $total_days"
echo -e "${GREEN}Successful:      $successful_days${NC}"
echo -e "${RED}Failed:          $failed_days${NC}"
echo ""

if [ $failed_days -eq 0 ]; then
    echo -e "${GREEN}✓ All days processed successfully!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some days failed. Check logs above.${NC}"
    exit 1
fi
