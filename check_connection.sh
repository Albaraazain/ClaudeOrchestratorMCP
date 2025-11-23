#!/bin/bash
echo "Checking Claude Orchestrator MCP Status..."
echo ""

# Check if server process is running
if pgrep -f "real_mcp_server.py" > /dev/null; then
    PID=$(pgrep -f "real_mcp_server.py")
    echo "✅ Server Process: RUNNING (PID: $PID)"
else
    echo "❌ Server Process: NOT RUNNING"
fi

# Check recent connections
if [ -f ~/.cursor/logs/mcp.log ]; then
    echo ""
    echo "📊 Recent MCP Activity:"
    tail -5 ~/.cursor/logs/mcp.log 2>/dev/null || echo "   No recent logs"
fi

echo ""
echo "💡 If you see 'Not connected' errors:"
echo "   1. Start a NEW chat in Cursor"
echo "   2. Wait 3 seconds"
echo "   3. Try using the orchestrator tools again"
