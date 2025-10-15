# Workspace Location Setup

## Problem
By default, the Claude Orchestrator MCP server creates task workspaces in its own directory (`.agent-workspace` in the ClaudeOrchestratorMCP folder), not in your project directory.

## Solutions

### Option 1: Pass client_cwd parameter (Recommended for multi-project use)
When calling `create_real_task`, pass the current working directory:

```python
# In Claude Code
create_real_task(
    description="Your task description",
    priority="P1",
    client_cwd="/Users/albaraa/Developer/Projects/atomicoat"  # Your project path
)
```

**Advantages:**
- Works dynamically for multiple projects
- No server restart required
- Each project gets its own `.agent-workspace` folder

### Option 2: Set environment variable (For single project)
Set the `CLAUDE_ORCHESTRATOR_WORKSPACE` environment variable before starting the MCP server to specify where task workspaces should be created.

## Setup Steps

### For atomicoat project:

1. **In your MCP server configuration** (e.g., `~/.config/claude/mcp.json` or wherever your MCP config is):

```json
{
  "mcpServers": {
    "claude-orchestrator": {
      "command": "python3",
      "args": ["/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py"],
      "env": {
        "CLAUDE_ORCHESTRATOR_WORKSPACE": "/Users/albaraa/Developer/Projects/atomicoat/.agent-workspace"
      }
    }
  }
}
```

2. **Restart the MCP server** (restart Claude Code or the specific MCP server)

3. **Verify** the workspace location by creating a test task and checking where the workspace appears

### Alternative: Using shell environment

If starting the MCP server from command line:

```bash
export CLAUDE_ORCHESTRATOR_WORKSPACE=/Users/albaraa/Developer/Projects/atomicoat/.agent-workspace
python3 real_mcp_server.py
```

## Result
Task workspaces will now be created in:
- `/Users/albaraa/Developer/Projects/atomicoat/.agent-workspace/TASK-YYYYMMDD-HHMMSS-xxxxxx/`

Instead of:
- `/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/.agent-workspace/TASK-YYYYMMDD-HHMMSS-xxxxxx/`

## Current Behavior
Without this configuration:
- Tasks are created in the orchestrator's directory
- Agents still run commands in the project directory (atomicoat)
- Only the workspace/logs/findings are stored in the wrong location

With this configuration:
- Everything (workspace, logs, findings, agent outputs) goes to your project directory

