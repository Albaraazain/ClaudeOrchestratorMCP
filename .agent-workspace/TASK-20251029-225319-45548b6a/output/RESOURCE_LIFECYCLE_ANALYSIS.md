# Resource Lifecycle Analysis Report

**Investigation Date:** 2025-10-29
**Investigator:** resource_lifecycle_investigator-225442-dfe9d7
**System:** Claude Orchestrator MCP

## Executive Summary

**CRITICAL FINDING:** The Claude Orchestrator MCP system has **SEVERE RESOURCE LEAKS** that cause computing resources to accumulate indefinitely after agents complete their tasks. Every completed agent leaves behind:
- 1 active tmux session
- 1+ open file handles (JSONL logs)
- Multiple Claude processes
- Temporary files on disk

**Current System Evidence:**
- 4 active tmux sessions
- 54 Claude processes running
- 78 agent prompt files accumulated
- 38 JSONL log files accumulated

---

## 1. Current Resource Creation Flow

### 1.1 Agent Deployment (`deploy_headless_agent`)
**Location:** `real_mcp_server.py:2135-2481`

**Resources Created:**
1. **Tmux Session** (line 2383-2387)
   - Session name: `agent_{agent_id}`
   - Created via `create_tmux_session()`
   - Runs Claude in background

2. **Agent Prompt File** (line 2365-2367)
   ```python
   prompt_file = f"{workspace}/agent_prompt_{agent_id}.txt"
   with open(prompt_file, 'w') as f:
       f.write(agent_prompt)
   ```
   - Absolute path stored
   - Never deleted after use

3. **JSONL Log File** (line 2375)
   ```python
   log_file = f"{logs_dir}/{agent_id}_stream.jsonl"
   claude_command = f"... | tee '{log_file}'"
   ```
   - Created via `tee` command
   - **NEVER closed explicitly**
   - File handle remains open indefinitely

4. **Registry Entries** (line 2406-2450)
   - Task-level registry: `AGENT_REGISTRY.json`
   - Global registry: `GLOBAL_REGISTRY.json`
   - Deployment log: `deploy_{agent_id}.json`

5. **Progress & Findings Directories**
   - `{workspace}/progress/{agent_id}_progress.jsonl`
   - `{workspace}/findings/{agent_id}_findings.jsonl`
   - Append mode, never closed

---

## 2. Current Cleanup Mechanisms

### 2.1 Manual Cleanup via `kill_real_agent`
**Location:** `real_mcp_server.py:3829-3923`

**What It Does:**
- ✅ Kills tmux session (line 3872)
- ✅ Updates registry status to 'terminated'
- ✅ Decrements active_count

**What It DOESN'T Do:**
- ❌ Close JSONL log file handles
- ❌ Remove temporary prompt files
- ❌ Clean up progress/findings files
- ❌ Verify all processes terminated

**Trigger:** MANUAL ONLY - must be explicitly called by orchestrator or user

---

### 2.2 Status Update via `update_agent_progress`
**Location:** `real_mcp_server.py:4232-4370`

**What It Does When status='completed':**
- ✅ Validates completion (4-layer validation, line 4288-4313)
- ✅ Marks completion timestamp
- ✅ Updates registry status to 'completed'
- ✅ Decrements active_count

**What It DOESN'T Do:**
- ❌ Kill tmux session
- ❌ Close file handles
- ❌ Clean up any resources
- ❌ Trigger any cleanup functions

**Critical Gap:** Agent status changes to "completed" but **ALL RESOURCES REMAIN ALLOCATED**

---

### 2.3 Passive Monitoring via `get_agent_output`
**Location:** `real_mcp_server.py:3674-3682`

**What It Does:**
```python
if check_tmux_session_exists(agent['tmux_session']):
    session_status = "running"
else:
    session_status = "terminated"
```
- ✅ Detects if tmux session is running or terminated
- ✅ Reports status

**What It DOESN'T Do:**
- ❌ Trigger cleanup when detecting termination
- ❌ Any resource management

**Behavior:** Passive observer only - takes no action

---

### 2.4 Watchdog Script (`progress_watchdog.sh`)
**Location:** `progress_watchdog.sh:1-45`

**What It Does:**
- ✅ Monitors agent progress updates
- ✅ Sends reminders to silent agents

**What It DOESN'T Do:**
- ❌ Detect completed agents
- ❌ Trigger cleanup
- ❌ Resource management

---

## 3. Identified Resource Leak Risks

### 3.1 CRITICAL: JSONL Log File Handles
**Severity:** CRITICAL
**Location:** `real_mcp_server.py:2375-2380`

