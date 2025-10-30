# Resource Cleanup Daemon Script Review

**Script:** `resource_cleanup_daemon.sh` (270 lines)
**Reviewer:** daemon_script_reviewer-233829-6c2867
**Date:** 2025-10-29
**Status:** ⚠️ NOT PRODUCTION READY - Critical bugs found

---

## Executive Summary

The cleanup daemon script demonstrates **solid architectural fundamentals** but contains **critical bugs** that prevent it from functioning reliably. The script has unreliable zombie process detection and suffers from race conditions in file operations. However, the prompt file cleanup pattern is verified correct.

**Overall Assessment:** 🟡 **NEEDS FIXES BEFORE PRODUCTION**

- ✅ Architecture: Well-structured, modular design
- ✅ Logging: Comprehensive with timestamps
- ✅ Prompt cleanup: Pattern verified correct
- 🔴 Zombie detection: Critical bug (line 128)
- 🟡 Safety: Race conditions and missing edge case handling
- 🟡 Robustness: No health monitoring or timeouts

---

## Critical Issues Found

### 🔴 CRITICAL: Zombie Process Detection Bug (Line 128)

**Location:** `resource_cleanup_daemon.sh:128`

**Buggy Code:**
```bash
zombie_count=$(ps aux | grep -c "$agent_id" | grep -v grep || echo 0)
```

**Problem:**
- `grep -c` counts matches BEFORE `grep -v grep` can filter
- The grep process itself always appears in ps output
- Result: Will ALWAYS report at least 1 process even when no zombies exist
- Makes zombie detection completely unreliable

**Fix:**
```bash
zombie_count=$(ps aux | grep "$agent_id" | grep -v grep | wc -l)
```

**Impact:** False positive zombie warnings on every cleanup operation.

---

### ✅ VERIFIED CORRECT: Prompt File Pattern (Line 81)

**Location:** `resource_cleanup_daemon.sh:81`

**Status:** ✅ **PATTERN IS CORRECT**

**Verification:**
Checked AGENT_REGISTRY.json and actual files on disk:
- Agent ID from registry: `cleanup_daemon_builder-232300-9040a9`
- Actual file: `agent_prompt_cleanup_daemon_builder-232300-9040a9.txt`
- Pattern: `${workspace}/agent_prompt_${agent_id}.txt` ✅ MATCHES

**Code:**
```bash
if [ -f "${workspace}/agent_prompt_${agent_id}.txt" ]; then
    rm -f "${workspace}/agent_prompt_${agent_id}.txt" 2>/dev/null
    return 0
fi
```

**Result:** This code will correctly find and delete prompt files. Initial concern was based on incorrect assumption about agent_id format. Verification shows agent_id includes the full `{agent_type}-{timestamp}-{hash}` format, which matches the file naming convention exactly.

---

## High Severity Issues

### 🟠 HIGH: Race Condition in Archive Operations (Lines 56-71)

**Location:** `resource_cleanup_daemon.sh:56-71`

**Problems:**

1. **No file locking:** Multiple daemons could try to archive the same file
2. **Silent failure:** `2>/dev/null` masks real errors
3. **No existence check:** mv fails if file is being written to
4. **mkdir race condition:** Multiple processes creating same archive dir

**Current Code:**
```bash
archive_agent_logs() {
    local workspace="$1"
    local agent_id="$2"
    local archive_dir="${workspace}/archive"

    mkdir -p "$archive_dir"  # Race condition possible

    # Move without checking if file is in use
    if [ -f "${workspace}/logs/${agent_id}_stream.jsonl" ]; then
        mv "${workspace}/logs/${agent_id}_stream.jsonl" "${archive_dir}/" 2>/dev/null && \
            ((files_archived++))
    fi
    # ... more files ...
}
```

**Recommended Fix:**
```bash
archive_agent_logs() {
    local workspace="$1"
    local agent_id="$2"
    local archive_dir="${workspace}/archive"
    local files_archived=0

    # Create archive dir with error handling
    if ! mkdir -p "$archive_dir" 2>/dev/null; then
        log "  ⚠️  Failed to create archive directory: $archive_dir"
        echo "0"
        return 1
    fi

    # Archive each file with proper error handling
    local stream_log="${workspace}/logs/${agent_id}_stream.jsonl"
    if [ -f "$stream_log" ]; then
        # Use flock for atomic operation if available
        if command -v flock >/dev/null 2>&1; then
            flock -n "$stream_log" mv "$stream_log" "${archive_dir}/" 2>&1 | \
                tee -a "$LOG_FILE" && ((files_archived++))
        else
            mv "$stream_log" "${archive_dir}/" 2>&1 | tee -a "$LOG_FILE" && \
                ((files_archived++))
        fi
    fi

    echo "$files_archived"
}
```

