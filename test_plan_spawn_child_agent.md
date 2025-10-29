# Test Plan: spawn_child_agent FastMCP Bug Fix

**Date**: 2025-10-17
**Agent**: test_planner-213540-c1473a
**Task**: TASK-20251017-213512-5169d812

## Bug Summary

**Location**: `real_mcp_server.py:2336`
**Function**: `spawn_child_agent`
**Issue**: Calls `deploy_headless_agent()` directly instead of `deploy_headless_agent.fn()`

Both functions are decorated with `@mcp.tool`. In FastMCP, when an MCP tool calls another MCP tool, it MUST use the `.fn` attribute to access the underlying function, otherwise it tries to call a `FunctionTool` object directly which causes:
```
Error calling tool 'spawn_child_agent': 'FunctionTool' object is not callable
```

**Current Code** (line 2336):
```python
return deploy_headless_agent(task_id, child_agent_type, child_prompt, parent_agent_id)
```

**Required Fix**:
```python
return deploy_headless_agent.fn(task_id, child_agent_type, child_prompt, parent_agent_id)
```

---

## Test Strategy Overview

### Test Phases
1. **Unit Test**: Verify the fix allows spawn_child_agent to be called
2. **Integration Test**: Verify parent-child agent relationships work end-to-end
3. **Hierarchy Test**: Verify multi-level spawning (parent -> child -> grandchild)
4. **Limit Test**: Verify anti-spiral protections still work
5. **Regression Test**: Verify no existing functionality broken

---

## Detailed Test Scenarios

### Test 1: Direct spawn_child_agent Call (Critical)
**Objective**: Verify the bug is fixed and spawn_child_agent can be called without error.

**Prerequisites**:
- Apply the fix: change line 2336 to use `.fn`
- Ensure tmux is available
- Have an existing task with available agent slots

**Test Command**:
```bash
# This will be called via MCP - simulating an agent calling it
# Test via Python REPL or a test script that imports the MCP server

python3 << 'EOF'
import sys
sys.path.insert(0, '/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP')

# Import after adding to path
from real_mcp_server import spawn_child_agent

# First create a test task to spawn into
from real_mcp_server import create_real_task
task_result = create_real_task.fn(
    description="Test task for spawn_child_agent fix verification",
    priority="P2",
    client_cwd="/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP"
)
print("Task created:", task_result)

task_id = task_result.get('task_id')
if not task_id:
    print("ERROR: Failed to create task")
    sys.exit(1)

# Now test spawn_child_agent - this should NOT fail with FunctionTool error
result = spawn_child_agent.fn(
    task_id=task_id,
    parent_agent_id="orchestrator",
    child_agent_type="test_child_agent",
    child_prompt="This is a test child agent to verify spawn_child_agent fix works"
)

print("\n=== SPAWN CHILD AGENT RESULT ===")
print(result)

if result.get('success'):
    print("\n✓ TEST PASSED: spawn_child_agent successfully called without FunctionTool error")
    print(f"✓ Child agent created: {result.get('agent_id')}")
    print(f"✓ Tmux session: {result.get('session_name')}")
else:
    print("\n✗ TEST FAILED:", result.get('error'))
    sys.exit(1)
EOF
```

**Expected Output**:
```
✓ TEST PASSED: spawn_child_agent successfully called without FunctionTool error
✓ Child agent created: test_child_agent-HHMMSS-xxxxxx
✓ Tmux session: agent_test_child_agent-HHMMSS-xxxxxx
```

**Failure Indicators**:
- `'FunctionTool' object is not callable` error
- Any Python exception during spawn_child_agent.fn() call
- success: false in result

---

### Test 2: End-to-End Agent Spawning Child
**Objective**: Verify a real agent can spawn a child agent through the MCP protocol.

**Prerequisites**:
- Test 1 passed
- MCP server running and accepting connections

