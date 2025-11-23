# Claude Orchestrator MCP - Cursor Setup

## Installation Complete! ✅

The Claude Orchestrator MCP has been added to your Cursor configuration at `~/.cursor/mcp.json`.

## Next Steps

### 1. Restart Cursor
Close and reopen Cursor for the MCP server to be loaded.

### 2. Verify Installation
After restarting Cursor, the orchestrator MCP tools should be available. You can verify by checking if these tools appear:
- `claude-orchestrator` prefix in MCP tools
- `create_real_task`
- `deploy_headless_agent`
- `get_real_task_status`
- etc.

### 3. Using the Orchestrator

#### Create a Task with Dynamic Workspace
```
claude-orchestrator - create_real_task(
    description="Your task description",
    priority="P1",
    client_cwd="/Users/albaraa/Developer/Projects/atomicoat"  # Current project path
)
```

#### Deploy Agents
```
claude-orchestrator - deploy_headless_agent(
    task_id="TASK-...",
    agent_type="investigator",
    prompt="Your agent instructions"
)
```

#### Check Task Status
```
claude-orchestrator - get_real_task_status(task_id="TASK-...")
```

## Configuration Details

### Current Configuration
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

### Python Requirements
Make sure you have the required Python packages installed:
```bash
cd /Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP
pip install -r requirements.txt
```

Or with the virtual environment:
```bash
source venv312/bin/activate
pip install -r requirements.txt
```

## Features

### Multi-Project Support
The orchestrator now works across multiple projects! When you create a task with `client_cwd`, the workspace is created in your project directory:
- Tasks created in: `{client_cwd}/.agent-workspace/TASK-xxx/`
- All tools automatically find tasks regardless of location

### Available Tools
1. **create_real_task** - Create orchestration tasks
2. **deploy_headless_agent** - Deploy background agents
3. **get_real_task_status** - Get task and agent status
4. **get_agent_output** - View agent terminal output
5. **kill_real_agent** - Terminate running agents
6. **update_agent_progress** - Agents report progress
7. **report_agent_finding** - Agents report discoveries

### Current Model
- Engine: Claude Sonnet 4.5 (hardcoded)
- To switch models: Edit `DEFAULT_ENGINE` in `real_mcp_server.py` line 36

## Troubleshooting

### MCP Server Not Loading
1. Check Python path: `which python3`
2. Verify file exists: `ls /Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py`
3. Check Cursor logs for MCP errors

### Tasks Not Found
- Make sure you're passing `client_cwd` parameter when creating tasks
- Check if task exists: `ls ~/.agent-workspace/` or `ls {project}/.agent-workspace/`

### Agent Sessions Terminating
- Fixed! Agents now use command-line arguments instead of stdin
- Make sure MCP server is restarted after recent updates

## Additional Documentation
- `WORKSPACE_SETUP.md` - Workspace location configuration
- `QUICK_REFERENCE.md` - Quick reference guide
- `MODEL_SELECTION.md` - Model configuration details























