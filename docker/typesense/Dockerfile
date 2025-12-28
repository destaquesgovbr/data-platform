# Typesense Sync Job for GovBR News Data Platform
# This image runs the sync job (PostgreSQL → Typesense)
# It does NOT run the Typesense server (that runs on a GCP VM)
FROM python:3.12-slim

# Install build dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy package files
COPY pyproject.toml poetry.lock README.md /app/

# Install poetry and dependencies
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main --no-root

# Copy source code
COPY src/ /app/src/

# Copy entrypoint script
COPY docker/typesense/entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/entrypoint.sh

# Set environment variables
ENV PYTHONPATH=/app/src

# Use custom entrypoint
ENTRYPOINT ["/opt/entrypoint.sh"]

# Default command: run sync with --help
CMD ["data-platform", "sync-typesense", "--help"]
