FROM python:3.13-slim

# Create non-root user for security compliance
RUN useradd --create-home appuser
WORKDIR /app
RUN chown appuser:appuser /app

# Copy dependency files first (for caching)
COPY pyproject.toml .

# Install project
RUN pip install --no-cache-dir .

# Copy app and set ownership
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8080

CMD ["sh", "-c", "uvicorn src.api.rest.app:app --host 0.0.0.0 --port ${PORT:-8080}"]