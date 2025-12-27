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

# Install PyTorch CPU-only version first (smaller image, ~150MB vs ~800MB GPU)
# This must be done before poetry install to override the default torch version
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Install dependencies (without the package itself)
RUN poetry install --no-root --no-interaction --no-ansi

# Copy application source code
COPY src/ src/
COPY scripts/ scripts/

# Install the package itself
RUN poetry install --no-interaction --no-ansi

# Pre-download embedding model to cache in Docker layer (Phase 4.7)
# This saves time on first run and avoids download failures during job execution
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-mpnet-base-v2')"

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default command - show help
CMD ["data-platform", "--help"]
