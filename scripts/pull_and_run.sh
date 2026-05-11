#!/usr/bin/env bash
set -euo pipefail

# Pull latest changes and start the FastAPI app (uvicorn)
# Place this script in the project root under scripts/ and run it from there.

# Move to repo root (one level up from scripts)
cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"
echo "Repo root: $REPO_ROOT"

echo "Fetching latest from origin..."
# Try a fast-forward pull first
git fetch origin
if ! git pull --ff-only; then
  echo "Fast-forward pull failed; attempting normal pull..."
  git pull
fi

# Setup venv: prefer existing .venv or venv; create .venv if neither exists
VENV_DIR=""
if [ -d ".venv" ]; then
  VENV_DIR=".venv"
elif [ -d "venv" ]; then
  VENV_DIR="venv"
else
  echo "No virtualenv found. Creating .venv..."
  python3 -m venv .venv
  VENV_DIR=".venv"
fi

# Activate chosen venv
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Install requirements if present
if [ -f requirements.txt ]; then
  echo "Installing requirements..."
  pip install -r requirements.txt
fi

mkdir -p logs run
PIDFILE="run/uvicorn.pid"

# If previous PID exists, try to stop it gracefully
if [ -f "$PIDFILE" ]; then
  OLD_PID=$(cat "$PIDFILE" 2>/dev/null || echo "")
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Stopping existing process $OLD_PID"
    kill "$OLD_PID" || true
    sleep 1
  fi
fi

# Start uvicorn in background and capture PID
echo "Starting uvicorn..."
nohup python -m uvicorn main:app --host 0.0.0.0 --port 8000 > logs/server.log 2>&1 &
NEWPID=$!
echo $NEWPID > "$PIDFILE"
echo "Started uvicorn with PID $NEWPID"
echo "Logs: $REPO_ROOT/logs/server.log"

echo "Done."
