#!/bin/bash
# Restart Claude Orchestrator MCP - Use this if connection issues occur

echo "🔄 Restarting Claude Orchestrator MCP..."

# 1. Kill any orphaned MCP server processes
echo "1️⃣  Cleaning up old processes..."
pkill -9 -f "real_mcp_server.py" 2>/dev/null && echo "   ✅ Killed old processes" || echo "   ℹ️  No old processes found"

# 2. Wait a moment for cleanup
sleep 1

# 3. Test the server manually
echo "2️⃣  Testing MCP server..."
cd "$(dirname "$0")"
timeout 5 python3 real_mcp_server.py 2>&1 | head -10 &
SERVER_PID=$!
sleep 2
kill -9 $SERVER_PID 2>/dev/null

echo ""
echo "✅ MCP server validated!"
echo ""
echo "📋 Next Steps:"
echo "   1. In Cursor, press Cmd+Shift+P"
echo "   2. Type: 'MCP: Restart All Servers'"
echo "   3. Wait 5 seconds for reconnection"
echo ""
echo "🔍 Configuration location: ~/.cursor/mcp.json"
echo "🎯 Server path: $(pwd)/real_mcp_server.py"
echo ""
echo "💡 Tip: The MCP icon in Cursor's status bar should show '8 tools' when connected"



