# cleanup_agent_resources() Implementation Documentation

**Implementation Date:** 2025-10-29
**Implemented By:** cleanup_function_builder-232249-fdb115
**Location:** `real_mcp_server.py:3925-4119`

---

## Overview

The `cleanup_agent_resources()` function provides comprehensive resource cleanup for completed or terminated Claude agents. It addresses the critical resource leak issues identified in the system audit by properly freeing all computing resources associated with an agent.

---

## Function Signature

```python
def cleanup_agent_resources(
    workspace: str,
    agent_id: str,
    agent_data: Dict[str, Any],
    keep_logs: bool = True
) -> Dict[str, Any]:
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `workspace` | str | Yes | Task workspace path (e.g., `.agent-workspace/TASK-xxx`) |
| `agent_id` | str | Yes | Agent ID to clean up |
| `agent_data` | Dict[str, Any] | Yes | Agent registry data dictionary (must contain `tmux_session` key) |
| `keep_logs` | bool | No (default: True) | If True, archive logs to `workspace/archive/`. If False, delete them. |

### Return Value

Returns a dictionary with detailed cleanup status:

```python
{
    "success": True,  # Overall success - True if all critical operations completed
    "tmux_session_killed": True,  # Whether tmux session was killed
    "prompt_file_deleted": True,  # Whether prompt file was deleted
    "log_files_archived": True,  # Whether log files were archived/deleted
    "verified_no_zombies": True,  # Whether zombie process check passed
    "errors": [],  # List of error messages (empty if no errors)
    "archived_files": [  # List of archived file paths (if keep_logs=True)
        "/path/to/archive/agent_xxx_stream.jsonl",
        "/path/to/archive/agent_xxx_progress.jsonl",
        "/path/to/archive/agent_xxx_findings.jsonl"
    ]
}
```

---

## Cleanup Operations

The function performs 5 main cleanup operations in sequence:

### 1. Kill Tmux Session

**Location:** Lines 3970-3986

**What it does:**
- Checks if tmux session still exists using `check_tmux_session_exists()`
- If running, kills the session using `kill_tmux_session()`
- Waits 0.5 seconds for graceful process termination
- Handles cases where session already terminated

**Success criteria:**
- `cleanup_results["tmux_session_killed"] = True` if session killed or already gone

**Errors:**
- Appends error message to `errors` list if kill operation fails

---

### 2. Delete Prompt File

**Location:** Lines 3988-4001

**What it does:**
- Constructs absolute path: `{workspace}/agent_prompt_{agent_id}.txt`
- Checks if file exists
- Deletes the file using `os.remove()`
- Handles cases where file already deleted or never existed

**Rationale:**
Prompt files are only needed for agent startup. Once the agent is running or completed, they serve no purpose and consume disk space.

**Success criteria:**
- `cleanup_results["prompt_file_deleted"] = True` if file deleted or doesn't exist

**Errors:**
- Appends error message if deletion fails (permissions, locked file, etc.)

---

### 3. Archive or Delete JSONL Log Files

**Location:** Lines 4003-4056

**What it does:**

#### If `keep_logs=True` (default):
1. Creates archive directory: `{workspace}/archive/`
2. Moves 3 types of log files to archive:
   - Stream log: `{workspace}/logs/{agent_id}_stream.jsonl`
   - Progress log: `{workspace}/progress/{agent_id}_progress.jsonl`
   - Findings log: `{workspace}/findings/{agent_id}_findings.jsonl`
3. Uses `shutil.move()` to atomically move files
4. Tracks archived file paths in `archived_files` list

#### If `keep_logs=False`:
1. Deletes all 3 log files using `os.remove()`
2. No archive directory created

**Success criteria:**
- `cleanup_results["log_files_archived"] = True` if at least one file was processed
- `cleanup_results["archived_files"]` contains list of archived paths (if keep_logs=True)

**Error handling:**
- If archive directory creation fails, falls back to deletion mode
- Per-file error handling - failure on one file doesn't stop others
- All errors appended to `errors` list

---

### 4. Verify No Zombie Processes

**Location:** Lines 4058-4095

**What it does:**
1. Runs `ps aux` to get all running processes
2. Searches for processes containing both `agent_id` and `claude` (case-insensitive)
3. Counts lingering processes
4. Reports first 3 zombie processes for debugging

**Success criteria:**
- `cleanup_results["verified_no_zombies"] = True` if zero zombie processes found

**Warning conditions:**
- If zombie processes found:
  - `cleanup_results["zombie_processes"]` = count
  - `cleanup_results["zombie_process_details"]` = first 3 process details
  - Warning logged

**Error handling:**
- 5-second timeout on `ps` command
- Graceful handling of timeout, command failures
- Non-blocking - doesn't fail cleanup if verification fails

---

### 5. Determine Overall Success

**Location:** Lines 4097-4111

**What it does:**
- Checks if all 3 critical operations succeeded:
  1. Tmux session killed
  2. Prompt file deleted
  3. Log files archived/deleted
- Sets `cleanup_results["success"]` based on critical operations
- Logs final status message

**Success definition:**
Overall cleanup is successful if ALL critical operations complete successfully. Zombie verification is informational only and doesn't affect success status.

---

## Usage Examples

### Example 1: Basic Cleanup (Archive Logs)

```python
# After agent completes normally
workspace = ".agent-workspace/TASK-20251029-225319-45548b6a"
agent_id = "investigator-225442-dfe9d7"
agent_data = {
    "id": agent_id,
    "tmux_session": "agent_investigator-225442-dfe9d7",
    "status": "completed"
}

