# Comprehensive Analysis of real_mcp_server.py

## Executive Summary

The `real_mcp_server.py` is a sophisticated Model Context Protocol (MCP) server for orchestrating headless Claude agents. Built on FastMCP, it provides comprehensive task management, agent deployment, progress tracking, and anti-spiral protection mechanisms.

**File Statistics:**
- Total Lines: ~6,857 lines
- MCP Tools: 8 tools
- MCP Resources: 3 resources
- Key Helper Functions: 50+ supporting functions

---

## 1. MCP Server Key Features & Capabilities

### Core Capabilities

1. **Task Management**
   - Create orchestration tasks with workspace isolation
   - Enhanced task context (deliverables, success criteria, constraints)
   - Cross-project task management via dual registry system
   - Task validation and parameter sanitization

2. **Agent Deployment**
   - Dual backend support:
     - **tmux + claude CLI**: Original method using tmux sessions
     - **cursor-agent**: Native process management with structured JSON logs
   - Automatic backend selection via `AGENT_BACKEND` environment variable
   - Unique agent ID generation with collision detection
   - Agent deduplication (prevents duplicate agent types)

3. **Progress Tracking & Coordination**
   - Self-reporting via `update_agent_progress` and `report_agent_finding`
   - JSONL-based persistent logging (progress, findings, output streams)
   - Minimal coordination info to prevent log bloat
   - Real-time status updates via `get_real_task_status`

4. **Anti-Spiral Protection**
   - Multi-layer protection:
     - Concurrent agent limit (default: 20)
     - Per-task total limit (default: 45)
     - Maximum depth limit (default: 5)
     - Duplicate agent detection
   - Automatic resource cleanup on agent completion
   - Startup registry validation (zombie detection/cleanup)

5. **Cross-Project Support**
   - Dual global registry updates (local + default)
   - Smart workspace discovery across multiple locations
   - Client workspace support via `client_cwd` parameter
   - Workspace variable resolution (e.g., `${workspaceFolder}`)

6. **Robustness Features**
   - Atomic file locking (`fcntl.flock`) for registry operations
   - Pre-flight checks (disk space, write access)
   - 4-layer agent completion validation
   - Intelligent output truncation for large logs
   - Graceful error handling with cleanup on failures

---

## 2. All Available MCP Tools

### Core Task Management Tools

#### 1. `create_real_task`
**Location:** Lines 3003-3304  
**Purpose:** Create a new orchestration task with workspace and tracking.

**Parameters:**
- `description` (required): Task description
- `priority` (default: "P2"): Priority level (P1, P2, P3, P4)
- `client_cwd` (optional): Client working directory for cross-project tasks
- `background_context` (optional): Background information
- `expected_deliverables` (optional): List of expected outputs
- `success_criteria` (optional): List of completion criteria
- `constraints` (optional): List of constraints
- `relevant_files` (optional): List of relevant file paths
- `conversation_history` (optional): Conversation context

**Features:**
- Validates and sanitizes all parameters
- Creates workspace structure (progress/, logs/, findings/, output/)
- Dual global registry registration for cross-project discovery
- Enhanced context support with validation warnings
- Intelligent conversation history truncation

#### 2. `deploy_headless_agent`
**Location:** Lines 3387-3416 (router), 3419-3848 (tmux), 3852-4276 (cursor)  
**Purpose:** Deploy a headless Claude agent using configured backend.

**Parameters:**
- `task_id` (required): Task ID to deploy agent for
- `agent_type` (required): Type of agent (investigator, fixer, etc.)
- `prompt` (required): Instructions for the agent
- `parent` (default: "orchestrator"): Parent agent ID for hierarchy

**Backend Selection:**
- Automatically routes to `deploy_cursor_agent` if `AGENT_BACKEND='cursor'`
- Falls back to `deploy_claude_tmux_agent` if `AGENT_BACKEND='claude'`

**Features:**
- Anti-spiral checks before deployment
- Unique agent ID generation with collision detection
- Project context detection from client directory
- Task enrichment with enhanced context
- Type-specific requirements injection
- Pre-flight checks (disk space, write access)
- Comprehensive error handling with cleanup

#### 3. `get_real_task_status`
**Location:** Lines 4279-4412  
**Purpose:** Get detailed status of a task and its agents.

**Parameters:**
- `task_id` (required): Task ID to query

**Features:**
- Automatic tmux session detection (marks completed agents)
- Reads progress and findings from JSONL files
- Returns enhanced progress tracking data
- Updates global registry for completed agents
- Returns comprehensive task metadata

