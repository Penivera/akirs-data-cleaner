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

# Note: instead of relying on 'pip' from PATH (which may refer to a system-managed runner),
# we'll call the venv's python explicitly to run pip. This avoids "externally-managed-environment" errors.
VENV_PY="$VENV_DIR/bin/python"

# Ensure pip/setuptools/wheel are available/upgraded inside venv
if [ -f requirements.txt ]; then
  echo "Installing requirements into $VENV_DIR..."

  # If pip isn't available in the venv, attempt to bootstrap it
  if ! "$VENV_PY" -m pip --version >/dev/null 2>&1; then
    echo "pip not found in venv; attempting to bootstrap with ensurepip..."
    if "$VENV_PY" -m ensurepip --upgrade >/dev/null 2>&1; then
      echo "ensurepip succeeded"
    else
      echo "ensurepip failed; attempting to download get-pip.py and install pip"
      TMP_GET_PIP="/tmp/get-pip.py"
      if command -v curl >/dev/null 2>&1; then
        curl -sS https://bootstrap.pypa.io/get-pip.py -o "$TMP_GET_PIP"
      elif command -v wget >/dev/null 2>&1; then
        wget -q -O "$TMP_GET_PIP" https://bootstrap.pypa.io/get-pip.py
      else
        echo "Neither curl nor wget was found; cannot bootstrap pip. Install pip or ensure ensurepip is available." >&2
        exit 1
      fi
      "$VENV_PY" "$TMP_GET_PIP"
    fi
  fi

  # Now upgrade pip/setuptools/wheel and install requirements
  "$VENV_PY" -m pip install --upgrade pip setuptools wheel
  "$VENV_PY" -m pip install -r requirements.txt
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
nohup "$VENV_PY" -m uvicorn main:app --host 0.0.0.0 --port 8000 > logs/server.log 2>&1 &
NEWPID=$!
echo $NEWPID > "$PIDFILE"
echo "Started uvicorn with PID $NEWPID"
echo "Logs: $REPO_ROOT/logs/server.log"
# Open default browser to the app URL
if command -v xdg-open > /dev/null 2>&1; then
  xdg-open "http://localhost:8000"
elif command -v open > /dev/null 2>&1; then
  open "http://localhost:8000"
elif command -v start > /dev/null 2>&1; then
  start "" "http://localhost:8000"
else
  echo "Please open http://localhost:8000 in your browser."
fi
echo "Done."
