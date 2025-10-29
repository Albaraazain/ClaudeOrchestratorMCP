# Global Registry Workspace Fix

## Problem

Tasks were being created in the correct location (`.agent-workspace/<task_id>/`), but the global registry was being created/updated in the wrong directory. This caused a "split-brain" situation where:

- **Tasks created in:** `client_cwd/.agent-workspace/<task_id>/` (when `client_cwd` provided)
- **Global registry in:** `WORKSPACE_BASE/registry/GLOBAL_REGISTRY.json` (MCP server's directory)

This meant the global registry wasn't in the same `.agent-workspace` folder as the tasks it was tracking.

## Root Cause

The global registry path was hardcoded to always use `WORKSPACE_BASE`:

```python
global_reg_path = f"{WORKSPACE_BASE}/registry/GLOBAL_REGISTRY.json"
```

However, when tasks were created with `client_cwd`, they would go into a different workspace:

```python
if client_cwd:
    workspace_base = os.path.join(client_cwd, '.agent-workspace')
    # Tasks created here
else:
    workspace_base = WORKSPACE_BASE
    # But global registry always updated in WORKSPACE_BASE
```

## Solution

### 1. Created Helper Functions

**`get_workspace_base_from_task_workspace(task_workspace)`**
- Extracts the workspace base from a task workspace path
- Example: `/path/to/.agent-workspace/TASK-xxx` → `/path/to/.agent-workspace`

**`get_global_registry_path(workspace_base)`**
- Returns the global registry path for a given workspace base
- Example: `/path/to/.agent-workspace` → `/path/to/.agent-workspace/registry/GLOBAL_REGISTRY.json`

**`ensure_global_registry(workspace_base)`**
- Ensures global registry exists at the specified workspace base
- Creates the registry file if it doesn't exist

### 2. Updated Task Creation

In `create_real_task()`:
```python
# Ensure global registry exists in THIS workspace
ensure_global_registry(workspace_base)

# Store workspace_base in task registry for future reference
registry = {
    ...
    "workspace_base": workspace_base,  # NEW: Store for global registry updates
    ...
}

# Update global registry in the SAME workspace_base where task was created
global_reg_path = get_global_registry_path(workspace_base)
```

### 3. Updated All Global Registry References

Updated these functions to use the correct workspace-specific global registry:

- **`deploy_headless_agent()`**: Uses `get_workspace_base_from_task_workspace(workspace)` to find the correct registry
- **`get_real_task_status()`**: Extracts workspace base from task workspace path
- **`kill_real_agent()`**: Uses workspace base from task location
- **`update_agent_progress()`**: Finds workspace base dynamically

## Before vs After

### Before (WRONG)
```
Project Directory/
├── .agent-workspace/
│   ├── TASK-20251015-183958-xxx/     ← Task here
│   │   ├── AGENT_REGISTRY.json
│   │   ├── progress/
│   │   └── findings/
│   └── TASK-20251015-190147-yyy/     ← Another task here
│       └── AGENT_REGISTRY.json
│
MCP Server Directory/
└── .agent-workspace/
    └── registry/
        └── GLOBAL_REGISTRY.json      ← But global registry here! ❌
```

### After (CORRECT)
```
Project Directory/
└── .agent-workspace/
    ├── registry/
    │   └── GLOBAL_REGISTRY.json      ← Global registry with tasks! ✅
    ├── TASK-20251015-183958-xxx/
    │   ├── AGENT_REGISTRY.json
    │   ├── progress/
    │   └── findings/
    └── TASK-20251015-190147-yyy/
        └── AGENT_REGISTRY.json
```

## How It Works Now

### Task Creation Flow
```python
# 1. Determine workspace base
if client_cwd:
    workspace_base = os.path.join(client_cwd, '.agent-workspace')
else:
    workspace_base = WORKSPACE_BASE

# 2. Ensure global registry exists THERE
ensure_global_registry(workspace_base)

# 3. Create task in that workspace
workspace = f"{workspace_base}/{task_id}"

# 4. Update global registry in SAME workspace
global_reg_path = get_global_registry_path(workspace_base)
```

### Agent Update Flow
```python
# 1. Find task workspace
workspace = find_task_workspace(task_id)
# e.g., /path/to/.agent-workspace/TASK-xxx

# 2. Extract workspace base
workspace_base = get_workspace_base_from_task_workspace(workspace)
# e.g., /path/to/.agent-workspace

# 3. Get global registry from SAME workspace
global_reg_path = get_global_registry_path(workspace_base)
# e.g., /path/to/.agent-workspace/registry/GLOBAL_REGISTRY.json

# 4. Update global registry
with open(global_reg_path, 'r') as f:
    global_reg = json.load(f)
# ... update ...
```

## Files Modified

- `real_mcp_server.py`:
  - Added `get_workspace_base_from_task_workspace()` (line 80)
  - Added `get_global_registry_path()` (line 94)
  - Added `ensure_global_registry()` (line 108)
  - Updated `ensure_workspace()` (line 122)
  - Updated `create_real_task()` (line 974)
  - Updated `deploy_headless_agent()` (line 1323)
  - Updated `get_real_task_status()` (line 1417)
  - Updated `kill_real_agent()` (line 1634)
  - Updated `update_agent_progress()` (line 2095)

## Testing

To verify the fix works:

### 1. Create a task with client_cwd
```python
result = create_real_task(
    description="Test task",
    client_cwd="/Users/yourname/project"
)
# Should create:
# /Users/yourname/project/.agent-workspace/registry/GLOBAL_REGISTRY.json
# /Users/yourname/project/.agent-workspace/TASK-xxx/
```

### 2. Deploy an agent
```python
deploy_headless_agent(
    task_id="TASK-xxx",
    agent_type="investigator",
    prompt="Test"
)
# Should update global registry in:
# /Users/yourname/project/.agent-workspace/registry/GLOBAL_REGISTRY.json
```

### 3. Check registry
```bash
# Global registry should be in same directory as tasks
ls -la /Users/yourname/project/.agent-workspace/
# Should show:
# registry/GLOBAL_REGISTRY.json
# TASK-xxx/
```

## Benefits

✅ **Consistent Location:** Global registry always in same `.agent-workspace` as tasks  
✅ **Client-Aware:** Works correctly with `client_cwd` parameter  
✅ **No Split-Brain:** All task data in one location  
✅ **Easy Cleanup:** Delete `.agent-workspace` folder removes everything  
✅ **Portable:** Can move entire `.agent-workspace` folder  
✅ **Multi-Project:** Each project has its own isolated workspace  

## Migration Notes

If you have an existing global registry in the wrong location:

1. **Find the old registry:** `WORKSPACE_BASE/registry/GLOBAL_REGISTRY.json`
2. **Find where tasks are:** Look for `.agent-workspace/TASK-xxx/` directories
3. **Move registry to task location:** `mv old/registry new/.agent-workspace/registry/`
4. **Verify:** Check that `new/.agent-workspace/registry/GLOBAL_REGISTRY.json` exists

Or simply delete the old registry and let the system create a new one in the correct location.

## Edge Cases Handled

- **Multiple workspace bases:** Each workspace base gets its own global registry
- **Server vs Client workspaces:** Both work correctly now
- **Missing registry:** Created automatically in correct location
- **Task workspace lookup:** Searches multiple locations to find tasks
- **Registry updates:** All updates use workspace-aware path resolution