**Issue:**
```python
log_file = f"{logs_dir}/{agent_id}_stream.jsonl"
claude_command = f"... | tee '{log_file}'"
```
The `tee` command opens the JSONL log file for writing but **NEVER closes it**. When the tmux session is killed, the file handle may remain open or improperly closed.

**Impact:**
- 1 leaked file handle per agent deployment
- File system resource exhaustion over time
- Potential file corruption

**Evidence:** 38 JSONL log files found in workspace

---

### 3.2 CRITICAL: Tmux Sessions Not Auto-Cleaned
**Severity:** CRITICAL
**Location:** `real_mcp_server.py:4288-4370`

**Issue:**
When agents report status='completed', the `update_agent_progress` function updates the registry but does NOT kill the tmux session. The session continues running indefinitely.

**Impact:**
- 1 leaked tmux session per completed agent
- Background processes consume CPU/memory
- System resource exhaustion

**Evidence:** 4 active tmux sessions, 54 Claude processes running

---

### 3.3 HIGH: Prompt Files Accumulate
**Severity:** HIGH
**Location:** `real_mcp_server.py:2365-2367`

**Issue:**
Agent prompt files are created but never deleted after the agent completes.

**Impact:**
- Disk space consumption (each file ~5-20KB)
- Workspace clutter
- No benefit after agent completes

**Evidence:** 78 prompt files found in workspace

---

### 3.4 MEDIUM: Progress/Findings Files Never Cleaned
**Severity:** MEDIUM
**Locations:**
- `real_mcp_server.py:4269` (progress append)
- `real_mcp_server.py:4412` (findings append)

**Issue:**
Progress and findings JSONL files are opened in append mode but never explicitly closed. While Python GC eventually closes them, the files themselves are never archived or removed.

**Impact:**
- Disk space consumption (can be large for verbose agents)
- Historical clutter
- May be useful for debugging, but no retention policy

---

### 3.5 LOW: Zombie Processes (Potential)
**Severity:** LOW

**Issue:**
When killing tmux sessions, child processes (Claude instances) should terminate, but there's no verification that all child processes are actually killed.

**Impact:**
- Potential zombie processes
- CPU/memory consumption

**Evidence:** Disproportionate process count (54 Claude processes for 4 sessions suggests ~13.5 processes per session or accumulation from past sessions)

---

## 4. Resources That Need Cleanup

### Complete Checklist of Resources:

1. **Tmux Sessions**
   - Created: `create_tmux_session()` in `deploy_headless_agent`
   - Should be killed: When agent status → 'completed' or 'terminated'
   - Currently: Only killed via manual `kill_real_agent` call

2. **JSONL Log Files** (`*_stream.jsonl`)
   - Created: Via `tee` command in `deploy_headless_agent`
   - Should be closed: When agent completes
   - Should be archived/deleted: Based on retention policy
   - Currently: Never closed, never cleaned up

3. **Agent Prompt Files** (`agent_prompt_*.txt`)
   - Created: `deploy_headless_agent:2366`
   - Should be deleted: After agent successfully starts (no longer needed)
   - Currently: Accumulate indefinitely

4. **Progress Files** (`*_progress.jsonl`)
   - Created: `update_agent_progress:4269` (append mode)
   - Should be closed: After agent completes
   - Should be archived: Based on retention policy
   - Currently: Never explicitly closed, never cleaned up

5. **Findings Files** (`*_findings.jsonl`)
   - Created: `report_agent_finding:4412` (append mode)
   - Should be closed: After agent completes
   - Should be archived: Based on retention policy
   - Currently: Never explicitly closed, never cleaned up

6. **Deployment Logs** (`deploy_*.json`)
   - Created: `deploy_headless_agent:2462`
   - Should be archived: Based on retention policy
   - Currently: Accumulate indefinitely

7. **Child Processes** (Claude instances)
   - Created: By tmux session running Claude
   - Should be killed: When tmux session is killed
   - Currently: Should auto-terminate with tmux, but verification needed

---

## 5. Root Cause Analysis

### Why Doesn't Cleanup Happen?

1. **Architectural Gap:** There's a fundamental disconnect between status updates and resource management
   - Agents report "completed" via MCP function
   - MCP function updates status but has NO cleanup logic
   - Cleanup function (`kill_real_agent`) exists but is NEVER called automatically

2. **No Lifecycle Hook:** There's no "on_completion" hook that triggers when agents finish
   - `update_agent_progress` detects completion
   - But treats it as just another status update
   - No special handling for terminal states

