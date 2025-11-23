# Claude Orchestrator - MCP Connection Workarounds

## 🎯 TL;DR

**The orchestrator works perfectly!** The issue is Cursor's MCP connection management closing connections prematurely.

## ✅ What's Working

From your MCP logs and tests:

```
✅ Server starts successfully (FastMCP 2.0)
✅ 8 tools registered and available
✅ create_real_task works (line 568-582 in logs)
✅ deploy_headless_agent works (line 583-597)
✅ get_real_task_status works (line 613-619)
✅ Agent deployment with cursor-agent backend (PID 90345)
✅ Direct Python tests: 6/6 passed
```

## ❌ What's Broken

```
❌ Cursor closes MCP client after chat completion
❌ Tools return "Not connected" after connection drops
❌ Connection doesn't auto-reconnect in same chat
```

**Evidence from logs:**
- Line 620: `Client closed for command`
- Line 623: `Error calling tool 'create_real_task': Not connected`
- Line 1195: `Error calling tool 'get_agent_output': Not connected`

## 🔧 Workarounds

### Method 1: Fresh Chat Sessions (RECOMMENDED)

Each time you want to use the orchestrator:

1. **Start a NEW chat in Cursor** (don't reuse old chat)
2. **Wait 3-5 seconds** for MCP to connect
3. **Use all tools you need in ONE go** 
4. **Don't expect tools to work after chat ends**

**Why this works:** Cursor establishes fresh MCP connections for new chats.

### Method 2: Batch Your Operations

Instead of:
```
❌ Create task
❌ (wait, connection drops)
❌ Deploy agent - FAILS
```

Do this:
```
✅ In ONE chat interaction:
   1. Create task
   2. Deploy agent
   3. Check status
   4. Get output
   All in quick succession before connection drops
```

### Method 3: Use Direct Python (Most Reliable)

For critical operations, bypass Cursor's MCP entirely:

```bash
cd /Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP
python3 << 'EOF'
import real_mcp_server

# Create task
task = real_mcp_server.create_real_task.fn(
    description="My important task",
    priority="P1",
    client_cwd="."
)
print(f"Task created: {task['task_id']}")

# Deploy agent
agent = real_mcp_server.deploy_headless_agent.fn(
    task_id=task['task_id'],
    agent_type="investigator",
    prompt="Your task here",
    parent="orchestrator"
)
print(f"Agent deployed: {agent['agent_id']}")
EOF
```

This ALWAYS works because it doesn't rely on MCP connections.

### Method 4: Check Connection Before Using

Run this before trying to use orchestrator tools:

```bash
./check_connection.sh
```

If server is running but tools fail, start a fresh chat.

## 🐛 Root Cause Analysis

### Why Cursor Closes Connections

From the MCP logs pattern:

1. You use a tool (works fine)
2. Chat interaction completes
3. Cursor decides: "Chat done, cleanup resources"
4. MCP client closes: `Client closed for command`
5. Next tool call in same chat: `Not connected`

This is Cursor's aggressive resource management, not an orchestrator bug.

### Evidence

**Successful sequence** (lines 568-619):
```
[19:59:07] create_real_task → ✅ Success
[19:59:13] deploy_headless_agent → ✅ Success  
[20:00:11] deploy_headless_agent → ✅ Success
[20:00:40] get_real_task_status → ✅ Success
[20:00:55] Client closed for command 👈 CONNECTION DROPS
[20:01:06] create_real_task → ❌ Not connected
```

The server didn't crash. Cursor closed the client.

## 📊 Known Working Scenarios

### ✅ Scenario 1: Direct Python
```python
python3 test_mcp_connection.py
# Result: 6/6 tests passed ✅
```

### ✅ Scenario 2: Fresh MCP Chat
```
New Chat → Wait 3s → Use tools → SUCCESS ✅
(Before chat ends)
```

### ❌ Scenario 3: Reuse Chat After Completion
```
Old Chat → Try to use tools → Not connected ❌
```

## 🎯 Best Practices

1. **For testing:** Use direct Python scripts
2. **For simple tasks:** Fresh chat per task
3. **For complex workflows:** Python automation
4. **For production:** Don't rely on Cursor MCP connection stability

## 📝 Quick Reference Commands

### Test orchestrator health:
```bash
python3 test_mcp_connection.py
```

### Check if server is running:
```bash
./check_connection.sh
```

### Create task directly:
```bash
python3 -c "
import real_mcp_server
result = real_mcp_server.create_real_task.fn(
    description='Test task',
    priority='P2'
)
print(result)
"
```

### Monitor deployed agents:
```bash
ls -la .agent-workspace/TASK-*/output/*.jsonl
```

## 🔮 Future Improvements

Potential fixes (for later):

1. **Keep-alive mechanism** in MCP server
2. **Auto-reconnect logic** in tool wrappers
3. **Connection health monitoring**
4. **Standalone CLI tool** that doesn't rely on MCP

## ✨ Bottom Line

**Your orchestrator is FULLY FUNCTIONAL.** The MCP connection instability is a Cursor issue, not an orchestrator issue. Use the workarounds above until Cursor improves MCP connection management.

---

**Last Updated:** 2025-10-31
**Status:** Server verified working, connection management needs workarounds