result = cleanup_agent_resources(
    workspace=workspace,
    agent_id=agent_id,
    agent_data=agent_data,
    keep_logs=True  # Archive logs for later review
)

if result["success"]:
    print(f"Cleanup successful. Archived {len(result['archived_files'])} files.")
else:
    print(f"Cleanup had errors: {result['errors']}")
```

### Example 2: Cleanup Without Archiving

```python
# For failed agents or test runs where logs aren't needed
result = cleanup_agent_resources(
    workspace=workspace,
    agent_id=agent_id,
    agent_data=agent_data,
    keep_logs=False  # Delete logs immediately
)
```

### Example 3: Integration with kill_real_agent

```python
# In kill_real_agent function (line 3867)
try:
    # Before killing tmux session, do comprehensive cleanup
    cleanup_result = cleanup_agent_resources(
        workspace=workspace,
        agent_id=agent_id,
        agent_data=agent,
        keep_logs=True
    )

    # Log cleanup results
    logger.info(f"Agent cleanup: {cleanup_result}")

    # Continue with registry updates...
```

### Example 4: Integration with update_agent_progress

```python
# In update_agent_progress function (after line 4316)
if status == 'completed' and agent_found:
    # Validate completion
    validation = validate_agent_completion(...)

    # Store validation results
    agent_found['completion_validation'] = {...}
    agent_found['completed_at'] = datetime.now().isoformat()

    # AUTO-CLEANUP: Free resources now that agent is done
    cleanup_result = cleanup_agent_resources(
        workspace=workspace,
        agent_id=agent_id,
        agent_data=agent_found,
        keep_logs=True
    )

    # Log cleanup status
    if cleanup_result["success"]:
        logger.info(f"Auto-cleanup successful for completed agent {agent_id}")
    else:
        logger.warning(f"Auto-cleanup had errors for {agent_id}: {cleanup_result['errors']}")
