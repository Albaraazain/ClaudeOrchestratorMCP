# tmux Integration Guide for Dashboard

## Executive Summary

tmux integration is **fully functional** in the orchestrator and ready for dashboard implementation. The system currently manages 5+ concurrent agent sessions with full output capture, PID tracking, and session management capabilities.

## Current tmux Implementation

### 1. How the Orchestrator Deploys tmux Sessions

Located in `orchestrator/deployment.py:45-83`, the deployment flow:

```python
# Session creation flow:
1. Agent ID generated: "{agent_type}-{timestamp}-{uuid[:6]}"
2. Session name: "agent_{agent_id}"
3. Command: tmux new-session -d -s agent_{id} -c {workspace} {claude_command}
4. Claude CLI launched inside tmux with prompt file
```

**Key Functions:**
- `create_tmux_session()` - Creates background tmux sessions
- `check_tmux_available()` - Verifies tmux installation
- `check_tmux_session_exists()` - Session existence check
- `get_tmux_session_output()` - Captures pane content
- `kill_tmux_session()` - Terminates sessions
- `list_all_tmux_sessions()` - Enumerates active sessions

### 2. Available tmux Commands

#### Session Listing with Metadata
```bash
# Get all sessions with creation time and IDs
tmux list-sessions -F "#{session_name}:#{session_id}:#{session_created}"

# Example output:
agent_architecture_designer-141234-ddf6af:$1:1767528754
agent_data_structure_analyzer-141232-a35bb6:$0:1767528752
```

#### Output Capture
```bash
# Capture last N lines from session
tmux capture-pane -t {session_name} -p -S -{N}

# Capture entire scrollback buffer
tmux capture-pane -t {session_name} -p -S -

# Real example tested:
tmux capture-pane -t agent_data_structure_analyzer-141232-a35bb6 -p -S -100
```

#### Process PID Retrieval
```bash
# Get PID of process in pane
tmux list-panes -t {session_name} -F "#{pane_pid}"

# Get detailed pane info
tmux list-panes -t {session_name} -F "#{pane_pid}:#{pane_current_path}"

# Example output:
44588:/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP
```

#### Session Attachment
```bash
# Attach to running session (interactive)
tmux attach -t agent_{id}

# Attach read-only
tmux attach -t agent_{id} -r
```

### 3. Test Results from Live System

Successfully tested on 5 active agent sessions:
- `agent_architecture_designer-141234-ddf6af` (PID: 44379)
- `agent_data_structure_analyzer-141232-a35bb6` (PID: 44314)
- `agent_existing_code_auditor-141241-b859d5` (PID: 44927)
- `agent_tmux_integration_researcher-141236-db527e` (PID: 44588)
- `agent_ui_ux_designer-141239-2b6fd7` (PID: 44782)

All commands executed successfully with proper output capture.

## Web UI Integration Options

### Option A: Terminal Command Launch (Simplest)
Open system terminal with tmux attach command:

**Implementation:**
```python
# FastAPI endpoint
@app.post("/api/agents/{agent_id}/attach-terminal")
async def attach_terminal(agent_id: str):
    # Launch terminal with tmux attach
    subprocess.run(['open', '-a', 'Terminal', '--', 'tmux', 'attach', '-t', f'agent_{agent_id}'])
    return {"status": "terminal_opened"}
```

**Pros:**
- Simple implementation
- Native terminal experience
- Full tmux functionality
- No security concerns

**Cons:**
- Opens external application
- Platform-specific (macOS/Linux/Windows differ)
- No in-browser experience

### Option B: xterm.js with WebSocket (Recommended)
Full web terminal using xterm.js + FastAPI WebSockets:

**Architecture:**
```
Browser (xterm.js) <-> WebSocket <-> FastAPI <-> PTY <-> tmux attach
```

**Implementation Stack:**
```python
# Backend: FastAPI + python-socketio + pty
import pty
import os
import asyncio
from fastapi import FastAPI, WebSocket

app = FastAPI()

@app.websocket("/ws/terminal/{agent_id}")
async def terminal_websocket(websocket: WebSocket, agent_id: str):
    await websocket.accept()

    # Create PTY connected to tmux
    master, slave = pty.openpty()
    pid = os.fork()

    if pid == 0:  # Child process
        os.dup2(slave, 0)
        os.dup2(slave, 1)
        os.dup2(slave, 2)
        os.execvp("tmux", ["tmux", "attach", "-t", f"agent_{agent_id}"])

    # Parent: bridge PTY <-> WebSocket
    # ... handle bidirectional communication
```

