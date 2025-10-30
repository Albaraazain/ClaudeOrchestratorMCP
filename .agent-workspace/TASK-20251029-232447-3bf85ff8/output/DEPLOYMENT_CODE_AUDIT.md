# Deployment Code Audit Report

**Agent:** deployment_code_auditor-232525-818d49
**Task:** TASK-20251029-232447-3bf85ff8
**Date:** 2025-10-29T23:34:00
**File Audited:** real_mcp_server.py

## Executive Summary

**CRITICAL FINDING:** The deployment code has **ZERO concurrency protection**, causing race conditions that spawn duplicate agents and corrupt the registry. Combined with missing deduplication checks and poor error handling, this creates the exact resource leakage observed (42 Claude processes but only 6 tmux sessions).

---

## 1. CODE LOCATIONS THAT SPAWN AGENTS

### Primary Spawn Function
**Function:** `deploy_headless_agent(task_id, agent_type, prompt, parent="orchestrator")`
**Location:** `real_mcp_server.py:2135-2488`
**Entry Points:**
- Direct MCP tool call: `@mcp.tool` decorator (line 2134)
- Via `spawn_child_agent()` function (line 4675)

### Child Spawn Wrapper
**Function:** `spawn_child_agent(task_id, parent_agent_id, child_agent_type, child_prompt)`
**Location:** `real_mcp_server.py:4661-4675`
**Implementation:** `return deploy_headless_agent.fn(task_id, child_agent_type, child_prompt, parent_agent_id)`

**Critical Issue:** This is a **transparent passthrough** with ZERO validation.

---

## 2. BUGS CAUSING DUPLICATE SPAWNS

### Bug #1: RACE CONDITION - No Concurrency Protection (CRITICAL)
**Severity:** CRITICAL
**Location:** `real_mcp_server.py:2171-2437`

**The Race Condition:**
```python
# Line 2171-2172: Read registry (no lock)
with open(registry_path, 'r') as f:
    registry = json.load(f)

# Lines 2174-2185: Check limits
if registry['active_count'] >= registry['max_concurrent']:
    return {"success": False, ...}

# Lines 2426-2428: Modify registry in-memory
registry['agents'].append(agent_data)
registry['total_spawned'] += 1
registry['active_count'] += 1

# Lines 2436-2437: Write registry (no lock)
with open(registry_path, 'w') as f:
    json.dump(registry, f, indent=2)
```

**Race Scenario:**
1. **T0:** Agent A reads registry: `active_count=5, max_concurrent=10`
2. **T1:** Agent B reads registry: `active_count=5, max_concurrent=10` (same state!)
3. **T2:** Agent A passes checks, spawns agent X, increments `active_count=6`, writes
4. **T3:** Agent B passes checks (still thinks `active_count=5`), spawns agent Y, increments `active_count=6`, writes
5. **Result:** Both agents spawned, but `active_count=6` instead of 7. Registry corruption begins.

**Evidence:**
- No `fcntl.flock()` calls in `deploy_headless_agent`
- `fcntl.LOCK_SH` only used in `get_global_registry_snapshot` (line 1397) for reading, never for writing
- Multiple concurrent MCP calls from parallel agents or orchestrator hit this path simultaneously

**Impact:**
- Duplicate agents spawned despite limits
- `active_count` becomes inaccurate (ghost agents)
- Global registry diverges from task registries

---

### Bug #2: REDUNDANT REGISTRY READS - Widening the Race Window (HIGH)
**Severity:** HIGH
**Location:** `real_mcp_server.py:2171, 2195, 2203`

**The Problem:**
```python
# Read #1 - Line 2171: For anti-spiral checks
with open(registry_path, 'r') as f:
    registry = json.load(f)

# Read #2 - Line 2195: For parent depth (REDUNDANT!)
with open(registry_path, 'r') as f:
    registry = json.load(f)  # Same file, already have it!

# Read #3 - Line 2203: For task description (REDUNDANT!)
with open(registry_path, 'r') as f:
    task_registry = json.load(f)  # AGAIN!
```