**Impact:**
- Files could be corrupted during move
- Real errors are hidden
- Multiple daemon instances could conflict

---

### 🟠 HIGH: No Health Monitoring (Lines 224-262)

**Location:** `resource_cleanup_daemon.sh:224-262`

**Problems:**

1. **No timeouts on subcommands:** tmux/python could hang indefinitely
2. **No deadlock detection:** Daemon could stall silently
3. **No watchdog:** No external process monitoring daemon health
4. **Infinite loop without bounds:** No circuit breaker

**Current Code:**
```bash
while true; do
    # No timeout on these commands
    while IFS= read -r registry_path; do
        process_registry "$registry_path"  # Could hang
    done < <(find "$WORKSPACE_BASE" -name "AGENT_REGISTRY.json" -type f 2>/dev/null)

    cleanup_inactive_sessions  # Could hang on tmux commands

    sleep "$CHECK_INTERVAL"
done
```

**Recommended Fix:**
```bash
# Add timeout utility function
run_with_timeout() {
    local timeout="$1"
    shift
    timeout "$timeout" "$@"
    return $?
}

while true; do
    # Add iteration timeout
    {
        while IFS= read -r registry_path; do
            run_with_timeout 30 process_registry "$registry_path" || \
                log "⚠️  Registry processing timeout: $registry_path"
        done < <(find "$WORKSPACE_BASE" -name "AGENT_REGISTRY.json" -type f 2>/dev/null)

        run_with_timeout 60 cleanup_inactive_sessions || \
            log "⚠️  Inactive session cleanup timeout"
    } &
    wait $! || log "⚠️  Cleanup iteration failed"

    # Touch heartbeat file for external monitoring
    touch "${WORKSPACE_BASE}/cleanup_daemon_heartbeat"

    sleep "$CHECK_INTERVAL"
done
```

**Impact:** Daemon could hang silently, requiring manual intervention.

---

## Medium Severity Issues

### 🟡 MEDIUM: JSON Parsing Safety (Lines 150-176)

**Location:** `resource_cleanup_daemon.sh:150-176`

**Problems:**

1. **No JSON schema validation**
2. **Assumes 'agents' key exists**
3. **Silent failure on malformed JSON**
4. **No validation of required fields**

**Current Code:**
```python
try:
    with open(registry_path, 'r') as f:
        data = json.load(f)

    agents = data.get('agents', [])  # Assumes 'agents' is list

    for agent in agents:
        agent_id = agent.get('id')  # No validation if None
        status = agent.get('status')
        session_name = agent.get('tmux_session')

        if status in ['completed', 'terminated', 'error'] and agent_id and session_name:
            print(f"{agent_id}|{session_name}|{status}")
```

**Recommended Fix:**
```python
try:
    with open(registry_path, 'r') as f:
        data = json.load(f)

    # Validate structure
    if not isinstance(data, dict):
        sys.stderr.write(f"Invalid registry format: not a dict\n")
        sys.exit(1)

    agents = data.get('agents', [])
    if not isinstance(agents, list):
        sys.stderr.write(f"Invalid registry format: 'agents' not a list\n")
        sys.exit(1)

    for agent in agents:
        # Validate each agent has required fields
        if not isinstance(agent, dict):
            continue

        agent_id = agent.get('id')
        status = agent.get('status')
        session_name = agent.get('tmux_session')

        if not all([agent_id, status, session_name]):
            sys.stderr.write(f"Skipping incomplete agent: {agent}\n")
            continue

        if status in ['completed', 'terminated', 'error']:
            print(f"{agent_id}|{session_name}|{status}")

except json.JSONDecodeError as e:
    sys.stderr.write(f"Invalid JSON in {registry_path}: {e}\n")
    sys.exit(1)
```

**Impact:** Script silently skips cleanup if registry format changes.