**Returns:**
- Task status and description
- Agent counts (total, active, completed)
- Agent hierarchy structure
- Recent progress updates and findings
- Spiral protection status
- Limit configuration

### Agent Management Tools

#### 4. `kill_real_agent`
**Location:** Lines 5734-5881  
**Purpose:** Terminate a running agent (tmux session or cursor-agent process).

**Parameters:**
- `task_id` (required): Task containing the agent
- `agent_id` (required): Agent to terminate
- `reason` (default: "Manual termination"): Reason for termination

**Features:**
- Backend-aware termination:
  - cursor-agent: Kills by PID
  - tmux: Kills tmux session with comprehensive cleanup
- Updates registries atomically
- Performs resource cleanup
- Updates global registry active counts

#### 5. `update_agent_progress`
**Location:** Lines 6462-6625  
**Purpose:** Update agent progress - called by agents themselves to self-report.

**Parameters:**
- `task_id` (required): Task ID
- `agent_id` (required): Agent ID reporting progress
- `status` (required): Current status (working/blocked/completed/etc)
- `message` (required): Status message
- `progress` (default: 0): Progress percentage (0-100)

**Features:**
- Logs progress to JSONL file
- Updates task registry atomically
- **4-layer completion validation** when status='completed':
  1. Workspace evidence (files modified, findings)
  2. Type-specific validation
  3. Message content validation
  4. Progress pattern validation
- Automatic resource cleanup on terminal status
- Returns minimal coordination info (prevents log bloat)
- Updates global registry synchronously

#### 6. `report_agent_finding`
**Location:** Lines 6627-6685  
**Purpose:** Report a finding/discovery - called by agents to share discoveries.

**Parameters:**
- `task_id` (required): Task ID
- `agent_id` (required): Agent ID reporting finding
- `finding_type` (required): Type (issue/solution/insight/recommendation)
- `severity` (required): Severity level (low/medium/high/critical)
- `message` (required): Finding description
- `data` (optional): Additional finding data

**Features:**
- Logs findings to JSONL file
- Returns minimal coordination info
- Enables agent-to-agent coordination

#### 7. `spawn_child_agent`
**Location:** Lines 6687-6702  
**Purpose:** Spawn a child agent - called by agents to create sub-agents.

**Parameters:**
- `task_id` (required): Parent task ID
- `parent_agent_id` (required): ID of parent agent
- `child_agent_type` (required): Type of child agent
- `child_prompt` (required): Prompt for child agent

**Implementation:**
- Delegates to `deploy_headless_agent.fn()` with parent parameter
- Enables hierarchical agent spawning

### Output & Monitoring Tools

#### 8. `get_agent_output`
**Location:** Lines 5277-5732  
**Purpose:** Get agent output from persistent JSONL log files with filtering and truncation.

**Parameters:**
- `task_id` (required): Task ID containing the agent
- `agent_id` (required): Agent ID to get output from
- `tail` (optional): Number of most recent lines (None = all)
- `filter` (optional): Regex pattern to filter lines
- `format` (default: "text"): Output format ("text", "jsonl", "parsed")
- `include_metadata` (default: False): Include file metadata
- `max_bytes` (optional): Maximum total response size
- `aggressive_truncate` (default: False): Use aggressive truncation
- `response_format` (default: "full"): "full", "summary", or "compact"

**Features:**
- **Cursor-agent log parsing**: Special handling for cursor stream-json format
- **Intelligent truncation**: Per-line truncation with JSON-aware logic
- **Smart sampling**: Detects repetitive content and samples intelligently
- **Summary mode**: Extracts only errors, status changes, key findings
- **Efficient tail reading**: Reverse seeking for large files
- **Robust error handling**: Skips malformed JSONL lines

**Output Formats:**
- `text`: Human-readable formatted output
- `jsonl`: Raw JSONL lines
- `parsed`: Rich parsed structure (for cursor-agent logs)

---

## 3. MCP Resources

### Resource: `tasks://list`
**Location:** Lines 6704-6716  
**Purpose:** List all orchestration tasks from global registry.

### Resource: `task://{task_id}/status`
**Location:** Lines 6718-6722  
**Purpose:** Get task details as resource (JSON format).

### Resource: `task://{task_id}/progress-timeline`
**Location:** Lines 6724-6796  
**Purpose:** Get comprehensive progress timeline combining all progress and findings.

---

## 4. Important Implementation Details

### Architecture Patterns

#### File Locking System
**Location:** Lines 65-177 (`LockedRegistryFile` class)

- Uses `fcntl.flock` for exclusive file locking
- Prevents race conditions in concurrent registry access
- Automatic unlock on context exit
- Retry mechanism with timeout

