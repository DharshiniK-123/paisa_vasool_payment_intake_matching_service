FROM python:3.13-slim

RUN useradd --create-home appuser
WORKDIR /app
RUN chown appuser:appuser /app

COPY pyproject.toml .

RUN pip install --no-cache-dir .

COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8080

CMD ["sh", "-c", "uvicorn src.api.rest.app:app --host 0.0.0.0 --port ${PORT:-8080}"]