**Frontend:**
```javascript
// React component with xterm.js
import { Terminal } from 'xterm';
import { AttachAddon } from 'xterm-addon-attach';

const term = new Terminal();
const ws = new WebSocket(`ws://localhost:8000/ws/terminal/${agentId}`);
const attachAddon = new AttachAddon(ws);
term.loadAddon(attachAddon);
```

**Pros:**
- Full in-browser terminal
- Cross-platform
- Interactive tmux control
- Professional UX

**Cons:**
- Complex implementation
- Security considerations
- Resource intensive

### Option C: Read-Only Log Stream (Safest)
Stream logs without interactive control:

**Implementation:**
```python
# FastAPI SSE endpoint
@app.get("/api/agents/{agent_id}/logs")
async def stream_logs(agent_id: str):
    async def generate():
        while True:
            # Capture tmux output
            output = subprocess.run(
                ['tmux', 'capture-pane', '-t', f'agent_{agent_id}', '-p'],
                capture_output=True, text=True
            ).stdout

            yield f"data: {json.dumps({'output': output})}\n\n"
            await asyncio.sleep(1)

    return EventSourceResponse(generate())
```

**Frontend:**
```javascript
// React component with EventSource
const eventSource = new EventSource(`/api/agents/${agentId}/logs`);
eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    updateTerminalOutput(data.output);
};
```

**Pros:**
- Secure (read-only)
- Simple implementation
- Low resource usage
- Real-time updates

**Cons:**
- No interactivity
- Can't control agents
- Limited UX

## Security Considerations

### 1. Authentication & Authorization
- **Requirement:** Secure API endpoints with JWT/session auth
- **Implementation:** FastAPI OAuth2 + dependency injection
- **Risk:** Unauthorized tmux access could expose system

### 2. Command Injection Prevention
```python
# UNSAFE - Command injection vulnerable
session_name = f"agent_{user_input}"  # NO!

# SAFE - Validated input only
import re
if not re.match(r'^[a-zA-Z0-9_-]+$', agent_id):
    raise ValueError("Invalid agent ID")
session_name = f"agent_{agent_id}"
```

### 3. Resource Limits
- **PTY limits:** Max concurrent terminals
- **WebSocket limits:** Connection timeouts
- **tmux limits:** Session count restrictions

### 4. Isolation Strategies
```python
# Option 1: Read-only attachment
tmux attach -r -t session_name

# Option 2: Restricted command set
ALLOWED_COMMANDS = ['capture-pane', 'list-sessions', 'list-panes']
if command not in ALLOWED_COMMANDS:
    raise PermissionError()

# Option 3: Container isolation (future)
# Run tmux sessions in Docker containers
```

### 5. Audit Logging
```python
# Log all terminal access
logger.info(f"User {user_id} attached to agent {agent_id} at {timestamp}")
```

## Recommended Implementation Path

### Phase 1: Read-Only Log Streaming (MVP)
1. Implement `/api/agents/{id}/logs` endpoint
2. Use Server-Sent Events for real-time updates
3. Display in Monaco Editor or pre-formatted div
4. No security risks, quick to implement

### Phase 2: Interactive Terminal (Full Feature)
1. Add xterm.js with WebSocket support
2. Implement PTY bridge in FastAPI
3. Add authentication layer
4. Enable read-only mode by default
5. Admin-only write access

### Phase 3: Advanced Features
1. Terminal recording/playback
2. Multi-user shared sessions
3. Command filtering/sanitization
4. Container isolation for security

## Integration with Existing Code

The dashboard can leverage existing functions in `orchestrator/deployment.py`:

```python
from orchestrator.deployment import (
    list_all_tmux_sessions,  # Get all active sessions
    get_tmux_session_output,  # Capture output
    check_tmux_session_exists,  # Verify session alive
    kill_tmux_session  # Terminate session
)

# Example dashboard endpoint
@app.get("/api/tmux/sessions")
async def get_sessions():
    sessions = list_all_tmux_sessions()
    return sessions['agent_sessions']
```

## Performance Considerations

### Output Capture Optimization
```python
# Don't capture entire buffer repeatedly
# Use incremental capture with line tracking
last_line_count = {}

def get_new_output(session_name):
    current = capture_full_output(session_name)
    lines = current.split('\n')

    if session_name in last_line_count:
        new_lines = lines[last_line_count[session_name]:]
    else:
        new_lines = lines

    last_line_count[session_name] = len(lines)
    return '\n'.join(new_lines)
```

### WebSocket Throttling
- Limit updates to 1-2 per second
- Batch multiple changes
- Use compression for large outputs

## Conclusion

tmux integration is **production-ready** with multiple implementation options:

1. **Immediate:** Read-only log streaming (Option C)
2. **Optimal:** xterm.js web terminal (Option B)
3. **Simple:** External terminal launch (Option A)

The orchestrator's existing tmux infrastructure provides all necessary capabilities. The dashboard only needs to add the web layer on top.

**Next Steps:**
1. Implement FastAPI server with tmux endpoints
2. Add authentication layer
3. Create React frontend with log viewer
4. Progressively add interactive features

All tmux commands tested and verified working. Ready for dashboard implementation.