```

---

## Error Handling

The function uses comprehensive error handling with these principles:

### 1. Non-Failing Design
- Each cleanup operation is wrapped in try-except
- Failure of one operation doesn't prevent others from executing
- All errors are collected in `errors` list

### 2. Error Categories

**Critical Errors** (affect success status):
- Failed to kill tmux session
- Failed to delete prompt file
- Failed to archive/delete log files

**Non-Critical Errors** (logged but don't affect success):
- Failed to verify zombie processes
- Failed to get zombie process details

### 3. Error Reporting

All errors are:
- Appended to `cleanup_results["errors"]` list
- Logged using Python `logger` with appropriate level (error/warning)
- Returned to caller for decision making

---

## Logging

The function uses structured logging at multiple levels:

### Info Level (Normal Operations)
```python
logger.info(f"Cleanup: Killing tmux session {session_name} for agent {agent_id}")
logger.info(f"Cleanup: Deleted prompt file {prompt_file}")
logger.info(f"Cleanup: Archived {file_type} to {dst_path}")
logger.info(f"Cleanup: Verified no zombie processes for agent {agent_id}")
logger.info(f"Cleanup: Successfully cleaned up all resources for agent {agent_id}")
```

### Warning Level (Non-Critical Issues)
```python
logger.warning(f"Failed to remove prompt file: {e}")
logger.warning(f"Failed to archive {src}: {e}")
logger.warning(f"Cleanup: Found {len(agent_processes)} lingering processes")
logger.warning(f"Cleanup: Partial cleanup for agent {agent_id}, errors: {errors}")
```

### Error Level (Critical Failures)
```python
logger.error(f"Failed to create archive directory {archive_dir}: {e}")
logger.error(f"Cleanup: {error_msg}")
```

All log messages are prefixed with "Cleanup:" for easy filtering and monitoring.

---

## Integration Points

### Where to Call This Function

#### 1. **Automatic Cleanup on Completion** (RECOMMENDED)
**Location:** `update_agent_progress` function (after line 4316)
**Trigger:** When agent reports `status='completed'`
**Purpose:** Immediate resource cleanup when agents finish normally

```python
# After setting completed_at timestamp
cleanup_result = cleanup_agent_resources(
    workspace=workspace,
    agent_id=agent_id,
    agent_data=agent_found,
    keep_logs=True
)
```

#### 2. **Manual Termination Cleanup** (CRITICAL)
**Location:** `kill_real_agent` function (before line 3872)
**Trigger:** When orchestrator manually terminates agent
**Purpose:** Comprehensive cleanup before killing tmux session

```python
# Before killing tmux session
cleanup_result = cleanup_agent_resources(
    workspace=workspace,
    agent_id=agent_id,
    agent_data=agent,
    keep_logs=True
)
```

#### 3. **Periodic Cleanup** (SAFETY NET)
**Location:** New background monitoring script
**Trigger:** Periodic check (every 60 seconds)
**Purpose:** Catch orphaned resources from crashed/failed agents

```python
def periodic_cleanup():
    # Find completed agents with still-running sessions
    # Call cleanup_agent_resources for each
    pass
```

---

## File Paths Reference

The function operates on these specific file paths:

| File Type | Path Template | Created At | Purpose |
|-----------|---------------|------------|---------|
| Prompt File | `{workspace}/agent_prompt_{agent_id}.txt` | deploy_headless_agent:2365 | Agent instructions |
| Stream Log | `{workspace}/logs/{agent_id}_stream.jsonl` | deploy_headless_agent:2375 | Claude output stream |
| Progress Log | `{workspace}/progress/{agent_id}_progress.jsonl` | update_agent_progress:4258 | Progress updates |
| Findings Log | `{workspace}/findings/{agent_id}_findings.jsonl` | report_agent_finding:4400 | Agent discoveries |
| Archive Dir | `{workspace}/archive/` | cleanup_agent_resources:4016 | Log archive location |

---

## Testing Recommendations

### Unit Test Example

```python
def test_cleanup_agent_resources():
    """Test comprehensive cleanup of agent resources."""
    # Setup
    workspace = "/tmp/test_workspace"
    agent_id = "test_agent_123"
    os.makedirs(f"{workspace}/logs", exist_ok=True)
    os.makedirs(f"{workspace}/progress", exist_ok=True)
    os.makedirs(f"{workspace}/findings", exist_ok=True)

    # Create test files
    open(f"{workspace}/agent_prompt_{agent_id}.txt", 'w').write("test")
    open(f"{workspace}/logs/{agent_id}_stream.jsonl", 'w').write("{}")
    open(f"{workspace}/progress/{agent_id}_progress.jsonl", 'w').write("{}")
    open(f"{workspace}/findings/{agent_id}_findings.jsonl", 'w').write("{}")

    # Create tmux session
    subprocess.run(["tmux", "new-session", "-d", "-s", f"agent_{agent_id}", "sleep 3600"])

    # Test cleanup
    agent_data = {"tmux_session": f"agent_{agent_id}"}
    result = cleanup_agent_resources(workspace, agent_id, agent_data, keep_logs=True)

    # Assertions
    assert result["success"] == True
    assert result["tmux_session_killed"] == True
    assert result["prompt_file_deleted"] == True
    assert result["log_files_archived"] == True
    assert len(result["archived_files"]) == 3
    assert len(result["errors"]) == 0

    # Verify tmux session gone
    ps_result = subprocess.run(
        ["tmux", "has-session", "-t", f"agent_{agent_id}"],
        capture_output=True
    )
    assert ps_result.returncode != 0  # Session should not exist

    # Verify files archived
    assert os.path.exists(f"{workspace}/archive/{agent_id}_stream.jsonl")
    assert os.path.exists(f"{workspace}/archive/{agent_id}_progress.jsonl")
    assert os.path.exists(f"{workspace}/archive/{agent_id}_findings.jsonl")

    # Verify prompt file deleted
    assert not os.path.exists(f"{workspace}/agent_prompt_{agent_id}.txt")

    print("✅ Test passed")
