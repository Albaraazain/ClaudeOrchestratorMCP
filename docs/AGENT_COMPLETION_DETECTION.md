# Agent Completion Detection

## Overview

The orchestrator tracks active agent counts automatically through multiple detection mechanisms. When an agent finishes its work, the active agent count is decremented and the completed count is incremented in both the task-specific and global registries.

## Detection Mechanisms

### 1. Self-Reporting via `update_agent_progress`

**How it works:**
- Agents call `update_agent_progress` with `status='completed'` when they finish
- The system tracks the previous status and detects state transitions
- When transitioning from active status to terminal status, counts are updated

**Implementation:**
```python
# Active statuses: running, working, blocked
# Terminal statuses: completed, terminated, error, failed

if previous_status in active_statuses and status in terminal_statuses:
    registry['active_count'] = max(0, registry['active_count'] - 1)
    registry['completed_count'] = registry['completed_count'] + 1
    
    # Also update global registry
    global_reg['active_agents'] = max(0, global_reg['active_agents'] - 1)
```

**Location:** `update_agent_progress()` function (lines ~1981-2016)

### 2. Tmux Session Monitoring via `get_real_task_status`

**How it works:**
- When task status is queried, the system checks if tmux sessions still exist
- If an agent's tmux session has terminated but status is still 'running', it's marked as completed
- This catches agents that terminated without self-reporting

**Implementation:**
```python
for agent in registry['agents']:
    if agent['status'] == 'running' and 'tmux_session' in agent:
        if not check_tmux_session_exists(agent['tmux_session']):
            agent['status'] = 'completed'
            agent['completed_at'] = datetime.now().isoformat()
            registry['active_count'] = max(0, registry['active_count'] - 1)
            registry['completed_count'] = registry['completed_count'] + 1
            # Also update global registry
```

**Location:** `get_real_task_status()` function (lines ~1351-1387)

### 3. Manual Termination via `kill_real_agent`

**How it works:**
- When an agent is manually terminated, counts are updated immediately
- Only decrements if the agent was in an active status (prevents double-counting)

**Implementation:**
```python
previous_status = agent.get('status')
agent['status'] = 'terminated'
agent['terminated_at'] = datetime.now().isoformat()

# Only decrement if agent was in active status
if previous_status in active_statuses:
    registry['active_count'] = max(0, registry['active_count'] - 1)
    # Also update global registry
```

**Location:** `kill_real_agent()` function (lines ~1546-1579)

## Dual Registry System

The system maintains two registries that must stay in sync:

### 1. Task-Specific Registry
- **Location:** `<workspace>/<task_id>/AGENT_REGISTRY.json`
- **Contains:** All agents for a specific task
- **Tracks:** `active_count`, `completed_count`, `total_spawned`

### 2. Global Registry
- **Location:** `<workspace>/registry/GLOBAL_REGISTRY.json`
- **Contains:** All agents across all tasks
- **Tracks:** `active_agents`, `total_agents_spawned`

Both registries are updated synchronously when agent status changes.

## Agent Status Lifecycle

```
                    ┌──────────────┐
                    │  deployed    │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   running    │◄──┐ Active
                    └──────┬───────┘   │ Statuses
                           │           │
                    ┌──────▼───────┐   │
                    │   working    ├───┘
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   blocked    │
                    └──────┬───────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
  ┌──────▼───────┐  ┌──────▼───────┐  ┌──────▼───────┐
  │  completed   │  │  terminated  │  │    error     │  Terminal
  └──────────────┘  └──────────────┘  └──────────────┘  Statuses
```

**Active Count Decremented When:**
- Transition from any active status (`running`, `working`, `blocked`) 
- To any terminal status (`completed`, `terminated`, `error`, `failed`)

**Double-Counting Prevention:**
- System tracks `previous_status` before updating
- Only decrements if transitioning FROM active status
- Uses `max(0, count - 1)` to prevent negative counts

## Validation on Completion

When an agent reports completion, the system performs 4-layer validation:

1. **Workspace Evidence:** Files modified, progress entries count, findings reported
2. **Type-Specific Validation:** Different requirements per agent type (investigator, builder, fixer)
3. **Message Content Validation:** Evidence keywords, suspicious phrases, minimum length
4. **Progress Pattern Validation:** Time elapsed, update frequency, working status updates

**Results stored in:**
```json
{
  "completion_validation": {
    "confidence": 0.85,
    "warnings": ["Only 2 progress updates - expected at least 3"],
    "blocking_issues": [],
    "evidence_summary": {
      "workspace_evidence": { "modified_files_count": 5 },
      "type_specific": { "findings_ok": true },
      "message_validation": { "evidence_keywords_found": ["created", "verified"] },
      "progress_pattern": { "speed": "reasonable" }
    },
    "validated_at": "2025-10-16T10:30:00.123456"
  }
}
```

## Logging

All count updates are logged for debugging:

```python
logger.info(f"Agent {agent_id} transitioned from {previous_status} to {status}. Active count: {registry['active_count']}")
logger.info(f"Global registry updated: Active agents: {global_reg['active_agents']}")
logger.info(f"Detected agent {agent_id} completed (tmux session terminated)")
```

## Error Handling

- All registry updates wrapped in try-except blocks
- Failed global registry updates logged but don't block task registry updates
- Uses `max(0, count)` to prevent negative counts
- Graceful degradation if files don't exist or are corrupted

## Usage Examples

### For Agents (Self-Reporting)

```python
# When starting work
update_agent_progress(
    task_id="TASK-20251016-123456-abc123",
    agent_id="investigator-103045-a1b2c3",
    status="working",
    message="Starting investigation of codebase patterns",
    progress=10
)

# During work
update_agent_progress(
    task_id="TASK-20251016-123456-abc123",
    agent_id="investigator-103045-a1b2c3",
    status="working",
    message="Found 5 key patterns in authentication code",
    progress=50
)

# When completing
update_agent_progress(
    task_id="TASK-20251016-123456-abc123",
    agent_id="investigator-103045-a1b2c3",
    status="completed",
    message="Investigation complete. Analyzed 15 files, found 8 patterns, documented 5 findings.",
    progress=100
)
# This automatically decrements active_count and increments completed_count
```

### For Monitoring

```python
# Check task status (also detects terminated sessions)
status = get_real_task_status(task_id="TASK-20251016-123456-abc123")
print(f"Active agents: {status['agents']['active']}")
print(f"Completed agents: {status['agents']['completed']}")

# Manually terminate an agent
kill_real_agent(
    task_id="TASK-20251016-123456-abc123",
    agent_id="investigator-103045-a1b2c3",
    reason="Agent stuck, exceeded time limit"
)
# This also updates active_count
```

## Benefits

1. **Accurate Tracking:** Multiple detection mechanisms ensure counts stay accurate
2. **Automatic Updates:** Agents self-report, system auto-detects terminations
3. **No Double-Counting:** State transition tracking prevents counting the same completion twice
4. **Dual Registry Sync:** Both task-specific and global registries stay in sync
5. **Validation:** Completion claims are validated to ensure quality
6. **Auditability:** All transitions logged with timestamps
7. **Fault Tolerance:** Graceful error handling, negative count prevention