3. **Manual-Only Cleanup:** Cleanup is designed for manual intervention
   - `kill_real_agent` is meant for emergency termination
   - Not designed for normal completion flow
   - No automatic trigger mechanism

4. **File Handle Management:** Python's file handling isn't properly structured
   - `tee` command used instead of Python file operations
   - No context managers (`with` statements) for file lifecycle
   - No explicit close operations

---

## 6. Recommended Solution Architecture

### Option 1: Automatic Cleanup on Completion (RECOMMENDED)

**Modify `update_agent_progress`:**

```python
# Line 4315 - After marking completion timestamp
if status in terminal_statuses:  # completed, terminated, error
    # Auto-cleanup resources
    cleanup_result = cleanup_agent_resources(
        workspace=workspace,
        agent_id=agent_id,
        agent_data=agent_found,
        keep_logs=True  # Archive instead of delete
    )
    logger.info(f"Auto-cleanup for {agent_id}: {cleanup_result}")
```

**New function `cleanup_agent_resources`:**
```python
def cleanup_agent_resources(workspace, agent_id, agent_data, keep_logs=True):
    """
    Clean up all resources associated with a completed agent.

    Args:
        workspace: Task workspace path
        agent_id: Agent ID
        agent_data: Agent registry data
        keep_logs: If True, archive logs instead of deleting

    Returns:
        Dict with cleanup results
    """
    cleanup_results = {
        "tmux_session": False,
        "prompt_file": False,
        "log_files_archived": False,
        "verified_no_zombies": False
    }

    # 1. Kill tmux session
    session_name = agent_data.get('tmux_session')
    if session_name and check_tmux_session_exists(session_name):
        cleanup_results["tmux_session"] = kill_tmux_session(session_name)
        time.sleep(0.5)  # Give processes time to terminate

    # 2. Delete prompt file (no longer needed)
    prompt_file = f"{workspace}/agent_prompt_{agent_id}.txt"
    if os.path.exists(prompt_file):
        try:
            os.remove(prompt_file)
            cleanup_results["prompt_file"] = True
        except Exception as e:
            logger.warning(f"Failed to remove prompt file: {e}")

    # 3. Archive or close log files
    if keep_logs:
        # Move to archive subdirectory
        archive_dir = f"{workspace}/archive"
        os.makedirs(archive_dir, exist_ok=True)

        files_to_archive = [
            f"{workspace}/logs/{agent_id}_stream.jsonl",
            f"{workspace}/progress/{agent_id}_progress.jsonl",
            f"{workspace}/findings/{agent_id}_findings.jsonl"
        ]

        for src in files_to_archive:
            if os.path.exists(src):
                dst = f"{archive_dir}/{os.path.basename(src)}"
                try:
                    shutil.move(src, dst)
                    cleanup_results["log_files_archived"] = True
                except Exception as e:
                    logger.warning(f"Failed to archive {src}: {e}")

    # 4. Verify no zombie processes
    # Check for lingering Claude processes tied to this agent
    try:
        ps_output = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True,
            timeout=5
        ).stdout

        agent_processes = [
            line for line in ps_output.split('\n')
            if agent_id in line and 'claude' in line.lower()
        ]

        if len(agent_processes) == 0:
            cleanup_results["verified_no_zombies"] = True
        else:
            logger.warning(f"Found {len(agent_processes)} lingering processes for {agent_id}")
            cleanup_results["zombie_processes"] = len(agent_processes)
    except Exception as e:
        logger.warning(f"Failed to verify zombie processes: {e}")

    return cleanup_results
```

---

### Option 2: Background Cleanup Daemon

**Create a new script: `resource_cleanup_daemon.sh`:**