```

### Integration Test Scenarios

1. **Normal completion flow:**
   - Agent completes → update_agent_progress → cleanup_agent_resources → verify

2. **Manual termination flow:**
   - User calls kill_real_agent → cleanup_agent_resources → verify

3. **Crash recovery flow:**
   - Agent crashes → periodic cleanup detects → cleanup_agent_resources → verify

4. **Partial cleanup handling:**
   - Some files missing → should still succeed for available resources

---

## Performance Considerations

### Resource Usage
- **CPU:** Minimal - mostly file I/O operations
- **Memory:** ~1KB per cleanup operation (result dict)
- **Disk I/O:**
  - 3-4 file moves (if archiving)
  - 1 directory creation (if first archive)
  - 1 file deletion (prompt file)

### Timing
- **Tmux kill:** ~0.5 seconds (includes grace period)
- **File operations:** ~0.1 seconds per file
- **Zombie verification:** ~0.5 seconds (ps command)
- **Total:** ~2 seconds for typical cleanup

### Concurrency
- Function is NOT thread-safe
- Multiple simultaneous cleanups of same agent will cause race conditions
- Recommendation: Use locking if called from multiple threads

---

## Known Limitations

1. **No file handle tracking:**
   - Function assumes files are closed by OS when tmux dies
   - Cannot explicitly close file handles opened by `tee` command
   - Mitigation: Tmux kill terminates `tee` process, OS closes handles

2. **Zombie process detection is best-effort:**
   - Relies on `ps aux` output containing agent_id
   - May miss processes if agent_id not in command line
   - Non-blocking - doesn't fail cleanup if detection fails

3. **No atomic operations:**
   - Cleanup is multi-step, not atomic
   - Partial cleanup possible if process interrupted
   - Recommendation: Use transaction log for critical systems

4. **Archive directory unlimited:**
   - No retention policy implemented
   - Archives accumulate indefinitely
   - Recommendation: Implement periodic archive cleanup

---

## Future Enhancements

### Phase 2 Improvements

1. **File handle tracking system:**
   - Track open file handles in agent registry
   - Explicitly close handles before cleanup
   - Reference: file_handle_tracker_builder agent findings

2. **Atomic cleanup operations:**
   - Use transaction log for rollback capability
   - All-or-nothing cleanup semantics

3. **Archive retention policy:**
   - Auto-delete archives older than N days
   - Compress old archives with gzip
   - Configurable retention per task type

4. **Enhanced zombie detection:**
   - Use psutil library for better process tracking
   - Track process tree, not just matching strings
   - Force kill zombies if found

5. **Cleanup metrics:**
   - Track cleanup success rate
   - Monitor disk space freed
   - Alert on repeated failures

---

## Coordination with Other Agents

This function was built as part of a coordinated effort with:

### Completed Agents:
1. **resource_lifecycle_investigator** - Identified resource leak patterns
2. **current_state_auditor** - Audited current cleanup gaps
3. **tmux_best_practices_researcher** - Provided tmux cleanup patterns

### Active Agents (Coordination Info):
1. **kill_real_agent_enhancer** - Integrating function into kill_real_agent
2. **file_handle_tracker_builder** - Building file handle tracking system
3. **process_management_researcher** - Researching process lifecycle

### Integration Status:
- ✅ Function implemented (this agent)
- 🔄 Integration with kill_real_agent (in progress)
- 🔄 File handle tracking (in progress)
- ⏳ Integration with update_agent_progress (pending)
- ⏳ Periodic cleanup daemon (pending)

---

## Summary

The `cleanup_agent_resources()` function provides a comprehensive, production-ready solution for cleaning up agent resources. It addresses the critical resource leak issues identified in the system audit by:

1. ✅ Killing tmux sessions with grace period
2. ✅ Deleting temporary prompt files
3. ✅ Archiving JSONL logs for retention
4. ✅ Verifying no zombie processes remain
5. ✅ Comprehensive error handling and logging
6. ✅ Detailed status reporting

**Next Steps:**
1. Integrate into `kill_real_agent` function (other agent working on this)
2. Integrate into `update_agent_progress` for auto-cleanup
3. Create periodic cleanup daemon script
4. Implement archive retention policy
5. Add comprehensive testing

**Location:** `real_mcp_server.py:3925-4119`
**Status:** ✅ COMPLETE AND READY FOR INTEGRATION
