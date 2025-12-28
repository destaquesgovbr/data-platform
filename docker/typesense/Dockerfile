# Typesense with GovBR News Data Platform
FROM typesense/typesense:27.1

# Install Python, pip, and build dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment for Python dependencies
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create app directory
WORKDIR /app

# Copy package files
COPY pyproject.toml poetry.lock /app/

# Install poetry and dependencies
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main

# Copy source code
COPY src/ /app/src/

# Copy entrypoint script
COPY docker/typesense/entrypoint.sh /opt/entrypoint.sh
RUN chmod +x /opt/entrypoint.sh

# Set environment variables for Typesense
# Note: TYPESENSE_API_KEY is not set here - entrypoint fetches from Secret Manager in GCP
ENV TYPESENSE_DATA_DIR=/data
ENV PYTHONPATH=/app/src

# Create data directory
RUN mkdir -p /data

# Expose Typesense port
EXPOSE 8108

# Use custom entrypoint
ENTRYPOINT ["/opt/entrypoint.sh"]
