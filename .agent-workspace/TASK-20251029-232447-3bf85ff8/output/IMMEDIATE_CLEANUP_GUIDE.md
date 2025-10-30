# Immediate Cleanup Guide

**Generated:** 2025-10-29 23:34
**Purpose:** Safe cleanup of leaked Claude processes and ghost registry entries

## Problem Summary

The orchestrator system has severe resource leakage:

- **Registry shows:** 95 agents spawned, 15 active
- **Reality shows:** 49 Claude processes running, 8 tmux sessions active
- **Ghost agents:** 87 agents in registry without corresponding tmux sessions
- **Issue:** Registry corruption - most agents in registry have no actual running process

## Root Cause

Based on investigation findings:
1. Agents completing or terminating but registry not being updated
2. No automatic cleanup when agents finish
3. Registry counts (total_agents_spawned, active_agents) not synchronized with reality
4. Old task agents from completed tasks still in registry

## What Will Be Cleaned Up

The cleanup script (`cleanup_leaked_agents.sh`) will:

### 1. Process Cleanup
- **Kill:** All Claude processes NOT associated with active tmux sessions
- **Preserve:** Claude processes running inside current agent tmux sessions
- **Expected:** ~0 processes killed (all 49 processes are likely associated with tmux sessions or other work)

### 2. Tmux Session Cleanup
- **Kill:** Any agent tmux sessions without a running Claude process (zombie sessions)
- **Preserve:** All active agent tmux sessions with running processes
- **Expected:** 0 zombie sessions (all 8 sessions appear healthy)

### 3. Registry Cleanup
- **Remove:** All agent entries in GLOBAL_REGISTRY.json without corresponding tmux sessions
- **Expected:** Remove ~87 ghost agent entries
- **Update:** Registry metadata counts (total_agents_spawned, active_agents) to match reality

## Safety Checks Performed

The cleanup script includes multiple safety mechanisms:

1. **User Confirmation:** Requires explicit "yes" confirmation before proceeding
2. **Process Preservation:** Creates whitelist of PIDs to preserve based on active tmux sessions
3. **Double-Check:** Verifies process is actually Claude before killing
4. **JSON Safety:** Uses Python for safe JSON manipulation (no sed/awk corruption risk)
5. **Dry-Run Available:** Shows what will be cleaned before execution

## How to Run the Cleanup

### Step 1: Review Current State
```bash
./verify_cleanup.sh
```

This shows:
- Current process counts
- Current tmux session counts
- Registry state
- Inconsistencies detected

### Step 2: Run the Cleanup
```bash
./cleanup_leaked_agents.sh
```

The script will:
1. Show you what will be cleaned
2. Ask for confirmation
3. Preserve active agent processes
4. Kill leaked processes
5. Clean zombie tmux sessions
6. Remove ghost registry entries
7. Update registry counts

### Step 3: Verify Success
```bash
./verify_cleanup.sh
```

Check for:
- ✓ Registry and tmux sessions synchronized
- ✓ No ghost agents in registry
- ✓ Active agent count matches reality

## Expected Results

### Before Cleanup
```
Registry agents: 95
Active agents: 15
Claude processes: 49
Tmux sessions: 8
Ghost agents: 87
```

### After Cleanup
```
Registry agents: 8
Active agents: 8
Claude processes: 49 (or fewer if some were leaked)
Tmux sessions: 8
Ghost agents: 0
```

## Manual Cleanup (If Scripts Fail)

If the automated scripts fail, here's how to clean manually:

### 1. Identify Active Sessions
```bash
tmux ls | grep agent_
```

### 2. Clean Registry Manually
```python
import json
from pathlib import Path
import subprocess

# Get active sessions
result = subprocess.run(['tmux', 'ls'], capture_output=True, text=True)
active_sessions = {line.split(':')[0] for line in result.stdout.strip().split('\n') if 'agent_' in line}

# Load and clean registry
registry_path = Path(".agent-workspace/registry/GLOBAL_REGISTRY.json")
with open(registry_path) as f:
    registry = json.load(f)

# Remove ghost agents
registry['agents'] = {
    aid: adata for aid, adata in registry['agents'].items()
    if adata.get('tmux_session', '') in active_sessions
}

# Update counts
registry['total_agents_spawned'] = len(registry['agents'])
registry['active_agents'] = sum(1 for a in registry['agents'].values()
                                if a.get('status') not in ['completed', 'terminated'])

# Save
with open(registry_path, 'w') as f:
    json.dump(registry, f, indent=2)
```

## Post-Cleanup Recommendations

After cleanup completes successfully:

1. **Monitor:** Watch for new ghost agents appearing (indicates deployment bug)
2. **Task Registries:** Consider cleaning up old task-specific registries in `.agent-workspace/TASK-*/`
3. **Implement:** Automatic cleanup on agent completion (see other agent findings)
4. **Add Monitoring:** Periodic health checks to detect registry drift early

## Files Created

1. **cleanup_leaked_agents.sh** - Main cleanup script (root directory)
2. **verify_cleanup.sh** - Verification script (root directory)
3. **IMMEDIATE_CLEANUP_GUIDE.md** - This documentation

## Technical Details

### Current Active Agents (as of 2025-10-29 23:25)

From current task (TASK-20251029-232447-3bf85ff8):
- process_leak_analyzer-232523-be4f03
- deployment_code_auditor-232525-818d49
- registry_corruption_investigator-232528-303b95
- immediate_cleanup_builder-232530-7cf214

From previous task (TASK-20251029-225319-45548b6a):
- cleanup_function_builder-232249-fdb115
- file_handle_tracker_builder-232257-348f75
- cleanup_daemon_builder-232300-9040a9
- integration_tester-232302-b08b55

These 8 agents should be preserved. All other 87 agents in registry are ghosts.

## Questions?

If cleanup fails or you encounter issues, check:
1. Do you have permission to kill processes?
2. Is Python 3 available?
3. Are tmux sessions accessible?
4. Is the registry file writable?
