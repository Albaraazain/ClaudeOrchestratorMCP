# Dashboard Integration Points Document

## Executive Summary
The existing orchestrator uses FastMCP with stdio/JSON-RPC protocol, not HTTP. This means we cannot add HTTP endpoints directly to the MCP server. A separate REST API server is required to expose data to the dashboard.

## Current Architecture

### 1. MCP Server (real_mcp_server.py)
- **Protocol**: stdio/JSON-RPC (not HTTP)
- **Port**: None (uses stdin/stdout)
- **Framework**: FastMCP
- **Entry Point**: `mcp.run()` at line 4536
- **Tools Count**: 21 MCP tools

### 2. Data Storage
- **Location**: `.agent-workspace/TASK-*/`
- **Formats**:
  - `AGENT_REGISTRY.json` - Main task/agent/phase registry
  - `progress/*.jsonl` - Agent status updates
  - `findings/*.jsonl` - Agent discoveries
  - `logs/*.stream-json` - Full agent logs with tool calls
  - `GLOBAL_REGISTRY.json` - System-wide task registry

### 3. Existing Modules (orchestrator/)
Comprehensive Python modules that can be reused:

| Module | Purpose | Key Functions |
|--------|---------|---------------|
| `registry.py` | Registry management | `LockedRegistryFile`, `read_registry_with_lock()`, `write_registry_with_lock()` |
| `workspace.py` | Workspace operations | `find_task_workspace()`, `ensure_workspace()` |
| `deployment.py` | tmux management | `create_tmux_session()`, `get_tmux_session_output()`, `kill_tmux_session()` |
| `status.py` | Log processing | `read_jsonl_lines()`, `parse_jsonl_lines()`, `smart_preview_truncate()` |
| `lifecycle.py` | Coordination | `get_comprehensive_coordination_info()`, `get_minimal_coordination_info()` |
| `health_daemon.py` | Health monitoring | `HealthDaemon` class with background monitoring |
| `tasks.py` | Task validation | `validate_task_parameters()`, `calculate_task_complexity()` |
| `review.py` | Review system | Review management functions |
| `handover.py` | Phase handovers | Phase transition documentation |

### 4. tmux Integration
- **Active Sessions**: Format `agent_{agent_type}-{id}`
- **Commands Available**:
  - `tmux list-sessions -F` - List all sessions with metadata
  - `tmux capture-pane -p -S - -t {session}` - Capture output
  - `tmux list-panes -F '#{pane_pid}'` - Get process PIDs
  - `tmux kill-session -t {session}` - Terminate session
  - `tmux send-keys -t {session}` - Send commands

## Missing Components for Dashboard

### 1. REST API Server (FastAPI)
**Needs to be built from scratch**
- HTTP endpoints to expose MCP data
- File system access to read `.agent-workspace/`
- Reuse orchestrator modules for data access
- Port: Suggest 8000 (configurable)

### 2. WebSocket Server
**Needs to be built**
- Real-time log streaming
- Agent status updates
- Phase transitions
- Can be integrated into FastAPI

### 3. File Watchers
**Needs implementation**
- Watch `.agent-workspace/TASK-*/` for changes
- Monitor JSONL file appends
- Detect new tasks/agents
- Trigger WebSocket broadcasts

### 4. React Frontend
**Needs to be built from scratch**
- No existing UI code found
- Will consume REST API and WebSocket
- Suggested libraries: Vite, React 18, TanStack Query, Socket.io-client

## Integration Strategy

### Option 1: Separate API Server (Recommended)
```python
# dashboard_api.py
from fastapi import FastAPI
from fastapi.websockets import WebSocket
import asyncio
from pathlib import Path
from orchestrator.registry import read_registry_with_lock
from orchestrator.workspace import find_task_workspace
from orchestrator.status import read_jsonl_lines

app = FastAPI()

@app.get("/api/tasks")
async def get_tasks():
    # Read from GLOBAL_REGISTRY.json
    pass

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    # Use find_task_workspace() and read_registry_with_lock()
    pass

@app.websocket("/ws/logs/{task_id}/{agent_id}")
async def stream_logs(websocket: WebSocket, task_id: str, agent_id: str):
    # Watch and stream JSONL files
    pass
```