```python
class LockedRegistryFile:
    """Context manager for atomic registry operations"""
    def __enter__(self):
        # Acquire exclusive lock (LOCK_EX)
        # Load registry
        return (registry, file_handle)
```

#### Atomic Registry Operations
**Location:** Lines 184-372

Functions for atomic registry updates:
- `atomic_add_agent()`: Add agent with count updates
- `atomic_update_agent_status()`: Update agent status
- `atomic_increment_counts()`: Increment counters
- `atomic_decrement_active_count()`: Decrement active count
- `atomic_mark_agents_completed()`: Mark multiple as completed

All use `LockedRegistryFile` for thread/process safety.

#### Workspace Discovery
**Location:** Lines 405-490 (`find_task_workspace()`)

Multi-location search strategy:
1. Check default WORKSPACE_BASE (fast path)
2. Search global registries (multiple locations)
3. Read stored workspace locations from registries
4. Fall back to directory-tree search (up to 5 levels)

Enables cross-project task management.

#### Anti-Spiral Protection
**Location:** Lines 3460-3483 (deployment checks)

Multi-layer protection:
1. **Concurrent Limit Check**: `active_count < max_concurrent`
2. **Total Limit Check**: `total_spawned < max_agents`
3. **Duplicate Detection**: Prevents same agent type running
4. **Depth Limit**: Enforced in orchestration guidance

All checks happen before agent deployment.

#### Agent Completion Validation
**Location:** Lines 6224-6461 (`validate_agent_completion()`)

4-layer validation architecture:

1. **Workspace Evidence**:
   - Files modified/created
   - Findings reported
   - Progress entries count

2. **Type-Specific Validation**:
   - Different requirements per agent type
   - Investigator: Must have findings
   - Builder: Must have code changes
   - Fixer: Must reference issues fixed

3. **Message Content Validation**:
   - Evidence keywords detection
   - Minimum message length
   - Completion indicators

4. **Progress Pattern Validation**:
   - Detect fake progress (sudden jumps)
   - Time-based validation
   - Activity verification

Returns confidence score (0-1) with warnings and blocking issues.

#### Intelligent Output Truncation
**Location:** Lines 4717-4827 (`intelligent_sample_lines()`)

- Detects repetitive content (same tool calls)
- Samples intelligently (first N + last N + unique entries)
- Preserves critical information
- Handles large log files efficiently

**Location:** Lines 4828-4900 (`summarize_output()`)

- Extracts only errors, status changes, key findings
- Filters verbose routine operations
- Useful for quick status checks

#### Cursor-Agent Log Parsing
**Location:** Lines 2270-2448 (`parse_cursor_stream_jsonl()`)

Parses cursor-agent's stream-json format:
- Session metadata (ID, model, CWD, duration)
- Events (assistant messages, tool calls, results)
- Tool call parsing (shell, edit, read operations)
- Thinking logs (optional, via `CURSOR_ENABLE_THINKING_LOGS`)

#### Project Context Detection
**Location:** Lines 1307-1605 (`detect_project_context()`)

Detects project configuration:
- Language, frameworks, testing tools
- Package manager
- Project type
- Config files (pyproject.toml, package.json, etc.)

Generates context prompt for agents to understand project conventions.

### Configuration

**Environment Variables:**
- `CLAUDE_ORCHESTRATOR_WORKSPACE`: Workspace base directory
- `CLAUDE_ORCHESTRATOR_MAX_AGENTS`: Max agents per task (default: 45)
- `CLAUDE_ORCHESTRATOR_MAX_CONCURRENT`: Max concurrent agents (default: 20)
- `CLAUDE_ORCHESTRATOR_MAX_DEPTH`: Max hierarchy depth (default: 5)
- `CLAUDE_ORCHESTRATOR_BACKEND`: Agent backend ('claude' or 'cursor', default: 'cursor')
- `CURSOR_AGENT_PATH`: Path to cursor-agent binary
- `CURSOR_AGENT_MODEL`: Model selection (default: 'auto')
- `CURSOR_AGENT_FLAGS`: Additional flags (default: '--approve-mcps --force')
- `CURSOR_ENABLE_THINKING_LOGS`: Enable thinking logs (default: 'false')

### Error Handling

- Comprehensive try/except blocks
- Resource cleanup on failures
- Graceful degradation (e.g., fallback to tmux if cursor-agent unavailable)
- Validation warnings (non-fatal)
- Blocking issues (prevent operations)

---

## 5. Task Management & Agent Coordination

### Task Lifecycle

