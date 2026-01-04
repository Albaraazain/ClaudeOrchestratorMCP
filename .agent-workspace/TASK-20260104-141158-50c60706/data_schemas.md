# Claude Orchestrator Data Schemas for Dashboard

## Overview
The Claude Orchestrator uses a file-based JSON storage system with JSONL logs for real-time data tracking. All data is stored in the `.agent-workspace/` directory hierarchy.

## MCP Tools Available (21 total)

### Task Management
- `create_real_task` - Create a new orchestration task with phases
- `get_real_task_status` - Get comprehensive task and agent status

### Agent Operations
- `deploy_headless_agent` - Deploy a new Claude agent in tmux session
- `get_agent_output` - Get agent's log output (with truncation options)
- `kill_real_agent` - Terminate a running agent
- `update_agent_progress` - Agent self-reports progress
- `report_agent_finding` - Agent reports discoveries
- `spawn_child_agent` - Agent spawns sub-agent

### Phase Control
- `get_phase_status` - Get current phase status and guidance
- `check_phase_progress` - Check if phase ready for review
- `advance_to_next_phase` - Move to next phase (after approval)
- `submit_phase_for_review` - Submit phase for review
- `approve_phase_review` - Approve phase (blocked - auto-review only)
- `reject_phase_review` - Reject phase (blocked - auto-review only)

### Review System
- `trigger_agentic_review` - Spawn reviewer agents
- `submit_review_verdict` - Reviewer submits verdict
- `get_review_status` - Get review status and verdicts
- `abort_stalled_review` - Cancel stuck review

### Health & Monitoring
- `get_health_status` - Get health monitoring status
- `trigger_health_scan` - Trigger immediate health check
- `get_phase_handover` - Get phase handover document

## Data Structure Schemas

### 1. AGENT_REGISTRY.json (Task-Level Registry)
Located at: `.agent-workspace/TASK-{timestamp}-{uuid}/AGENT_REGISTRY.json`

```json
{
  "task_id": "TASK-20260104-141158-50c60706",
  "task_description": "string - full task description",
  "created_at": "ISO 8601 timestamp",
  "workspace": "/full/path/to/task/workspace",
  "workspace_base": "/full/path/to/.agent-workspace",
  "client_cwd": "/original/client/working/directory",
  "status": "INITIALIZED | ACTIVE | COMPLETED | FAILED",
  "priority": "P0 | P1 | P2 | P3 | P4",

  "phases": [
    {
      "id": "phase-{uuid}",
      "order": 1,  // Sequential order number
      "name": "Investigation",
      "description": "Phase description",
      "status": "PENDING | ACTIVE | AWAITING_REVIEW | UNDER_REVIEW | APPROVED | REJECTED | REVISING | ESCALATED",
      "created_at": "ISO 8601 timestamp",
      "started_at": "ISO 8601 timestamp or null",
      "completed_at": "ISO 8601 timestamp or null"
    }
  ],

  "current_phase_index": 0,  // Index of current active phase

  "agents": [
    {
      "id": "agent_type-timestamp-hash",
      "type": "investigator | builder | fixer | reviewer | etc",
      "tmux_session": "agent_{id}",
      "parent": "orchestrator | parent_agent_id",
      "depth": 1,  // Nesting depth (orchestrator = 0)
      "phase_index": 0,  // Associated phase
      "status": "running | working | blocked | completed | failed | error",
      "started_at": "ISO 8601 timestamp",
      "completed_at": "ISO 8601 timestamp or null",
      "progress": 0,  // 0-100 percentage
      "last_update": "ISO 8601 timestamp",
      "prompt": "First 200 chars of agent prompt...",
      "claude_pid": 12345,  // Process ID if available
      "cursor_pid": 12346,  // Process ID if available
      "tracked_files": {
        "prompt_file": "/path/to/agent_prompt_file.txt",
        "log_file": "/path/to/logs/agent_stream.jsonl",
        "progress_file": "/path/to/progress/agent_progress.jsonl",
        "findings_file": "/path/to/findings/agent_findings.jsonl",
        "deploy_log": "/path/to/logs/deploy_agent.json"
      }
    }
  ],

  "agent_hierarchy": {
    "orchestrator": ["agent1_id", "agent2_id"],
    "agent1_id": ["child1_id", "child2_id"]
  },

  "max_agents": 45,
  "max_depth": 5,
  "max_concurrent": 20,
  "total_spawned": 5,
  "active_count": 5,
  "completed_count": 0,

  "reviews": [
    {
      "review_id": "review-{uuid}",
      "phase_index": 0,
      "status": "pending | in_progress | completed | aborted",
      "started_at": "ISO 8601 timestamp",
      "reviewer_count": 2,
      "verdicts_submitted": 1,
      "final_verdict": "approved | rejected | needs_revision | null"
    }
  ],

  "task_context": {
    "expected_deliverables": ["array", "of", "deliverables"],
    "success_criteria": ["array", "of", "criteria"],
    "relevant_files": ["file", "paths"]
  }
}
```

### 2. GLOBAL_REGISTRY.json (System-Wide Registry)
Located at: `.agent-workspace/registry/GLOBAL_REGISTRY.json`