### Option 2: Proxy MCP Calls (Not Recommended)
- Would require complex stdio/JSON-RPC to HTTP translation
- Adds unnecessary complexity
- MCP tools not designed for web consumption

### Option 3: Direct File System Access (Simple but Limited)
- Frontend directly reads JSON files
- No real-time updates without polling
- Security concerns with file system exposure
- Not scalable

## Recommended Implementation Path

1. **Create FastAPI Backend** (`dashboard_api.py`)
   - Import and reuse orchestrator modules
   - Expose REST endpoints for all MCP tool equivalents
   - Add WebSocket endpoints for real-time data

2. **Implement File Watching**
   - Use `watchdog` library or `asyncio` file monitoring
   - Watch `.agent-workspace/` for changes
   - Broadcast updates via WebSocket

3. **Build React Dashboard**
   - Create Vite + React project
   - Use TanStack Query for data fetching
   - Socket.io-client for WebSocket connection
   - xterm.js for terminal emulation (tmux output)

4. **Security Considerations**
   - Add authentication to API endpoints
   - Validate tmux session access
   - Sanitize file paths
   - Rate limit API calls

## API Endpoints Needed

### Tasks
- `GET /api/tasks` - List all tasks
- `GET /api/tasks/{task_id}` - Get task details
- `GET /api/tasks/{task_id}/agents` - List task agents
- `GET /api/tasks/{task_id}/phases` - Get phase status

### Agents
- `GET /api/agents/{task_id}/{agent_id}` - Get agent details
- `GET /api/agents/{task_id}/{agent_id}/logs` - Get agent logs
- `GET /api/agents/{task_id}/{agent_id}/findings` - Get findings
- `DELETE /api/agents/{task_id}/{agent_id}` - Kill agent

### tmux Sessions
- `GET /api/tmux/sessions` - List all sessions
- `GET /api/tmux/sessions/{session}/output` - Get session output
- `POST /api/tmux/sessions/{session}/command` - Send command
- `DELETE /api/tmux/sessions/{session}` - Kill session

### WebSocket
- `WS /ws/tasks` - Real-time task updates
- `WS /ws/logs/{task_id}/{agent_id}` - Stream agent logs
- `WS /ws/tmux/{session}` - Stream tmux output

## File Structure Proposal
```
ClaudeOrchestratorMCP/
├── dashboard/
│   ├── backend/
│   │   ├── main.py                 # FastAPI app
│   │   ├── api/
│   │   │   ├── tasks.py           # Task endpoints
│   │   │   ├── agents.py          # Agent endpoints
│   │   │   └── tmux.py            # tmux endpoints
│   │   ├── websocket/
│   │   │   ├── handlers.py        # WebSocket handlers
│   │   │   └── watchers.py        # File watchers
│   │   └── requirements.txt
│   └── frontend/
│       ├── package.json
│       ├── vite.config.js
│       ├── src/
│       │   ├── App.jsx
│       │   ├── api/               # API client
│       │   ├── components/        # React components
│       │   └── hooks/             # Custom hooks
│       └── public/
```

## Next Steps

1. **Phase 2 (Backend Implementation)**:
   - Set up FastAPI project structure
   - Implement REST endpoints
   - Add WebSocket support
   - Create file watchers

2. **Phase 3 (Frontend Implementation)**:
   - Initialize React project with Vite
   - Build UI components
   - Connect to API and WebSocket
   - Add xterm.js for terminal

3. **Phase 4 (Integration & Testing)**:
   - Test real-time updates
   - Verify tmux integration
   - Add error handling
   - Performance optimization

## Conclusion

The orchestrator has excellent Python infrastructure but lacks web exposure. A separate FastAPI server is the cleanest approach to bridge this gap, reusing the existing orchestrator modules for data access while providing HTTP/WebSocket interfaces for the dashboard.