**Why This Matters:**
1. **Wastes I/O:** 3x file reads instead of 1
2. **Widens race window:** More time between read and write = more collisions
3. **Inconsistency risk:** Registry could change between reads (though unlikely in practice)

**Fix:** Use the first loaded `registry` object for all three purposes.

---

### Bug #3: NO DEDUPLICATION - Duplicate Children Spawn Freely (CRITICAL)
**Severity:** CRITICAL
**Location:** `real_mcp_server.py:4675`

**The Problem:**
```python
@mcp.tool
def spawn_child_agent(task_id: str, parent_agent_id: str, child_agent_type: str, child_prompt: str):
    # Delegate to existing deployment function
    return deploy_headless_agent.fn(task_id, child_agent_type, child_prompt, parent_agent_id)
```

**Missing Checks:**
- ✗ Check if parent already has a child of this type
- ✗ Check if similar child prompt exists
- ✗ Check agent hierarchy depth limits
- ✗ Prevent rapid re-spawning (rate limiting)

**Attack Scenario (Accidental):**
1. Agent experiences error/confusion
2. Agent retries by calling `spawn_child_agent` again
3. Second identical child spawns
4. Both children now work on same task, waste resources
5. Both report findings, creating duplicate work

**Real-World Example:**
Current task shows 4 agents spawned, likely including duplicates from retry behavior.

---

### Bug #4: INCOMPLETE ERROR HANDLING - Orphaned Resources (HIGH)
**Severity:** HIGH
**Location:** `real_mcp_server.py:2484-2488, 2389-2403`

**The Problem:**
```python
try:
    # Line 2365: Create prompt file
    prompt_file = os.path.abspath(f"{workspace}/agent_prompt_{agent_id}.txt")
    with open(prompt_file, 'w') as f:
        f.write(agent_prompt)

    # Lines 2383-2387: Create tmux session
    session_result = create_tmux_session(...)

    # Line 2389: Early return if session fails
    if not session_result["success"]:
        return {"success": False, "error": ...}  # prompt_file NOT cleaned up!

    # Line 2399: Early return if session terminates
    if not check_tmux_session_exists(session_name):
        return {"success": False, "error": ...}  # prompt_file STILL NOT cleaned up!

except Exception as e:
    return {"success": False, "error": f"Failed to deploy agent: {str(e)}"}
    # NO CLEANUP HERE EITHER!
```

**Orphaned Resources:**
- `agent_prompt_{agent_id}.txt` files (lines 2365, 2389, 2399)
- `logs/` directories created at line 2349
- Potentially zombie tmux sessions if creation succeeds but registry update fails
- In-memory registry modifications lost if exception occurs before write

**Impact:**
- Disk space waste (each prompt file ~5-10KB, accumulates over time)
- Workspace clutter
- Misleading debugging (old prompt files look like active agents)

---

### Bug #5: RESOURCE LEAK ON EARLY RETURNS (MEDIUM)
**Severity:** MEDIUM
**Location:** `real_mcp_server.py:2389-2403`

**Specific Issue:**
If tmux session creation **succeeds** (line 2383) but the session **terminates immediately** (line 2399), we return error without:
- Cleaning up the created (but dead) tmux session
- Removing the prompt file
- Logging the failure for debugging

**This creates zombie tmux sessions** that exist but aren't tracked.

---

## 3. MISSING VALIDATION/DEDUPLICATION LOGIC

### No Pre-Spawn Checks in `deploy_headless_agent`
**Current checks (lines 2174-2185):**
- ✓ `active_count >= max_concurrent`
- ✓ `total_spawned >= max_agents`

**MISSING checks:**
- ✗ Check if agent with same `agent_type` and `parent` already exists
- ✗ Check if similar prompt was recently used (semantic dedup)
- ✗ Verify parent agent still exists and is active
- ✗ Rate limiting (prevent spawn bursts)
- ✗ Depth validation (prevent deep nesting beyond `max_depth`)

### No Pre-Spawn Checks in `spawn_child_agent`
**Current implementation:** Blind passthrough to `deploy_headless_agent.fn()`

