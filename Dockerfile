FROM python:3.12-slim

# Prevent Python from writing bytecode, enable unbuffered logging, configure uv
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PORT=8080 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Install curl for container health checks
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install dependencies using uv sync with lockfile caching
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Create non-root user and runtime directories with correct permissions
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data /app/uploads /app/cleaned /app/reports /app/logs && \
    chown -R appuser:appuser /app

# Copy application code into container
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/auth || exit 1

CMD ["sh", "-c", "gunicorn main:app -w ${WORKERS:-2} -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:${PORT:-8080} --preload --access-logfile -"]