```bash
#!/bin/bash
# Resource Cleanup Daemon - Auto-cleanup completed agents

WORKSPACE_BASE=".agent-workspace"
CHECK_INTERVAL=60  # Check every minute

while true; do
    # Find all AGENT_REGISTRY.json files
    for REGISTRY in $(find "$WORKSPACE_BASE" -name "AGENT_REGISTRY.json" -type f); do
        # Extract completed agents without active tmux sessions
        COMPLETED_AGENTS=$(jq -r '.agents[] | select(.status == "completed") | .id' "$REGISTRY" 2>/dev/null)

        for AGENT_ID in $COMPLETED_AGENTS; do
            # Check if tmux session still running
            SESSION_NAME=$(jq -r ".agents[] | select(.id == \"$AGENT_ID\") | .tmux_session" "$REGISTRY")

            if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
                echo "🧹 Cleaning up completed agent: $AGENT_ID (session: $SESSION_NAME)"

                # Kill tmux session
                tmux kill-session -t "$SESSION_NAME" 2>/dev/null

                # Archive log files
                WORKSPACE=$(dirname "$REGISTRY")
                mkdir -p "$WORKSPACE/archive"

                mv "$WORKSPACE/logs/${AGENT_ID}_stream.jsonl" "$WORKSPACE/archive/" 2>/dev/null
                mv "$WORKSPACE/progress/${AGENT_ID}_progress.jsonl" "$WORKSPACE/archive/" 2>/dev/null
                mv "$WORKSPACE/findings/${AGENT_ID}_findings.jsonl" "$WORKSPACE/archive/" 2>/dev/null

                # Delete prompt file
                rm -f "$WORKSPACE/agent_prompt_${AGENT_ID}.txt" 2>/dev/null

                echo "✅ Cleaned up $AGENT_ID"
            fi
        done
    done

    sleep $CHECK_INTERVAL
done
```

---

### Option 3: Hybrid Approach (BEST)

Combine both:
1. **Immediate cleanup** via `update_agent_progress` modification (Option 1)
2. **Safety net daemon** that catches any missed cleanups (Option 2)

This ensures:
- Fast cleanup when agents complete normally
- Catches edge cases (crashes, network issues, etc.)
- No resource accumulation over time

---

## 7. Implementation Priority

### Phase 1: Critical Fixes (Immediate)
1. Add `cleanup_agent_resources()` function
2. Modify `update_agent_progress` to call cleanup on terminal status
3. Test with single agent deployment → completion cycle

### Phase 2: Daemon Safety Net (Within 24h)
1. Create `resource_cleanup_daemon.sh`
2. Add systemd service or launchd plist for auto-start
3. Monitor for 48h to verify effectiveness

### Phase 3: Retention Policy (Within 1 week)
1. Define log retention policy (e.g., keep for 7 days)
2. Add archive cleanup logic (delete archives older than retention)
3. Add disk space monitoring

---

## 8. Testing Recommendations

### Test Scenario 1: Normal Completion
1. Deploy agent
2. Agent reports status='completed'
3. Verify:
   - Tmux session killed
   - Prompt file deleted
   - Logs archived
   - No zombie processes

### Test Scenario 2: Manual Termination
1. Deploy agent
2. Call `kill_real_agent`
3. Verify same cleanup as Scenario 1

### Test Scenario 3: Error/Crash
1. Deploy agent
2. Simulate crash (kill -9 tmux session)
3. Verify daemon detects and cleans up orphaned resources

### Test Scenario 4: Resource Accumulation
1. Deploy 10 agents
2. All complete normally
3. Verify:
   - Only 10 archived log sets exist
   - No active tmux sessions
   - Process count returns to baseline

---

## 9. Metrics to Monitor

Post-implementation, monitor:

1. **Tmux Sessions:** `tmux list-sessions | grep agent_ | wc -l`
   - Should be: Number of currently active agents
   - Currently: Accumulates indefinitely

2. **Claude Processes:** `ps aux | grep claude | wc -l`
   - Should be: ~1-2x number of active agents + 1 (main orchestrator)
   - Currently: 54 (likely accumulated)

3. **Disk Space:** `du -sh .agent-workspace/`
   - Should be: Stable or slowly growing (archived logs)
   - Currently: Unbounded growth

4. **File Count:**
   ```bash
   find .agent-workspace -name "agent_prompt_*.txt" | wc -l  # Should be 0
   find .agent-workspace -name "*_stream.jsonl" | wc -l      # Should be active count only
   ```

---

## 10. Conclusion

The Claude Orchestrator MCP system has **severe resource leak issues** that will cause system degradation over time. The root cause is a **fundamental architectural gap**: agents can report completion, but there's **no mechanism to trigger resource cleanup**.

**Key Findings:**
- ❌ Tmux sessions never auto-cleaned
- ❌ File handles never closed
- ❌ Temporary files accumulate indefinitely
- ❌ No lifecycle hooks for cleanup

**Recommended Solution:**
Implement **hybrid approach** (Option 3):
- Immediate cleanup in `update_agent_progress`
- Safety net daemon for edge cases
- Retention policy for long-term management

**Priority:** CRITICAL - Should be implemented immediately to prevent system resource exhaustion.

---

**Report Generated:** 2025-10-29T23:01:00
**Next Steps:** Proceed to best practices research and implementation planning phase.