---

### 🟡 MEDIUM: Daemon Loop Without Health Check (Lines 224-262)

**Problem:** Already covered in HIGH severity section above.

---

## Low Severity Issues

### 🔵 LOW: Incomplete Signal Handling (Line 266)

**Location:** `resource_cleanup_daemon.sh:266`

**Current Code:**
```bash
trap 'log "Received shutdown signal, exiting..."; exit 0' SIGINT SIGTERM
```

**Problems:**

1. **Missing signals:** SIGHUP, SIGQUIT not handled
2. **No state persistence:** Partial cleanup lost on shutdown
3. **No graceful cleanup:** Just exits immediately

**Recommended Fix:**
```bash
# State file for restart recovery
STATE_FILE="${WORKSPACE_BASE}/cleanup_daemon_state.json"

cleanup_and_exit() {
    log "Received shutdown signal, performing graceful shutdown..."

    # Save current state
    echo "{\"last_iteration\": $iteration, \"timestamp\": $(date +%s)}" > "$STATE_FILE"

    # Wait for any in-progress cleanup
    wait

    log "Daemon shutdown complete"
    exit 0
}

trap cleanup_and_exit SIGINT SIGTERM SIGHUP SIGQUIT
```

**Impact:** Minor - daemon restart loses partial progress.

---

## Positive Aspects ✅

The script demonstrates several **good practices**:

1. ✅ **Error Handling:** `set -euo pipefail` (line 14) for immediate error exit
2. ✅ **Logging:** Comprehensive logging with timestamps (lines 27-29)
3. ✅ **Modularity:** Well-organized functions with clear responsibilities
4. ✅ **Signal Handling:** Basic signal handling structure in place (line 266)
5. ✅ **Documentation:** Clear comments explaining purpose and logic
6. ✅ **Separation of Concerns:** Each function has single responsibility

**Core architecture is sound** - issues are implementation bugs, not design flaws.

---

## Feature Coverage Analysis

Required features from task specification:

| Feature | Status | Notes |
|---------|--------|-------|
| Scans AGENT_REGISTRY.json files | ✅ Implemented | Lines 232-248 |
| Detects completed agents | ✅ Implemented | Lines 150-176 (Python parser) |
| Kills orphaned tmux sessions | ✅ Implemented | Lines 101-110 |
| Archives logs properly | 🟡 Partial | Race condition issues (lines 56-71) |
| Deletes temp files safely | ✅ Implemented | Pattern verified correct (line 81) |
| Zombie process detection | 🔴 BROKEN | grep bug (line 128) |
| Inactivity cleanup (>110 min) | ✅ Implemented | Lines 179-211 |

**Overall Feature Coverage:** 5/7 working, 1/7 broken, 1/7 partial

---

## Performance Analysis

### Current Performance Characteristics

**Check Interval:** 60 seconds (configurable via `CHECK_INTERVAL`)

**Complexity per iteration:**
- Registry scan: O(n) where n = number of task workspaces
- Per-agent processing: O(m) where m = number of completed agents
- Inactive session check: O(k) where k = total tmux sessions

**Estimated overhead per iteration:**
- find command: ~100-500ms for 100 workspaces
- JSON parsing: ~10-50ms per registry
- tmux queries: ~50ms per session check
- Total: **~1-2 seconds for 100 agents**

### Performance Issues

1. **No batch processing:** Processes agents one at a time
2. **Redundant tmux calls:** Calls tmux list-sessions multiple times
3. **No caching:** Re-scans entire workspace tree every iteration

### Recommended Optimizations

```bash
# Cache tmux session list at start of iteration
TMUX_SESSIONS=$(tmux list-sessions -F "#{session_name}:#{session_activity}" 2>/dev/null)

check_session_exists() {
    local session_name="$1"
    echo "$TMUX_SESSIONS" | grep -q "^${session_name}:"
}

get_session_activity() {
    local session_name="$1"
    echo "$TMUX_SESSIONS" | grep "^${session_name}:" | cut -d: -f2
}
```

**Impact:** Reduces tmux overhead from O(n²) to O(n)

---

## Safety Concerns

### 🔴 Critical Safety Issues