**Test Command**:
```bash
# Deploy a parent agent that will attempt to spawn a child
python3 << 'EOF'
import sys
sys.path.insert(0, '/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP')

from real_mcp_server import create_real_task, deploy_headless_agent
import time

# Create task
task = create_real_task.fn("Test parent-child agent spawning", "P2",
                           "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP")
task_id = task['task_id']
print(f"Task ID: {task_id}")

# Deploy parent agent with instructions to spawn a child
parent_prompt = """
You are a parent agent testing the spawn_child_agent functionality.

YOUR MISSION:
1. Report your status as 'working'
2. Call spawn_child_agent to create a child agent
3. Report finding with the child agent details
4. Report status as 'completed'

The child agent should be type 'test_child' with a simple prompt to report its status.

Use the MCP tools:
- mcp__claude-orchestrator__update_agent_progress
- mcp__claude-orchestrator__spawn_child_agent
- mcp__claude-orchestrator__report_agent_finding
"""

parent = deploy_headless_agent.fn(task_id, "parent_spawner", parent_prompt, "orchestrator")
print(f"Parent agent: {parent['agent_id']}")

# Wait for parent to attempt spawning
print("\nWaiting 30 seconds for parent agent to spawn child...")
time.sleep(30)

# Check task status
from real_mcp_server import get_real_task_status
status = get_real_task_status.fn(task_id)

print("\n=== TASK STATUS ===")
print(f"Total agents: {status['agents']['total_spawned']}")
print(f"Active agents: {status['agents']['active']}")

# Look for child agent
agents = status['agents'].get('agents_list', [])
parent_agent = None
child_agent = None

for agent in agents:
    if agent['id'] == parent['agent_id']:
        parent_agent = agent
    elif agent.get('parent') == parent['agent_id']:
        child_agent = agent

if child_agent:
    print(f"\n✓ TEST PASSED: Child agent spawned successfully")
    print(f"✓ Parent: {parent_agent['id']} (depth {parent_agent['depth']})")
    print(f"✓ Child: {child_agent['id']} (depth {child_agent['depth']})")
    print(f"✓ Hierarchy verified: {child_agent.get('parent')} -> {child_agent['id']}")
else:
    print(f"\n✗ TEST FAILED: No child agent found")
    print(f"Total agents: {len(agents)}")
    for a in agents:
        print(f"  - {a['id']} (parent: {a.get('parent')})")
EOF
```

**Expected Output**:
```
✓ TEST PASSED: Child agent spawned successfully
✓ Parent: parent_spawner-HHMMSS-xxxxxx (depth 1)
✓ Child: test_child-HHMMSS-xxxxxx (depth 2)
✓ Hierarchy verified: parent_spawner-HHMMSS-xxxxxx -> test_child-HHMMSS-xxxxxx
```

---

### Test 3: Multi-Level Hierarchy (Grandchild Spawning)
**Objective**: Verify agents can spawn children who spawn their own children (3 levels deep).

**Test Command**:
```bash
# Similar to Test 2, but parent spawns child with instructions to spawn grandchild
python3 << 'EOF'
import sys, time
sys.path.insert(0, '/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP')

from real_mcp_server import create_real_task, deploy_headless_agent, get_real_task_status

task = create_real_task.fn("Test 3-level hierarchy spawning", "P2",
                           "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP")
task_id = task['task_id']

# Deploy grandparent with instructions to spawn child who spawns grandchild
grandparent_prompt = """
Test agent for multi-level spawning.

MISSION:
1. Report status='working'
2. Spawn a child agent of type 'middle_child' with instructions to spawn its own child
3. Report finding when child spawned
4. Wait and check if grandchild appears
5. Report completion

Child prompt should instruct it to spawn a 'grandchild_agent' type agent.
"""

gp = deploy_headless_agent.fn(task_id, "grandparent", grandparent_prompt, "orchestrator")
print(f"Grandparent: {gp['agent_id']}")

# Wait for multi-level spawning
print("\nWaiting 60 seconds for multi-level spawning...")
time.sleep(60)

status = get_real_task_status.fn(task_id)
agents = status['agents'].get('agents_list', [])

# Build hierarchy
hierarchy = {"orchestrator": []}
for agent in agents:
    parent = agent.get('parent', 'orchestrator')
    if parent not in hierarchy:
        hierarchy[parent] = []
    hierarchy[parent].append(agent['id'])

# Check for 3 levels
levels = 0
current_level = hierarchy.get('orchestrator', [])
depth_map = {}

def count_levels(parent, level=1):
    children = hierarchy.get(parent, [])
    if not children:
        return level
    max_level = level
    for child in children:
        child_level = count_levels(child, level + 1)
        max_level = max(max_level, child_level)
    return max_level

max_depth = count_levels('orchestrator')

print(f"\n=== HIERARCHY TEST RESULTS ===")
print(f"Max depth achieved: {max_depth}")
print(f"Total agents spawned: {len(agents)}")

if max_depth >= 3:
    print(f"✓ TEST PASSED: Successfully spawned 3+ level hierarchy")
    # Print tree
    def print_tree(parent, indent=0):
        children = hierarchy.get(parent, [])
        for child in children:
            print("  " * indent + f"└─ {child}")
            print_tree(child, indent + 1)
    print("\nHierarchy tree:")
    print("orchestrator")
    print_tree('orchestrator', 1)
else:
    print(f"✗ TEST FAILED: Only reached depth {max_depth}, expected 3+")
EOF
```