```json
{
  "created_at": "ISO 8601 timestamp",
  "total_tasks": 38,
  "active_tasks": 10,
  "total_agents_spawned": 162,
  "active_agents": 54,
  "max_concurrent_agents": 20,

  "tasks": {
    "TASK-{timestamp}-{uuid}": {
      "description": "Task description",
      "created_at": "ISO 8601 timestamp",
      "status": "INITIALIZED | ACTIVE | COMPLETED | FAILED"
    }
  }
}
```

### 3. Progress JSONL Format
Located at: `.agent-workspace/TASK-*/progress/{agent_id}_progress.jsonl`

Each line is a JSON object:
```json
{
  "timestamp": "ISO 8601 timestamp",
  "agent_id": "agent_identifier",
  "status": "working | blocked | completed | error",
  "message": "Description of current work",
  "progress": 45  // 0-100 percentage
}
```

### 4. Findings JSONL Format
Located at: `.agent-workspace/TASK-*/findings/{agent_id}_findings.jsonl`

Each line is a JSON object:
```json
{
  "timestamp": "ISO 8601 timestamp",
  "agent_id": "agent_identifier",
  "finding_type": "issue | solution | insight | recommendation",
  "severity": "low | medium | high | critical",
  "message": "Finding description",
  "data": {
    "key": "Additional structured data"
  }
}
```

### 5. Stream Logs JSONL Format
Located at: `.agent-workspace/TASK-*/logs/{agent_id}_stream.jsonl`

Each line is a JSON object with various types:

#### System Init Message
```json
{
  "type": "system",
  "subtype": "init",
  "cwd": "/working/directory",
  "session_id": "uuid",
  "tools": ["array", "of", "available", "tools"]
}
```

#### User/Assistant Messages
```json
{
  "type": "user | assistant",
  "content": "Message content",
  "timestamp": "ISO 8601"
}
```

#### Tool Calls
```json
{
  "type": "tool_call",
  "tool_name": "mcp__claude-orchestrator__update_agent_progress",
  "parameters": {
    "task_id": "...",
    "agent_id": "...",
    "status": "...",
    "message": "...",
    "progress": 50
  }
}
```

#### Tool Results
```json
{
  "type": "tool_result",
  "tool_name": "...",
  "result": {
    // Tool-specific result data
  }
}
```

## Dashboard Data Requirements

### 1. Real-Time Data Streaming
- **WebSocket connections** for live log streaming from agent JSONL files
- **File watchers** on progress/findings JSONL files for real-time updates
- **tmux output capture** for live terminal viewing

### 2. REST API Endpoints Needed
- `GET /tasks` - List all tasks with phase status
- `GET /tasks/{task_id}` - Get detailed task info with agents
- `GET /tasks/{task_id}/agents` - List agents for a task
- `GET /tasks/{task_id}/agents/{agent_id}/logs` - Get agent logs (paginated)
- `GET /tasks/{task_id}/phases` - Get phase status and transitions
- `GET /tmux/sessions` - List all tmux sessions
- `GET /tmux/sessions/{session_id}/output` - Capture tmux pane output
- `POST /tmux/sessions/{session_id}/attach` - Attach to tmux session

### 3. WebSocket Events
- `task:created` - New task created
- `agent:spawned` - New agent deployed
- `agent:progress` - Agent progress update
- `agent:finding` - Agent reported finding
- `agent:completed` - Agent finished
- `phase:changed` - Phase status changed
- `log:update` - New log entries available

### 4. Phase State Machine (8 States)
```
PENDING → ACTIVE → AWAITING_REVIEW → UNDER_REVIEW → APPROVED
                                                 ↓
                                             REJECTED → REVISING → AWAITING_REVIEW

Any state can transition to ESCALATED for human intervention
```

### 5. Data Access Patterns
- **File-based storage**: All data in JSON/JSONL files under `.agent-workspace/`
- **Atomic operations**: Registry updates use file locking (fcntl)
- **Append-only logs**: JSONL files are append-only for concurrent safety
- **No database required**: File system is the database

## Implementation Recommendations

### Backend Architecture
1. **FastAPI server** (separate from MCP server) for REST API
2. **WebSocket support** via FastAPI for real-time updates
3. **File watchers** (watchdog library) to monitor JSONL files
4. **tmux integration** via subprocess for session control
5. **CORS enabled** for frontend access

### Frontend Requirements
1. **React** for component-based UI
2. **WebSocket client** for real-time updates
3. **State management** (Redux/Zustand) for complex state
4. **Virtual scrolling** for large log displays
5. **Phase visualization** with state machine diagram
6. **Terminal emulator** for tmux session viewing

### Key Integration Points
1. **Read registries directly** from JSON files (no MCP calls needed)
2. **Monitor JSONL files** for real-time updates
3. **Use tmux commands** for session management
4. **File locking awareness** when reading registries during updates

## Performance Considerations
- **Log truncation**: Agent logs can be large, use pagination/streaming
- **File watching limits**: Monitor only active task directories
- **WebSocket connection pooling**: Limit concurrent connections
- **Caching**: Cache registry data with short TTL (5-10 seconds)
- **Lazy loading**: Load agent details on demand

## Security Considerations
- **Read-only access** to workspace files
- **Sanitize tmux output** before display
- **Rate limiting** on API endpoints
- **Authentication** for dashboard access
- **No direct MCP tool execution** from dashboard (view-only)