1. **Data Loss Risk:** Archive race condition could corrupt log files
2. **Resource Leaks:** Broken prompt file deletion means unbounded disk usage
3. **False Monitoring:** Broken zombie detection gives false confidence

### 🟡 Moderate Safety Issues

1. **Silent Failures:** Error suppression with `2>/dev/null` hides problems
2. **No Validation:** Missing checks could delete wrong files if logic fails
3. **No Rollback:** Failed cleanup operations leave inconsistent state

### Recommended Safety Enhancements

```bash
# Add safety checks before destructive operations
cleanup_agent() {
    local workspace="$1"
    local agent_id="$2"
    local session_name="$3"
    local reason="$4"

    # Validate inputs
    if [[ ! "$workspace" =~ ^.agent-workspace/TASK- ]]; then
        log "⚠️  SAFETY: Invalid workspace path: $workspace"
        return 1
    fi

    if [[ ! "$session_name" =~ ^agent_ ]]; then
        log "⚠️  SAFETY: Invalid session name: $session_name"
        return 1
    fi

    # ... rest of cleanup ...
}
```

---

## Edge Cases Analysis

### Handled Edge Cases ✅

1. ✅ Registry file doesn't exist (line 145)
2. ✅ Agent session already terminated (line 238)
3. ✅ Python parsing errors (line 172)
4. ✅ Empty agents list (implicit handling)

### Missing Edge Cases 🔴

1. 🔴 **Concurrent daemon instances:** No locking, multiple daemons could conflict
2. 🔴 **Partial registry writes:** Could read corrupted JSON mid-write
3. 🔴 **Workspace deletion during cleanup:** No check if workspace still exists
4. 🔴 **Agent ID with special characters:** Could break grep/find patterns
5. 🔴 **Symlinks in workspace:** Could follow symlinks outside workspace
6. 🔴 **Disk full during archive:** No space check before move
7. 🔴 **Extremely large log files:** Could hang on move operation

### Recommended Edge Case Handling

```bash
# Add workspace existence check
cleanup_agent() {
    local workspace="$1"

    # Check workspace still exists
    if [ ! -d "$workspace" ]; then
        log "  ⚠️  Workspace no longer exists: $workspace"
        return 1
    fi

    # Check disk space before archiving
    local available_space=$(df -P "$workspace" | awk 'NR==2 {print $4}')
    if [ "$available_space" -lt 102400 ]; then  # Less than 100MB
        log "  ⚠️  Insufficient disk space for archiving"
        return 1
    fi

    # ... rest of cleanup ...
}
```

---

## Testing Recommendations

### Unit Tests Needed

```bash
# Test script syntax
bash -n resource_cleanup_daemon.sh

# Test zombie detection fix
test_zombie_detection() {
    # Create test process
    sleep 60 &
    local test_pid=$!

    # Run detection (should find 1)
    zombie_count=$(ps aux | grep "$test_pid" | grep -v grep | wc -l)

    # Cleanup
    kill $test_pid

    [ "$zombie_count" -eq 1 ] || echo "FAIL: zombie detection"
}

# Test prompt file pattern
test_prompt_file_pattern() {
    local test_workspace="/tmp/test_workspace"
    mkdir -p "$test_workspace"

    # Create file with real naming pattern
    touch "${test_workspace}/agent_prompt_test_agent-123456-abc123.txt"

    # Test detection
    agent_id="test_agent-123456-abc123"
    if [ -f "${test_workspace}/agent_prompt_${agent_id}.txt" ]; then
        echo "PASS: prompt file detected"
    else
        echo "FAIL: prompt file not detected"
    fi

    rm -rf "$test_workspace"
}
```

### Integration Tests Needed

1. **End-to-end cleanup:** Create fake agent, complete it, verify cleanup
2. **Concurrent daemon test:** Run multiple daemons, verify no conflicts
3. **Load test:** Create 100 completed agents, measure cleanup time
4. **Recovery test:** Kill daemon mid-cleanup, verify graceful restart

### Manual Test Plan

1. ✅ Create test workspace with fake completed agent
2. ✅ Run daemon for one iteration
3. ✅ Verify tmux session killed
4. ✅ Verify logs archived
5. ✅ Verify prompt file deleted
6. ✅ Check for zombie processes
7. ✅ Verify logging output
8. ✅ Test signal handling (SIGINT, SIGTERM)
9. ✅ Test inactive session cleanup

