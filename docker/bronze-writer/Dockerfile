FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential gcc g++ \
    libffi-dev libssl-dev \
    libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock README.md ./

RUN poetry config virtualenvs.create false
RUN poetry install --no-root --no-interaction --no-ansi --without dev

COPY src/ src/
RUN poetry install --no-interaction --no-ansi --without dev

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PORT=8080

EXPOSE 8080

CMD ["uvicorn", "data_platform.workers.bronze_writer.app:app", "--host", "0.0.0.0", "--port", "8080"]
