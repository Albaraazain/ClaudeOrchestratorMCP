# State DB Enhancement Migration Guide

## Overview
This guide documents the migration from the partial SQLite implementation to the fully enhanced state_db.py that supports complete task/agent state management and dashboard integration.

## What's New

### New Tables
1. **reviews** - Agentic review system tracking
2. **agent_findings** - Agent discoveries and insights
3. **handovers** - Phase transition documents

### Enhanced Columns in `agents` Table
- `model` - LLM model used (opus/sonnet/haiku)
- `claude_pid` - Claude process ID for health monitoring
- `cursor_pid` - Cursor process ID for health monitoring
- `tracked_files` - JSON field for file tracking metadata

### New CRUD Functions

#### Task Lifecycle Management
- `update_task_status()` - Transition task states (INITIALIZED → ACTIVE → COMPLETED)
- `update_phase_status()` - Manage phase state machine
- `cleanup_stale_agents()` - Mark dead agents as failed

#### Dashboard Integration
- `get_all_tasks()` - List tasks with real-time counts
- `get_active_counts()` - Dashboard stats (active tasks/agents)

#### Agent Coordination
- `record_agent_finding()` - Store agent discoveries
- `get_agent_findings()` - Query findings with filters
- `create_review()` / `update_review()` - Agentic review management
- `create_handover()` / `get_latest_handover()` - Phase transitions

#### Debugging
- `inspect_database()` - Database state inspection

## Migration Steps

### Step 1: Backup Existing Data
```bash
# Backup existing SQLite database if it exists
cp .agent-workspace/registry/state.sqlite3 .agent-workspace/registry/state.sqlite3.backup

# Backup registry JSONs
cp .agent-workspace/registry/GLOBAL_REGISTRY.json .agent-workspace/registry/GLOBAL_REGISTRY.json.backup
```

### Step 2: Replace state_db.py
```bash
# Rename existing to backup
mv orchestrator/state_db.py orchestrator/state_db_old.py

# Use enhanced version
mv orchestrator/state_db_enhanced.py orchestrator/state_db.py
```

### Step 3: Update Imports
No changes needed - the enhanced version maintains backward compatibility with all existing functions.

### Step 4: Test Migration
```bash
# Run the test script
python test_state_db_migration.py

# Expected output: All tests should pass
```

### Step 5: Update Dashboard API
Modify `dashboard/backend/api/routes/tasks.py` to use the new SQLite functions:

```python
# Instead of reading JSON files:
# with open(GLOBAL_REGISTRY_PATH) as f:
#     registry = json.load(f)

# Use new functions:
from orchestrator.state_db import get_all_tasks, get_active_counts

@router.get("/tasks")
async def list_tasks():
    tasks = get_all_tasks(
        workspace_base=WORKSPACE_BASE,
        limit=100,
        offset=0
    )
    return tasks

@router.get("/stats")
async def get_stats():
    counts = get_active_counts(workspace_base=WORKSPACE_BASE)
    return counts
```

### Step 6: Update MCP Server
In `real_mcp_server.py`, use the new functions for lifecycle management:

```python
# When agents complete:
update_task_status(
    workspace_base=workspace_base,
    task_id=task_id,
    new_status="COMPLETED"
)

# For phase transitions:
update_phase_status(
    workspace_base=workspace_base,
    task_id=task_id,
    phase_index=current_phase,
    new_status="APPROVED"
)
```

## Verification Checklist

- [ ] SQLite database creates all 7 tables
- [ ] Agents table has new columns (model, PIDs, tracked_files)
- [ ] Dashboard shows accurate real-time counts
- [ ] Task status transitions properly (INITIALIZED → ACTIVE → COMPLETED)
- [ ] No more stale counts in GLOBAL_REGISTRY.json
- [ ] Agent findings are stored and retrievable
- [ ] Reviews and handovers work for phase management

## Rollback Plan

If issues occur:
1. Restore backup: `mv orchestrator/state_db_old.py orchestrator/state_db.py`
2. Restore database: `cp .agent-workspace/registry/state.sqlite3.backup .agent-workspace/registry/state.sqlite3`
3. Restart services

## Performance Improvements

The enhanced schema includes:
- Proper indexes on all foreign keys and frequently queried columns
- WAL mode for better concurrency
- Atomic operations to prevent race conditions
- Efficient count queries using aggregation

## Notes

- The schema is backward compatible - existing data will migrate automatically
- ALTER TABLE commands add missing columns without data loss
- JSON fields (tracked_files, data, etc.) are properly validated
- All timestamps use ISO format for consistency

## Support

For issues or questions about the migration:
1. Check test output: `python test_state_db_migration.py`
2. Inspect database: Use the `inspect_database()` function
3. Review logs in `.agent-workspace/logs/`