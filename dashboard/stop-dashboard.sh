#!/bin/bash
# Stop dashboard processes

echo "Stopping dashboard..."
pkill -f 'uvicorn main:app.*8765' 2>/dev/null
pkill -f 'node.*vite.*8766' 2>/dev/null
pkill -f 'esbuild.*8766' 2>/dev/null

# Verify
sleep 1
if lsof -ti :8765 > /dev/null 2>&1 || lsof -ti :8766 > /dev/null 2>&1; then
    echo "Force killing remaining processes..."
    lsof -ti :8765 | xargs kill -9 2>/dev/null
    lsof -ti :8766 | xargs kill -9 2>/dev/null
fi

echo "Dashboard stopped."