**Expected Output**:
```
✓ TEST PASSED: Successfully spawned 3+ level hierarchy
Max depth achieved: 3
Hierarchy tree:
orchestrator
  └─ grandparent-HHMMSS-xxxxxx
    └─ middle_child-HHMMSS-xxxxxx
      └─ grandchild_agent-HHMMSS-xxxxxx
```

---

### Test 4: Anti-Spiral Limits
**Objective**: Verify spawn_child_agent respects max_concurrent and max_agents limits.

**Test Command**:
```bash
# Attempt to spawn more agents than allowed
python3 << 'EOF'
import sys, json
sys.path.insert(0, '/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP')

from real_mcp_server import create_real_task, spawn_child_agent
import os

task = create_real_task.fn("Test agent limits", "P2",
                           "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP")
task_id = task['task_id']
workspace = task['workspace']

# Check current limits
registry_path = f"{workspace}/AGENT_REGISTRY.json"
with open(registry_path) as f:
    registry = json.load(f)

max_agents = registry['max_agents']
max_concurrent = registry['max_concurrent']

print(f"Limits: max_agents={max_agents}, max_concurrent={max_concurrent}")

# Try to spawn max_agents + 1
successes = 0
failures = 0
last_error = None

for i in range(max_agents + 2):
    result = spawn_child_agent.fn(
        task_id=task_id,
        parent_agent_id="orchestrator",
        child_agent_type=f"limit_test_{i}",
        child_prompt=f"Test agent {i} for limit testing"
    )

    if result.get('success'):
        successes += 1
        print(f"  Agent {i}: spawned")
    else:
        failures += 1
        last_error = result.get('error')
        print(f"  Agent {i}: BLOCKED - {last_error}")

print(f"\n=== LIMIT TEST RESULTS ===")
print(f"Successfully spawned: {successes}")
print(f"Blocked by limits: {failures}")
print(f"Last error: {last_error}")

if failures > 0 and "Max agents reached" in last_error:
    print(f"✓ TEST PASSED: Anti-spiral limits working correctly")
elif failures > 0 and "Too many active" in last_error:
    print(f"✓ TEST PASSED: Concurrent limit enforced")
else:
    print(f"✗ TEST FAILED: Limits not enforced properly")
    print(f"Expected: Should block after {max_agents} agents")
    print(f"Actual: {successes} spawned, {failures} blocked")
EOF
```

**Expected Output**:
```
✓ TEST PASSED: Anti-spiral limits working correctly
Successfully spawned: 20
Blocked by limits: 2
Last error: Max agents reached (20/20)
```

---

### Test 5: Regression Test - Existing Functionality
**Objective**: Verify the fix doesn't break other MCP tool cross-calls.

