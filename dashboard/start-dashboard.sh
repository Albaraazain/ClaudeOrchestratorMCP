#!/bin/bash
# Robust dashboard launcher - starts backend + frontend and opens browser

DASHBOARD_DIR="/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/dashboard"
BACKEND_PORT=8765
FRONTEND_PORT=8766

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting Claude Orchestrator Dashboard...${NC}"

# Kill existing processes on the ports
kill_port() {
    local port=$1
    local pid=$(lsof -ti :$port 2>/dev/null)
    if [ -n "$pid" ]; then
        echo -e "${YELLOW}Killing existing process on port $port (PID: $pid)${NC}"
        kill -9 $pid 2>/dev/null
        sleep 1
    fi
}

kill_port $BACKEND_PORT
kill_port $FRONTEND_PORT

# Start backend
echo -e "${GREEN}Starting backend on port $BACKEND_PORT...${NC}"
cd "$DASHBOARD_DIR/backend"
python3 -m uvicorn main:app --host 0.0.0.0 --port $BACKEND_PORT --reload > /tmp/dashboard-backend.log 2>&1 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Start frontend
echo -e "${GREEN}Starting frontend on port $FRONTEND_PORT...${NC}"
cd "$DASHBOARD_DIR/frontend"
npm run dev -- --port $FRONTEND_PORT > /tmp/dashboard-frontend.log 2>&1 &
FRONTEND_PID=$!
echo "Frontend PID: $FRONTEND_PID"

# Wait for servers to be ready
echo -e "${YELLOW}Waiting for servers to start...${NC}"
MAX_WAIT=30
WAITED=0

# Wait for backend
while ! curl -s http://localhost:$BACKEND_PORT/api/health > /dev/null 2>&1; do
    sleep 1
    WAITED=$((WAITED + 1))
    if [ $WAITED -ge $MAX_WAIT ]; then
        echo -e "${RED}Backend failed to start. Check /tmp/dashboard-backend.log${NC}"
        break
    fi
done

# Wait for frontend
WAITED=0
while ! curl -s http://localhost:$FRONTEND_PORT > /dev/null 2>&1; do
    sleep 1
    WAITED=$((WAITED + 1))
    if [ $WAITED -ge $MAX_WAIT ]; then
        echo -e "${RED}Frontend failed to start. Check /tmp/dashboard-frontend.log${NC}"
        break
    fi
done

# Open browser in new window
echo -e "${GREEN}Opening dashboard in browser...${NC}"
# Try Chrome first (new window), fallback to default browser
if [ -d "/Applications/Google Chrome.app" ]; then
    open -na "Google Chrome" --args --new-window "http://localhost:$FRONTEND_PORT"
elif [ -d "/Applications/Arc.app" ]; then
    open -na "Arc" --args "http://localhost:$FRONTEND_PORT"
else
    open "http://localhost:$FRONTEND_PORT"
fi

echo -e "${GREEN}Dashboard running!${NC}"
echo "  Frontend: http://localhost:$FRONTEND_PORT"
echo "  Backend:  http://localhost:$BACKEND_PORT"
echo ""
echo "Logs:"
echo "  Backend:  tail -f /tmp/dashboard-backend.log"
echo "  Frontend: tail -f /tmp/dashboard-frontend.log"
echo ""
echo "To stop: dashboard-stop"
