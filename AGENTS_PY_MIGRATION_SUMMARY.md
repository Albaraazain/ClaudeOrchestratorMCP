# Agents.py SQLite Migration Summary

## Overview
Successfully migrated `dashboard/backend/api/routes/agents.py` from JSON-based registry reads to SQLite state_db as the primary data source, with JSON as fallback only.

## Changes Made

### 1. Added Imports (Lines 17-30)
- Added `from orchestrator import state_db` to the import section
- Created fallback `state_db` class for environments without orchestrator

### 2. Added Helper Functions (Lines 67-74)
- Added `WORKSPACE_BASE` constant pointing to `~/.agent-workspace`
- Added `_get_workspace_base()` helper to extract workspace base from task workspace path

### 3. Migrated Functions

#### _resolve_tracked_file (Lines 151-203)
**Before**: Read from AGENT_REGISTRY.json only
**After**:
- First tries `state_db.get_agent_by_id()`
- Falls back to JSON registry if SQLite returns None
- Preserves all existing functionality including archive fallback

#### list_agents (Lines 263-322)
**Before**: Read from AGENT_REGISTRY.json only
**After**:
- First tries `state_db.get_agents_for_task()`
- Converts SQLite dict format (uses 'agent_id') to expected format (uses 'id')
- Falls back to JSON registry if SQLite returns None
- Maintains all filtering logic

#### get_agent (Lines 333-374)
**Before**: Read from AGENT_REGISTRY.json only
**After**:
- First tries `state_db.get_agent_by_id()`
- Converts SQLite dict format to expected format
- Falls back to JSON registry if SQLite returns None

## Migration Pattern Used
```python
# Try SQLite first
data = state_db.get_function(
    workspace_base=workspace_base,
    task_id=task_id,
    ...
)
if data:
    # Use SQLite data
    ...
else:
    # Fallback to JSON only if SQLite unavailable
    registry = read_registry_with_lock(...)
```

## Function Call Counts
- `state_db.get_agent_by_id`: 2 occurrences (in _resolve_tracked_file and get_agent)
- `state_db.get_agents_for_task`: 1 occurrence (in list_agents)

## Benefits
1. **Performance**: SQLite queries are faster than reading/parsing large JSON files
2. **Consistency**: SQLite provides ACID guarantees, avoiding race conditions
3. **Backward Compatibility**: JSON fallback ensures system works even without SQLite
4. **Zero Breaking Changes**: All existing API contracts maintained

## Testing
Created `test_agents_migration.py` which verifies:
- Correct import statements added
- State_db functions called in right places
- Correct number of function calls
- SQLite-first pattern implemented

## Files Modified
- `/dashboard/backend/api/routes/agents.py` - Main migration
- `/test_agents_migration.py` - Test script (created)
- `/AGENTS_PY_MIGRATION_SUMMARY.md` - This summary (created)