**MISSING checks:**
- ✗ Verify parent_agent_id exists in registry
- ✗ Check parent's current child count
- ✗ Prevent duplicate children with same type
- ✗ Enforce depth limits based on parent's depth

### No Atomic Registry Updates
**Current pattern:** Read → Modify in-memory → Write (UNSAFE!)

**MISSING:**
- ✗ File locking with `fcntl.flock(f.fileno(), fcntl.LOCK_EX)` for exclusive writes
- ✗ Retry logic on lock contention
- ✗ Atomic write-then-rename pattern for registry files
- ✗ Checksum/version validation to detect concurrent modifications

---

## 4. RECOMMENDED FIXES (PRIORITY ORDER)

### Fix #1: Implement File Locking (IMMEDIATE - CRITICAL)
**Location:** `real_mcp_server.py:2171-2437, 4557-4558`

**Solution Pattern:**
```python
import fcntl

def atomic_registry_update(registry_path, update_fn):
    """Context manager for atomic registry updates with file locking."""
    with open(registry_path, 'r+') as f:  # Open for read+write
        # Acquire exclusive lock (blocks other writers)
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            registry = json.load(f)
            registry = update_fn(registry)  # Apply updates
            f.seek(0)
            f.truncate()
            json.dump(registry, f, indent=2)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return registry

# Usage in deploy_headless_agent:
def update_registry(registry):
    # Checks
    if registry['active_count'] >= registry['max_concurrent']:
        raise ValueError("Too many active agents")

    # Modifications
    registry['agents'].append(agent_data)
    registry['total_spawned'] += 1
    registry['active_count'] += 1
    return registry

try:
    registry = atomic_registry_update(registry_path, update_registry)
except ValueError as e:
    return {"success": False, "error": str(e)}
```

**Files to Update:**
- `deploy_headless_agent`: Lines 2171-2437
- `update_agent_progress`: Lines 4501-4558
- `kill_real_agent`: Lines ~3915-3918 (needs audit)

**Estimated Time:** 3-4 hours

---

### Fix #2: Add Deduplication Checks in `spawn_child_agent` (IMMEDIATE - CRITICAL)
**Location:** `real_mcp_server.py:4661-4675`

**Solution:**
```python
@mcp.tool
def spawn_child_agent(task_id: str, parent_agent_id: str, child_agent_type: str, child_prompt: str):
    # Find task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {"success": False, "error": f"Task {task_id} not found"}

    registry_path = f"{workspace}/AGENT_REGISTRY.json"

    # Use atomic read
    with open(registry_path, 'r') as f:
        registry = json.load(f)

    # DEDUPLICATION CHECK #1: Verify parent exists and is active
    parent_agent = None
    for agent in registry['agents']:
        if agent['id'] == parent_agent_id:
            parent_agent = agent
            break

    if not parent_agent:
        return {"success": False, "error": f"Parent agent {parent_agent_id} not found"}

    if parent_agent['status'] not in ['running', 'working', 'blocked']:
        return {"success": False, "error": f"Parent agent {parent_agent_id} not active (status: {parent_agent['status']})"}

    # DEDUPLICATION CHECK #2: Check if parent already has this child type
    existing_children = registry['agent_hierarchy'].get(parent_agent_id, [])
    for child_id in existing_children:
        for agent in registry['agents']:
            if agent['id'] == child_id and agent['type'] == child_agent_type:
                # Check if still active
                if agent['status'] in ['running', 'working', 'blocked']:
                    logger.warning(f"Parent {parent_agent_id} already has active {child_agent_type} child: {child_id}")
                    return {
                        "success": False,
                        "error": f"Duplicate child: Parent already has active {child_agent_type} agent ({child_id})",
                        "existing_child_id": child_id
                    }

    # DEDUPLICATION CHECK #3: Depth limit validation
    parent_depth = parent_agent.get('depth', 1)
    if parent_depth >= registry.get('max_depth', 5):
        return {"success": False, "error": f"Max depth reached: parent depth {parent_depth}"}

    # Proceed with spawn
    return deploy_headless_agent.fn(task_id, child_agent_type, child_prompt, parent_agent_id)
```

