# Multi-stage Dockerfile for the Renovation Bot
# Optimized for Oracle Cloud Always Free ARM instances (Ampere A1)

FROM python:3.12-slim AS base

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first (better caching)
COPY pyproject.toml ./
COPY src/ ./src/

# Install Python dependencies
RUN pip install --no-cache-dir -e "."

# Copy remaining files
COPY alembic.ini ./
COPY docker/ ./docker/
COPY skills/ ./skills/ 2>/dev/null || true

# Run as non-root user
RUN useradd -m -r botuser && chown -R botuser:botuser /app
USER botuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import asyncio; from bot.config import settings; print('ok')" || exit 1

CMD ["python", "-m", "bot"]