**Test Command**:
```bash
# Test update_agent_progress and report_agent_finding (which also use .fn)
python3 << 'EOF'
import sys
sys.path.insert(0, '/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP')

from real_mcp_server import (
    create_real_task,
    deploy_headless_agent,
    update_agent_progress,
    report_agent_finding
)

task = create_real_task.fn("Regression test", "P2",
                           "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP")
task_id = task['task_id']

agent = deploy_headless_agent.fn(task_id, "regress_test", "Test agent", "orchestrator")
agent_id = agent['agent_id']

# Test update_agent_progress (uses get_status.fn internally - line 1052)
progress_result = update_agent_progress.fn(
    task_id=task_id,
    agent_id=agent_id,
    status="working",
    message="Testing regression",
    progress=50
)

print("=== update_agent_progress Test ===")
if progress_result.get('success'):
    print("✓ PASSED: update_agent_progress works")
else:
    print("✗ FAILED:", progress_result)

# Test report_agent_finding (uses get_status.fn internally - line 1099)
finding_result = report_agent_finding.fn(
    task_id=task_id,
    agent_id=agent_id,
    finding_type="insight",
    severity="low",
    message="Test finding for regression",
    data={"test": True}
)

print("\n=== report_agent_finding Test ===")
if finding_result.get('success'):
    print("✓ PASSED: report_agent_finding works")
else:
    print("✗ FAILED:", finding_result)

# Overall
if progress_result.get('success') and finding_result.get('success'):
    print("\n✓ REGRESSION TEST PASSED: All existing MCP tool cross-calls still work")
else:
    print("\n✗ REGRESSION TEST FAILED")
EOF
```

**Expected Output**:
```
✓ PASSED: update_agent_progress works
✓ PASSED: report_agent_finding works
✓ REGRESSION TEST PASSED: All existing MCP tool cross-calls still work
```

---

## Test Execution Order

**Critical Path**:
1. Test 1 (Direct call) - MUST pass before proceeding
2. Test 5 (Regression) - Verify no breakage of existing code
3. Test 2 (End-to-end) - Verify real-world usage
4. Test 3 (Hierarchy) - Verify complex scenarios
5. Test 4 (Limits) - Verify safety mechanisms

**Stop Conditions**:
- If Test 1 fails: Fix is not applied correctly, do not proceed
- If Test 5 fails: Fix broke existing functionality, must fix before proceeding
- If Test 2 fails: Real-world integration issue, investigate agent deployment

---

## Success Criteria

The fix is considered complete and verified when:

✓ Test 1 passes - spawn_child_agent can be called without FunctionTool error
✓ Test 2 passes - Real agents can spawn children through MCP protocol
✓ Test 3 passes - Multi-level hierarchies work (3+ levels deep)
✓ Test 4 passes - Anti-spiral limits still enforced
✓ Test 5 passes - No regression in existing update_agent_progress or report_agent_finding

**Evidence Required**:
- All 5 tests pass
- No "FunctionTool object is not callable" errors
- Parent-child relationships correctly tracked in registry
- Depth levels correctly calculated
- Tmux sessions properly created for child agents

---

## Known Edge Cases to Monitor

1. **Concurrent spawning**: Multiple agents spawning children simultaneously
   - Registry locking/race conditions
   - Accurate active_count tracking

2. **Agent depth calculation**: Ensure child depth = parent depth + 1
   - Verify in registry after spawning
   - Check depth propagates correctly through hierarchy

3. **Orphaned children**: If parent crashes during spawn
   - Child should still be registered
   - Child should be killable

4. **Max depth limit**: If max_depth is reached
   - Should block spawning with clear error
   - Should not crash or corrupt registry

---

## Additional Verification

After all tests pass, manually verify:

```bash
# Check no other @mcp.tool cross-calls are missing .fn
grep -n "return.*def.*(" real_mcp_server.py | grep "@mcp.tool" -B 5

# Check all known .fn usages are correct
grep -n "\.fn(" real_mcp_server.py
```

Expected .fn usages (should see at least these):
- Line 1052: `get_status.fn(task_id, ...)`
- Line 1099: `get_status.fn(task_id, ...)`
- Line 2336: `deploy_headless_agent.fn(task_id, ...)`

---

## Test Artifacts

All test runs should produce:
- Console output showing pass/fail for each test
- Task workspace with AGENT_REGISTRY.json showing spawned agents
- Progress logs showing agent updates
- Finding logs showing agent discoveries

Save test results to: `/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/test_results_spawn_child_agent.log`

---

## Automation Considerations

For CI/CD integration:
- Ensure tmux is available in test environment
- Each test should cleanup agents after completion
- Tests should run in isolated task workspaces
- May need to mock tmux for unit tests if tmux not available in CI

Recommended: Create a `test_spawn_child_agent.py` pytest file with these scenarios.