1. **Creation** (`create_real_task`):
   - Validates parameters
   - Creates workspace structure
   - Initializes task registry
   - Registers in global registry (dual registration for cross-project)

2. **Agent Deployment** (`deploy_headless_agent`):
   - Anti-spiral checks
   - Generates unique agent ID
   - Builds comprehensive agent prompt
   - Deploys via selected backend
   - Updates registries atomically

3. **Agent Execution**:
   - Agents self-report via `update_agent_progress`
   - Agents share findings via `report_agent_finding`
   - System provides coordination info on each call
   - Progress/findings logged to JSONL files

4. **Completion Detection**:
   - Self-reporting: Agent calls `update_agent_progress` with status='completed'
   - Auto-detection: `get_real_task_status` checks tmux sessions
   - Validation: 4-layer completion validation
   - Cleanup: Automatic resource cleanup

5. **Termination** (`kill_real_agent`):
   - Backend-aware termination
   - Registry updates
   - Resource cleanup

### Coordination Mechanism

**Minimal Coordination Info** (Lines 6156-6212):
- Prevents log bloat by returning compact status
- Includes:
  - Agent counts
  - Recent progress (last 5 updates)
  - Recent findings (last 3 findings)
  - Agent status summary

**Self-Reporting Pattern:**
1. Agent calls `update_agent_progress` or `report_agent_finding`
2. System logs to JSONL file
3. System updates registry
4. System returns minimal coordination info
5. Agent receives status of other agents for coordination

**Benefits:**
- Real-time coordination without polling
- Efficient (minimal data transfer)
- Persistent (JSONL logs)
- Fault-tolerant (graceful handling of missing agents)

### Registry Structure

**Task Registry** (`AGENT_REGISTRY.json`):
```json
{
  "task_id": "TASK-...",
  "task_description": "...",
  "created_at": "...",
  "workspace": "...",
  "status": "INITIALIZED",
  "priority": "P2",
  "agents": [...],
  "agent_hierarchy": {...},
  "max_agents": 45,
  "max_depth": 5,
  "max_concurrent": 20,
  "total_spawned": 0,
  "active_count": 0,
  "completed_count": 0,
  "task_context": {...},  // Enhanced context if provided
  "spiral_checks": {...}
}
```

**Global Registry** (`GLOBAL_REGISTRY.json`):
```json
{
  "created_at": "...",
  "total_tasks": 0,
  "active_tasks": 0,
  "total_agents_spawned": 0,
  "active_agents": 0,
  "max_concurrent_agents": 20,
  "tasks": {
    "TASK-xxx": {
      "description": "...",
      "workspace": "...",
      "workspace_base": "...",
      "status": "INITIALIZED",
      "cross_project_reference": true
    }
  },
  "agents": {
    "agent-xxx": {
      "task_id": "...",
      "status": "...",
      "type": "..."
    }
  }
}
```

### Workspace Structure

```
.agent-workspace/
├── TASK-{timestamp}-{id}/
│   ├── AGENT_REGISTRY.json       # Task-specific registry
│   ├── progress/                 # Progress JSONL files
│   │   └── {agent_id}_progress.jsonl
│   ├── findings/                 # Findings JSONL files
│   │   └── {agent_id}_findings.jsonl
│   ├── logs/                     # Agent output streams
│   │   └── {agent_id}_stream.jsonl
│   └── output/                   # Agent outputs
├── registry/
│   └── GLOBAL_REGISTRY.json      # Global registry
```

---

## Key Design Decisions

1. **Dual Backend Support**: Flexibility to use either tmux+claude or cursor-agent based on environment
2. **Atomic File Locking**: Prevents race conditions in concurrent access
3. **JSONL-Based Logging**: Persistent, append-only logs for progress/findings
4. **Minimal Coordination Info**: Prevents log bloat while enabling coordination
5. **Cross-Project Support**: Dual registry registration enables task discovery across projects
6. **4-Layer Validation**: Ensures agent completion claims are legitimate
7. **Intelligent Truncation**: Handles large logs efficiently without losing critical info
8. **Anti-Spiral Protection**: Multiple layers prevent runaway agent spawning

---

## Summary

The `real_mcp_server.py` is a production-ready MCP server with:
- **8 MCP tools** for comprehensive task and agent management
- **3 MCP resources** for task listing and monitoring
- **Robust architecture** with atomic operations, file locking, and error handling
- **Advanced features** like cross-project support, intelligent truncation, and completion validation
- **Flexible deployment** with dual backend support
- **Effective coordination** via self-reporting and minimal status updates

The server demonstrates sophisticated design patterns for distributed agent orchestration while maintaining safety through anti-spiral protection and validation mechanisms.
