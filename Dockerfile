FROM python:3.13-slim

WORKDIR /app

# Install only required system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONPATH=/app

# Copy dependency files first (for caching)
COPY pyproject.toml .

# Install project
RUN pip install --no-cache-dir .

# Copy app
COPY . .

EXPOSE 8080

CMD ["sh", "-c", "uvicorn src.api.rest.app:app --host 0.0.0.0 --port ${PORT:-8080}"]