---

## Recommended Improvements

### Priority 1 (Must Fix Before Production)

1. 🔴 **Fix zombie detection bug** (line 128) - 5 minutes
2. 🔴 **Add file locking to archive operations** (lines 56-71) - 1-2 hours
3. 🔴 **Add timeouts to all subprocess calls** - 1 hour

### Priority 2 (Should Fix Soon)

1. 🟡 **Add JSON schema validation** (lines 150-176)
2. 🟡 **Implement health monitoring** with heartbeat file
3. 🟡 **Add concurrent daemon detection** and locking
4. 🟡 **Preserve error messages** instead of `2>/dev/null`

### Priority 3 (Nice to Have)

1. 🔵 **Add SIGHUP/SIGQUIT handlers** (line 266)
2. 🔵 **Implement state persistence** for graceful restart
3. 🔵 **Add metrics collection** (cleanup counts, timing)
4. 🔵 **Implement log rotation** for daemon log file

---

## Code Quality Metrics

| Metric | Score | Notes |
|--------|-------|-------|
| **Correctness** | 6/10 | One critical bug (zombie detection), rest working |
| **Safety** | 5/10 | Race conditions, missing validation |
| **Robustness** | 4/10 | No timeouts, health checks |
| **Maintainability** | 8/10 | Well-structured, good comments |
| **Performance** | 6/10 | Acceptable but could optimize |
| **Error Handling** | 5/10 | Basic handling, hides real errors |
| **Testing** | 0/10 | No tests provided |

**Overall Quality Score: 5.4/10** - Needs fixes before production

---

## Comparison with Python cleanup_agent_resources()

Based on findings from other agents, there's a Python function `cleanup_agent_resources()` in `real_mcp_server.py:3925-4119` that performs similar cleanup.

### Daemon Script vs Python Function

| Feature | Bash Daemon | Python Function | Winner |
|---------|-------------|-----------------|--------|
| Automatic execution | ✅ Periodic | 🔴 Manual call | Daemon |
| Error handling | 🔴 Buggy | ✅ Comprehensive | Python |
| Integration | 🔴 External | ✅ Native | Python |
| Maintenance | 🔴 Separate code | ✅ Same codebase | Python |
| Testing | 🔴 Shell tests | ✅ pytest | Python |
| Debugging | 🔴 Shell logs | ✅ Python logging | Python |

### Recommendation

**Use Python function as primary cleanup mechanism:**
1. Call `cleanup_agent_resources()` from `kill_real_agent()` ✅ Already done
2. Call `cleanup_agent_resources()` from `update_agent_progress()` when status becomes terminal 🔴 Not yet implemented
3. Use bash daemon as **safety net** only for:
   - Orphaned sessions from crashed processes
   - Manual cleanup of old workspaces
   - Emergency recovery scenarios

**This bash daemon should be SECONDARY, not primary cleanup.**

---

## Conclusion

### ⚠️ REVIEW VERDICT: NEEDS FIXES BEFORE PRODUCTION

**Critical Issues Blocking Production:**
1. 🔴 Zombie detection completely broken (line 128)
2. 🟡 Race conditions in file operations (lines 56-71)
3. 🟡 No health monitoring or timeouts

**Required Actions Before Production:**
1. Fix zombie detection bug (5 minutes)
2. Add file locking to archive operations (1-2 hours)
3. Implement health monitoring with timeouts (1-2 hours)
4. Add comprehensive testing
5. Coordinate with Python cleanup function

**Estimated Fix Time:** 3-4 hours for all priority 1 issues

**Recommendation:**
- Fix critical bugs immediately
- Use Python cleanup as primary mechanism
- Demote bash daemon to safety net role
- Add comprehensive testing before production deployment

---

## References

- Script: `resource_cleanup_daemon.sh` (270 lines)
- Related: `real_mcp_server.py:3925-4119` (cleanup_agent_resources function)
- Related: `real_mcp_server.py:3878-3883` (kill_real_agent integration)
- Documentation: `.agent-workspace/TASK-*/output/CLEANUP_FUNCTION_IMPLEMENTATION.md`

---

**Review completed by:** daemon_script_reviewer-233829-6c2867
**Task:** TASK-20251029-225319-45548b6a
**Date:** 2025-10-29
