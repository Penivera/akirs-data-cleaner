#!/bin/bash
set -e

# If custom command line arguments were provided, execute them directly
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

CELERY_PID=""
WEB_PID=""

# Graceful termination handler
cleanup() {
    echo "[start.sh] Received stop signal, stopping processes..."
    if [ -n "$CELERY_PID" ] && kill -0 "$CELERY_PID" 2>/dev/null; then
        echo "[start.sh] Stopping Celery worker (PID: $CELERY_PID)..."
        kill -TERM "$CELERY_PID" 2>/dev/null || true
    fi
    if [ -n "$WEB_PID" ] && kill -0 "$WEB_PID" 2>/dev/null; then
        echo "[start.sh] Stopping Web server (PID: $WEB_PID)..."
        kill -TERM "$WEB_PID" 2>/dev/null || true
    fi
    wait
    echo "[start.sh] All processes exited."
    exit 0
}

trap cleanup SIGINT SIGTERM

# Start Celery worker in background if enabled (default: true)
if [ "${START_CELERY_WORKER:-true}" = "true" ]; then
    echo "[start.sh] Starting Celery worker (concurrency: ${CELERY_CONCURRENCY:-2})..."
    celery -A app.tasks worker \
        --loglevel="${CELERY_LOG_LEVEL:-INFO}" \
        --concurrency="${CELERY_CONCURRENCY:-2}" &
    CELERY_PID=$!
fi

# Start Web server in background so signal traps work
echo "[start.sh] Starting Gunicorn web server on port ${PORT:-8080}..."
gunicorn main:app \
    -w "${WORKERS:-2}" \
    -k uvicorn.workers.UvicornWorker \
    --bind "0.0.0.0:${PORT:-8080}" \
    --access-logfile - &
WEB_PID=$!

# Wait for any process to exit
wait -n "$WEB_PID" "$CELERY_PID" 2>/dev/null || wait "$WEB_PID"

# If web server exited first, trigger cleanup
cleanup
