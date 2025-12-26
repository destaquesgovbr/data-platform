FROM python:3.12-slim

WORKDIR /app

# System dependencies for building Python packages
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc g++ \
    libffi-dev libssl-dev libbz2-dev liblzma-dev \
    libsqlite3-dev libreadline-dev zlib1g-dev \
    libpq-dev \
    curl git \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry

# Copy dependency files first (leverage Docker layer caching)
COPY pyproject.toml poetry.lock README.md ./

# Configure Poetry to not create virtual environments (install globally)
RUN poetry config virtualenvs.create false

# Install dependencies (without the package itself)
RUN poetry install --no-root --no-interaction --no-ansi

# Copy application source code
COPY src/ src/
COPY scripts/ scripts/

# Install the package itself
RUN poetry install --no-interaction --no-ansi

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default command - show help
CMD ["data-platform", "--help"]