**Estimated Time:** 1-2 hours

---

### Fix #3: Consolidate Registry Reads (IMMEDIATE - MEDIUM)
**Location:** `real_mcp_server.py:2171-2210`

**Solution:**
```python
# Load registry ONCE at line 2171
with open(registry_path, 'r') as f:
    registry = json.load(f)

# Anti-spiral checks (lines 2174-2185) - use 'registry'

# Parent depth calculation (lines 2192-2200) - use 'registry' directly
if parent != "orchestrator":
    for agent in registry['agents']:
        if agent['id'] == parent:
            depth = agent.get('depth', 1) + 1
            break

# Task description (lines 2206-2208) - use 'registry' directly
task_description = registry.get('task_description', '')
max_depth = registry.get('max_depth', 5)

# DELETE lines 2195-2196 and 2203-2204 entirely
```

**Estimated Time:** 30 minutes

---

### Fix #4: Add Resource Cleanup on Failure (HIGH PRIORITY)
**Location:** `real_mcp_server.py:2331-2488`

**Solution:**
```python
try:
    # ... existing code ...

    prompt_file = os.path.abspath(f"{workspace}/agent_prompt_{agent_id}.txt")
    with open(prompt_file, 'w') as f:
        f.write(agent_prompt)

    # Create the session
    session_result = create_tmux_session(...)

    if not session_result["success"]:
        # CLEANUP before returning
        if os.path.exists(prompt_file):
            os.remove(prompt_file)
            logger.info(f"Cleaned up prompt file after session creation failure: {prompt_file}")
        return {"success": False, "error": f"Failed to create agent session: {session_result['error']}"}

    time.sleep(2)

    if not check_tmux_session_exists(session_name):
        # CLEANUP before returning
        if os.path.exists(prompt_file):
            os.remove(prompt_file)
            logger.info(f"Cleaned up prompt file after session termination: {prompt_file}")
        return {"success": False, "error": "Agent session terminated immediately after creation"}

    # ... rest of function ...

except Exception as e:
    # CLEANUP on exception
    error_msg = f"Failed to deploy agent: {str(e)}"
    logger.error(error_msg, exc_info=True)

    # Clean up prompt file if it exists
    try:
        prompt_file = f"{workspace}/agent_prompt_{agent_id}.txt"
        if os.path.exists(prompt_file):
            os.remove(prompt_file)
            logger.info(f"Cleaned up prompt file after exception: {prompt_file}")
    except Exception as cleanup_error:
        logger.error(f"Failed to cleanup prompt file: {cleanup_error}")

    # Try to kill tmux session if it was created
    try:
        if 'session_name' in locals() and check_tmux_session_exists(session_name):
            kill_tmux_session(session_name)
            logger.info(f"Killed orphaned tmux session: {session_name}")
    except Exception as cleanup_error:
        logger.error(f"Failed to cleanup tmux session: {cleanup_error}")

    return {"success": False, "error": error_msg}
```

**Estimated Time:** 1 hour

---

### Fix #5: Add Agent Deduplication in `deploy_headless_agent` (MEDIUM PRIORITY)
**Location:** `real_mcp_server.py:2174-2185` (after existing checks)

**Solution:**
```python
# After lines 2174-2185 (existing anti-spiral checks)

# DEDUPLICATION: Check for recently spawned agents with same type and parent
recent_threshold = datetime.now() - timedelta(seconds=30)  # 30-second window
for agent in registry['agents']:
    if agent['type'] == agent_type and agent['parent'] == parent:
        # Check if spawned recently
        started_at = datetime.fromisoformat(agent['started_at'])
        if started_at > recent_threshold:
            # Check if still active
            if agent['status'] in ['running', 'working', 'blocked']:
                logger.warning(f"Recent {agent_type} agent found: {agent['id']} spawned at {agent['started_at']}")
                return {
                    "success": False,
                    "error": f"Duplicate spawn prevented: {agent_type} agent {agent['id']} spawned {int((datetime.now() - started_at).total_seconds())}s ago",
                    "existing_agent_id": agent['id'],
                    "hint": "Use spawn_child_agent with checks or wait 30s before retrying"
                }
```

