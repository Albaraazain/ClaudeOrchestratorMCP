#!/bin/bash
# Dashboard Backend Startup Script
# Activates the virtual environment and starts the server

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Activate venv
if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
    echo "[startup] Activated virtual environment: $PROJECT_ROOT/.venv"
else
    echo "[startup] WARNING: No .venv found at $PROJECT_ROOT/.venv"
    echo "[startup] Run: cd $PROJECT_ROOT && uv venv && uv pip install -r dashboard/backend/requirements.txt"
    exit 1
fi

# Check dependencies
python -c "import fastapi; import uvicorn; import websockets; print('[startup] All dependencies verified')" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "[startup] Installing dependencies..."
    uv pip install -r "$SCRIPT_DIR/requirements.txt"
fi

# Start server
cd "$SCRIPT_DIR"
echo "[startup] Starting FastAPI server on port 8000..."
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
