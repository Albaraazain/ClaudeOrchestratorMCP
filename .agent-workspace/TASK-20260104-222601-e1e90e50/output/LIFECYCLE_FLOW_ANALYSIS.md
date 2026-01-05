# Task and Agent Lifecycle Flow Analysis

## Executive Summary

The dashboard shows incorrect active task counts (7 active when 0 are running) due to fundamental lifecycle management issues. Task statuses never transition properly, and global registry counts only increment without ever decrementing.

## Current Broken Flow

### 1. Task Creation (`create_real_task`)
- **Location**: `real_mcp_server.py:475`
- **Issue**: Sets `status = "INITIALIZED"` and increments `active_tasks` in GLOBAL_REGISTRY.json
- **Problem**: Status never transitions from INITIALIZED

### 2. Agent Deployment (`deploy_agent`)
- **Location**: `real_mcp_server.py:700-1100`
- **Issue**: Increments `active_agents` in both AGENT_REGISTRY.json and GLOBAL_REGISTRY.json
- **Problem**: Global counts only increment

### 3. Agent Progress Updates (`update_agent_progress`)
- **Location**: `real_mcp_server.py:3065-3300`
- **Issue**: Only decrements local AGENT_REGISTRY `active_count`, not global counts
- **Problem**: GLOBAL_REGISTRY.json counts never decrement

### 4. Global Registry State
- **Location**: `.agent-workspace/registry/GLOBAL_REGISTRY.json`
- **Current State**:
  - `active_tasks: 44` (should be 0-1)
  - `active_agents: 102` (should be 0-5)
  - All tasks show `status: "INITIALIZED"`

### 5. Dashboard Backend
- **Location**: `dashboard/backend/api/routes/tasks.py:446-465`
- **Issue**: Reads from stale JSON files instead of SQLite
- **Problem**: Counts active agents from outdated registry data

### 6. Dashboard Frontend
- **Location**: `dashboard/frontend/src/pages/Dashboard.tsx:102`
- **Issue**: `tasks.filter(t => t.active_agents && t.active_agents > 0).length`
- **Problem**: Determines "active" based on agent count, not task status

## Root Causes

1. **No Task Status Lifecycle**: Tasks created as INITIALIZED but never transition to ACTIVE or COMPLETED
2. **One-Way Counters**: Global registry counters only increment, never decrement
3. **Wrong Data Source**: Dashboard reads from JSON files instead of SQLite truth
4. **Wrong Logic**: Frontend uses agent counts instead of task status to determine active tasks

## Correct Flow Design

### Task Status State Machine
```
INITIALIZED -> ACTIVE -> COMPLETED
     ↑           ↓          ↓
  (created)  (1st agent)  (all done)
```

### Proper Count Management
1. When agent completes: Decrement both local AND global `active_agents`
2. When all agents complete: Transition task to COMPLETED, decrement `active_tasks`
3. When first agent starts: Transition task from INITIALIZED to ACTIVE

### Data Source Architecture
```
SQLite (state_db.py) = Source of Truth
    ↓
JSON files = Optional caches/logs
    ↓
Dashboard API = Read from SQLite
```

## Required Fixes

### Fix 1: Task Status Transitions
**File**: `real_mcp_server.py`
- In `deploy_agent`: When first agent deployed, transition task from INITIALIZED to ACTIVE
- In `update_agent_progress`: When all agents complete, transition task to COMPLETED

### Fix 2: Global Registry Decrements
**File**: `real_mcp_server.py:update_agent_progress`
- When agent transitions to terminal state: Decrement GLOBAL_REGISTRY `active_agents`
- When task completes: Decrement GLOBAL_REGISTRY `active_tasks`

### Fix 3: Dashboard API SQLite Integration
**File**: `dashboard/backend/api/routes/tasks.py`
- Import and use `state_db` functions
- Replace JSON file reads with SQLite queries
- Use `load_task_snapshot()` for accurate data

### Fix 4: Dashboard Frontend Logic
**File**: `dashboard/frontend/src/pages/Dashboard.tsx:102`
- Change: `t.active_agents && t.active_agents > 0`
- To: `t.status === 'ACTIVE'`

### Fix 5: SQLite as Single Source of Truth
- Ensure all writes go through `state_db.record_progress()`
- Make `reconcile_task_workspace()` run on every read
- Deprecate direct JSON file reads for state

## Impact

### Current Problems
- Dashboard shows 7 active tasks when 0 are running
- Task statuses stuck at INITIALIZED forever
- Stale counts accumulate over time
- No way to know actual system state

### After Fix
- Dashboard shows accurate active task count
- Task statuses reflect actual lifecycle
- Counts properly increment and decrement
- SQLite provides consistent, accurate state
- JSON files remain for audit/debugging only

## Implementation Priority

**CRITICAL** - This is breaking the entire dashboard and orchestrator visibility.

### Phase 1: Quick Fix (Immediate)
1. Fix dashboard frontend to use task status
2. Add global registry decrements

### Phase 2: Proper Integration (Next)
1. Integrate SQLite reads in dashboard API
2. Add task status transitions

### Phase 3: Full Migration (Future)
1. Make SQLite the only source of truth
2. Convert JSON files to append-only logs
3. Remove all direct JSON registry reads

## Testing Validation

After fixes are implemented:
1. Create a new task
2. Deploy agents
3. Wait for agents to complete
4. Verify dashboard shows 0 active tasks
5. Check GLOBAL_REGISTRY.json shows correct counts
6. Verify SQLite has accurate state

## Code References

- Task creation: `real_mcp_server.py:222-570`
- Agent deployment: `real_mcp_server.py:700-1100`
- Progress updates: `real_mcp_server.py:3065-3300`
- Dashboard API: `tasks.py:324-500`
- Dashboard UI: `Dashboard.tsx:100-150`
- State DB: `orchestrator/state_db.py:1-494`