# Claude Orchestrator MCP - Quick Start Guide

## 🚀 How to Connect (Once and For All)

### Step 1: Verify Configuration ✅
Your MCP is already configured at: `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "claude-orchestrator": {
      "command": "python3",
      "args": [
        "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py"
      ]
    }
  }
}
```

**✅ This is correct - no changes needed!**

---

### Step 2: Restart MCP in Cursor

**Option A: Quick Restart (Recommended)**
1. Press **`Cmd+Shift+P`** (Command Palette)
2. Type: **`MCP: Restart All Servers`**
3. Wait 5-10 seconds
4. Look for "8 tools" in MCP status

**Option B: Full Cursor Restart**
1. Quit Cursor completely
2. Reopen Cursor
3. Wait for MCP to auto-connect

**Option C: Use the Restart Script**
```bash
./restart_mcp.sh
```
Then do Option A

---

### Step 3: Verify Connection 🔍

**Check 1: MCP Status Bar**
- Bottom of Cursor window
- Should show MCP icon with "8 tools"

**Check 2: Test in Chat**
Ask me: "List all tasks" and I'll use `mcp__claude-orchestrator__get_real_task_status`

**Check 3: Check Logs**
```bash
# Watch MCP logs in real-time
tail -f ~/.cursor/logs/mcp-*.log | grep "claude-orchestrator"
```

---

## 🎯 Using the Orchestrator

### Create a Task (Cross-Project Support!)

```
Create a task to [YOUR TASK] in [PROJECT PATH]
```

**Example:**
```
Create a task to analyze the payment integration 
in /Users/albaraa/Developer/Projects/rop_version_1
```

I'll automatically:
1. Create workspace in your project: `rop_version_1/.agent-workspace/TASK-xxx/`
2. Register it in central location for discoverability
3. Deploy agents that can find it from anywhere

### Deploy an Agent

```
Deploy an investigator agent to analyze [WHAT TO ANALYZE]
```

### Check Status

```
What's the status of task TASK-xxx?
```

or

```
Show me all active tasks
```

---

## 🐛 Troubleshooting

### Issue: "Not connected" Error

**Quick Fix:**
1. Run: `./restart_mcp.sh`
2. In Cursor: `Cmd+Shift+P` → "MCP: Restart All Servers"
3. Try again in 10 seconds

### Issue: Server keeps disconnecting

**Cause:** Multiple server processes running
**Fix:**
```bash
pkill -9 -f "real_mcp_server.py"
# Then restart MCP in Cursor
```

### Issue: Can't find workspace

**This is fixed!** The cross-project workspace discovery fix ensures:
- Tasks created with `client_cwd` are registered in both locations
- `find_task_workspace()` checks multiple registries
- Works across any project

---

## 📊 Available MCP Tools

| Tool | Purpose |
|------|---------|
| `create_real_task` | Create new orchestration task |
| `deploy_headless_agent` | Deploy autonomous agent |
| `get_real_task_status` | Check task status |
| `get_agent_output` | Read agent logs |
| `kill_real_agent` | Terminate agent |
| `update_agent_progress` | Agent self-reporting |
| `report_agent_finding` | Agent findings |
| `spawn_child_agent` | Create sub-agents |

---

## 🎓 Pro Tips

### 1. **Always specify `client_cwd` for project-specific tasks**
```
Create a task to fix authentication 
in /Users/albaraa/Developer/Projects/my-app
```

### 2. **Use descriptive task descriptions**
Good: "Analyze payment integration errors in Ödeal API"
Bad: "Fix bug"

### 3. **Provide context in deliverables**
```
Create a task to optimize database queries with these deliverables:
- Identify slow queries
- Create indexes
- Test performance improvements
```

### 4. **Check agent output for debugging**
```
Show me the output from agent investigator-xxx
```

---

## 🔥 Common Use Cases

### 1. Multi-Project Analysis
```
Create tasks to analyze code quality in:
- /Users/albaraa/Developer/Projects/frontend
- /Users/albaraa/Developer/Projects/backend
- /Users/albaraa/Developer/Projects/mobile
```

All workspaces discoverable from anywhere!

### 2. Complex Refactoring
```
Create a task to refactor authentication system with:
- Investigator: Analyze current implementation
- Architect: Design new system
- Builder: Implement changes
- Tester: Verify functionality
```

### 3. Bug Investigation
```
Create a task to investigate payment integration bug in rop_version_1
with priority P1
```

---

## ⚡ Quick Reference Commands

```bash
# Restart MCP
./restart_mcp.sh

# Check running MCP servers
ps aux | grep real_mcp_server.py

# View MCP logs
tail -f ~/.cursor/logs/mcp-*.log

# View agent output
tail -f ~/.agent-workspace/TASK-xxx/logs/*_stream.jsonl

# Clean up old processes
pkill -9 -f "real_mcp_server.py"
```

---

## 🎉 Success Indicators

You know it's working when:
- ✅ MCP status bar shows "8 tools"
- ✅ I can create tasks via MCP tools
- ✅ Agents deploy successfully
- ✅ Workspaces are found across projects
- ✅ No "not found" errors

---

## 📞 Need Help?

If you see errors:
1. Check logs: `tail -f ~/.cursor/logs/mcp-*.log`
2. Run: `./restart_mcp.sh`
3. Restart Cursor's MCP servers
4. If still broken, restart Cursor completely

---

## 🚀 Ready to Go!

Now try it:
1. **Restart MCP** in Cursor (`Cmd+Shift+P` → "MCP: Restart All Servers")
2. **Wait 10 seconds** for connection
3. **Ask me**: "Create a task to test the orchestrator in rop_version_1"
4. **Watch it work!** 🎯

The cross-project fix is active and ready to use!