**Estimated Time:** 1 hour

---

## 5. TESTING RECOMMENDATIONS

### Test #1: Concurrent Spawn Race Condition
```bash
# Spawn 10 agents in parallel without fix
for i in {1..10}; do
  claude --mcp-server-call deploy_headless_agent task_id agent_type_$i &
done
wait

# Expected WITHOUT fix: ~7-15 agents spawned (race conditions lose some)
# Expected WITH fix: Exactly 10 agents spawned (or proper rejection if limit hit)
```

### Test #2: Duplicate Child Prevention
```python
# Spawn same child twice from same parent
spawn_child_agent(task_id, parent_id, "researcher", "Find X")
spawn_child_agent(task_id, parent_id, "researcher", "Find X")  # Should fail

# Expected: Second call returns error with existing_child_id
```

### Test #3: Cleanup on Failure
```bash
# Force session creation to fail (e.g., invalid tmux)
TMUX=/nonexistent deploy_headless_agent(...)

# Check workspace for orphaned prompt files
ls -la .agent-workspace/TASK-*/agent_prompt_*.txt

# Expected WITH fix: No orphaned files
# Expected WITHOUT fix: Orphaned prompt files accumulate
```

---

## 6. LONG-TERM IMPROVEMENTS

1. **Distributed Lock Service:** For multi-machine orchestrators, replace fcntl with Redis/etcd locks
2. **Registry Database:** Replace JSON files with SQLite for ACID guarantees
3. **Agent Health Monitoring:** Daemon that periodically checks tmux sessions and syncs registry
4. **Idempotent Spawning:** Accept `agent_id` parameter to enable retry-safe spawning
5. **Spawn Queue:** Queue spawn requests, process serially to eliminate races entirely

---

## 7. ROOT CAUSE ANALYSIS

### Why This Happened
1. **Assumption of Serial Execution:** Code assumes one spawn at a time
2. **File I/O Appears Atomic:** JSON read/write seems atomic but isn't at process level
3. **No Concurrency Testing:** Tests likely spawn one agent at a time
4. **MVP Velocity:** Fast prototyping prioritized over concurrency safety

### Why It's So Bad Now
1. **Exponential Agent Growth:** Orchestrators spawn multiple agents in parallel
2. **Agent Spawning Agents:** Depth=2+ agents spawn children, multiplying race probability
3. **No Backpressure:** System keeps spawning until resource exhaustion
4. **Positive Feedback Loop:** Corruption causes confusion, causing more spawns

---

## 8. VERIFICATION CHECKLIST

After implementing fixes:

- [ ] **Test #1:** Run 20 parallel spawns, verify exact count in registry
- [ ] **Test #2:** Spawn duplicate children, verify rejection with clear error
- [ ] **Test #3:** Force deployment failures, verify no orphaned files
- [ ] **Test #4:** Kill agent mid-spawn, verify registry consistency
- [ ] **Test #5:** Load test with 100 agent orchestration, monitor for leaks
- [ ] **Test #6:** Verify global registry stays in sync with task registries
- [ ] **Test #7:** Check tmux session count matches active agent count

---

## CONCLUSION

The deployment code has **zero concurrency protection**, creating race conditions that:
1. Spawn duplicate agents
2. Corrupt active/total counts
3. Leak resources on failures
4. Accumulate ghost agents in registry

**Immediate Actions Required:**
1. Implement file locking (Fix #1) - **BLOCKS ALL OTHER WORK**
2. Add deduplication in spawn_child_agent (Fix #2) - **PREVENTS MOST DUPLICATES**
3. Consolidate registry reads (Fix #3) - **REDUCES RACE WINDOW**
4. Add cleanup on failure (Fix #4) - **STOPS RESOURCE LEAKS**

**Estimated Fix Time:** 6-8 hours total (can be parallelized with 2 developers)

**Impact if Not Fixed:** System unusable with >5 concurrent agents, registry corruption guaranteed at scale.
