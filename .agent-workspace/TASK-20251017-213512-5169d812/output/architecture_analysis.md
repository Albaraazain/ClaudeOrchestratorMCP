# FastMCP Architecture Analysis
## Tool Dependency Graph and .fn Pattern Compliance

**Analysis Date:** 2025-10-17
**Analyzed By:** architecture_analyzer-213538-2fff2c
**File Analyzed:** real_mcp_server.py

---

## Executive Summary

This analysis maps the complete dependency graph of all @mcp.tool and @mcp.resource decorated functions in real_mcp_server.py, identifying which tools call other tools and verifying correct usage of the `.fn` pattern required by FastMCP.

### Key Finding
**CRITICAL BUG CONFIRMED:** spawn_child_agent (line 2336) calls deploy_headless_agent without .fn attribute

---

## Complete Tool Inventory

### @mcp.tool Functions (8 total)

| Line | Function Name | Purpose |
|------|---------------|---------|
| 1100 | `create_real_task` | Create orchestration task with workspace |
| 1200 | `deploy_headless_agent` | Deploy agent using tmux background execution |
| 1500 | `get_real_task_status` | Get detailed task and agent status |
| 1635 | `get_agent_output` | Get output from running agent's tmux session |
| 1699 | `kill_real_agent` | Terminate agent by killing tmux session |
| 2120 | `update_agent_progress` | Agent self-reporting progress (returns coordination data) |
| 2261 | `report_agent_finding` | Agent reporting discoveries (returns coordination data) |
| 2321 | `spawn_child_agent` | Agent spawning child agents |

### @mcp.resource Functions (3 total)

| Line | Function Name | URI Pattern | Purpose |
|------|---------------|-------------|---------|
| 2338 | `list_real_tasks` | tasks://list | List all real tasks |
| 2352 | `get_task_resource` | task://{task_id}/status | Get task details as resource |
| 2358 | `get_task_progress_timeline` | task://{task_id}/progress-timeline | Get comprehensive progress timeline |

### Helper Functions (Non-Decorated)

| Line | Function Name | Purpose |
|------|---------------|---------|
| 1796 | `get_comprehensive_task_status` | Internal coordination helper - returns all agents' progress/findings |
| 1882 | `validate_agent_completion` | 4-layer validation of agent completion claims |

---

## Tool Dependency Graph

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           MCP TOOL DEPENDENCIES                          │
└─────────────────────────────────────────────────────────────────────────┘

Level 1: Entry Point Tools (No dependencies on other @mcp.tool)
├── create_real_task (line 1100)
│   └── No @mcp.tool dependencies ✓
│
├── deploy_headless_agent (line 1200)
│   └── No @mcp.tool dependencies ✓
│
├── get_real_task_status (line 1500)
│   └── No @mcp.tool dependencies ✓
│
├── get_agent_output (line 1635)
│   └── No @mcp.tool dependencies ✓
│
└── kill_real_agent (line 1699)
    └── No @mcp.tool dependencies ✓

Level 2: Coordination Tools (Call helper functions)
├── update_agent_progress (line 2120)
│   └── Calls: get_comprehensive_task_status() [Helper function - CORRECT ✓]
│       └── Line 2246: comprehensive_status = get_comprehensive_task_status(task_id)
│
└── report_agent_finding (line 2261)
    └── Calls: get_comprehensive_task_status() [Helper function - CORRECT ✓]
        └── Line 2305: comprehensive_status = get_comprehensive_task_status(task_id)

Level 3: Proxy/Delegation Tools (Call other @mcp.tool functions)
└── spawn_child_agent (line 2321) ⚠️ BUG CONFIRMED
    └── Calls: deploy_headless_agent() [MISSING .fn - CRITICAL BUG]
        └── Line 2336: return deploy_headless_agent(task_id, child_agent_type, child_prompt, parent_agent_id)
        └── MUST BE: return deploy_headless_agent.fn(task_id, child_agent_type, child_prompt, parent_agent_id)

Resource Layer: @mcp.resource functions (May call @mcp.tool)
├── list_real_tasks (line 2338)
│   └── No @mcp.tool dependencies ✓
│
├── get_task_resource (line 2352) ⚠️ NEEDS INVESTIGATION
│   └── Calls: get_real_task_status() [Missing .fn - MEDIUM RISK]
│       └── Line 2355: result = get_real_task_status(task_id)
│       └── QUESTION: Does @mcp.resource wrap functions the same way as @mcp.tool?
│
└── get_task_progress_timeline (line 2358)
    └── No @mcp.tool dependencies ✓
```

---

## Dependency Analysis Details

### 1. create_real_task (line 1100)
- **Type:** Entry point tool
- **Dependencies:** None (only calls helper functions and standard library)
- **.fn Pattern Compliance:** N/A - no cross-tool calls ✓

### 2. deploy_headless_agent (line 1200)
- **Type:** Entry point tool
- **Dependencies:** None (only calls helper functions)
- **.fn Pattern Compliance:** N/A - no cross-tool calls ✓

### 3. get_real_task_status (line 1500)
- **Type:** Entry point tool
- **Dependencies:** None (only calls helper functions)
- **.fn Pattern Compliance:** N/A - no cross-tool calls ✓

### 4. get_agent_output (line 1635)
- **Type:** Entry point tool
- **Dependencies:** None (only calls helper functions)
- **.fn Pattern Compliance:** N/A - no cross-tool calls ✓

### 5. kill_real_agent (line 1699)
- **Type:** Entry point tool
- **Dependencies:** None (only calls helper functions)
- **.fn Pattern Compliance:** N/A - no cross-tool calls ✓

### 6. update_agent_progress (line 2120)
- **Type:** Coordination tool (returns comprehensive agent status)
- **Dependencies:**
  - `get_comprehensive_task_status(task_id)` at line 2246
    - **Status:** CORRECT ✓
    - **Reason:** get_comprehensive_task_status is NOT an @mcp.tool, it's a regular helper function (line 1796), so direct call is correct
- **.fn Pattern Compliance:** COMPLIANT ✓

### 7. report_agent_finding (line 2261)
- **Type:** Coordination tool (returns comprehensive agent status)
- **Dependencies:**
  - `get_comprehensive_task_status(task_id)` at line 2305
    - **Status:** CORRECT ✓
    - **Reason:** get_comprehensive_task_status is NOT an @mcp.tool, it's a regular helper function (line 1796), so direct call is correct
- **.fn Pattern Compliance:** COMPLIANT ✓

### 8. spawn_child_agent (line 2321) ⚠️ CRITICAL BUG
- **Type:** Proxy/delegation tool
- **Dependencies:**
  - `deploy_headless_agent(task_id, child_agent_type, child_prompt, parent_agent_id)` at line 2336
    - **Status:** INCORRECT - MISSING .fn ❌
    - **Bug Type:** FunctionTool self-invocation error
    - **Current Code:** `return deploy_headless_agent(task_id, child_agent_type, child_prompt, parent_agent_id)`
    - **Fixed Code:** `return deploy_headless_agent.fn(task_id, child_agent_type, child_prompt, parent_agent_id)`
    - **Impact:** When agents call spawn_child_agent MCP tool, they get 'FunctionTool' object is not callable error
    - **Severity:** CRITICAL - blocks all agent child spawning functionality
- **.fn Pattern Compliance:** NON-COMPLIANT ❌

### 9. get_task_resource (line 2352) ⚠️ NEEDS INVESTIGATION
- **Type:** Resource function (@mcp.resource, not @mcp.tool)
- **Dependencies:**
  - `get_real_task_status(task_id)` at line 2355
    - **Status:** UNKNOWN - May need .fn pattern ⚠️
    - **Current Code:** `result = get_real_task_status(task_id)`
    - **Potential Fix:** `result = get_real_task_status.fn(task_id)`
    - **Question:** Does @mcp.resource decorator wrap functions the same way @mcp.tool does?
    - **Severity:** MEDIUM - needs verification
- **.fn Pattern Compliance:** UNKNOWN ⚠️

---

## Call Patterns Identified

### Pattern 1: Direct Entry Points (Safe)
Most @mcp.tool functions are entry points that don't call other @mcp.tool functions. They only call:
- Standard library functions
- Helper functions (not decorated)
- External libraries

**Functions Following This Pattern:**
- create_real_task
- deploy_headless_agent
- get_real_task_status
- get_agent_output
- kill_real_agent

**Risk:** LOW - No cross-tool invocation issues ✓

### Pattern 2: Coordination Tools Calling Helpers (Safe)
Tools that call non-decorated helper functions to aggregate data.

**Functions Following This Pattern:**
- update_agent_progress → calls get_comprehensive_task_status (helper)
- report_agent_finding → calls get_comprehensive_task_status (helper)

**Risk:** LOW - Helpers are not @mcp.tool decorated, so direct calls are correct ✓

### Pattern 3: Proxy/Delegation Tools (HIGH RISK)
Tools that delegate to other @mcp.tool functions. **MUST USE .fn PATTERN**

**Functions Following This Pattern:**
- spawn_child_agent → calls deploy_headless_agent (@mcp.tool) ❌ MISSING .fn

**Risk:** CRITICAL - Will fail at runtime with 'FunctionTool' object is not callable ❌

### Pattern 4: Resources Calling Tools (UNKNOWN RISK)
@mcp.resource decorated functions that call @mcp.tool functions.

**Functions Following This Pattern:**
- get_task_resource → calls get_real_task_status (@mcp.tool) ⚠️ May need .fn

**Risk:** MEDIUM - Needs investigation of @mcp.resource wrapping behavior ⚠️

---

## Risk Assessment

### Critical Issues (Must Fix)
1. **spawn_child_agent:2336** - Missing .fn when calling deploy_headless_agent
   - **Impact:** Blocks all agent spawning functionality
   - **Fix Required:** Change to `deploy_headless_agent.fn(...)`

### Medium Priority Issues (Needs Investigation)
2. **get_task_resource:2355** - May need .fn when calling get_real_task_status
   - **Impact:** Resource endpoints may fail
   - **Investigation Needed:** Test if @mcp.resource wraps functions like @mcp.tool
   - **Potential Fix:** Change to `get_real_task_status.fn(...)` if needed

### No Issues Detected
- update_agent_progress correctly calls helper function (not @mcp.tool)
- report_agent_finding correctly calls helper function (not @mcp.tool)
- All entry point tools have no cross-tool dependencies

---

## Best Practices Recommendations

### 1. FastMCP .fn Pattern Rule
**When @mcp.tool calls another @mcp.tool:**
```python
# ❌ WRONG - Will fail at runtime
@mcp.tool
def tool_a():
    result = tool_b()  # Error: 'FunctionTool' object is not callable

# ✓ CORRECT - Use .fn to access underlying function
@mcp.tool
def tool_a():
    result = tool_b.fn()  # Works correctly
```

### 2. Helper Functions Pattern (Recommended)
For shared logic between tools, use non-decorated helper functions:
```python
# Helper function (no decorator)
def get_comprehensive_task_status(task_id: str):
    # Shared logic here
    return data

# Tools can call helper directly
@mcp.tool
def update_agent_progress(...):
    status = get_comprehensive_task_status(task_id)  # ✓ Direct call OK
```

### 3. Delegation/Proxy Pattern (Use Sparingly)
If you must have one @mcp.tool call another, always use .fn:
```python
@mcp.tool
def spawn_child_agent(...):
    return deploy_headless_agent.fn(...)  # ✓ Use .fn for tool-to-tool calls
```

### 4. Architectural Recommendation
**Minimize tool-to-tool dependencies.** Prefer:
- Helper functions for shared logic
- Direct implementation over delegation
- Flat tool hierarchy over nested tool calls

This reduces complexity and avoids .fn pattern issues.

---

## Verification Checklist

- [x] All @mcp.tool functions identified (8 found)
- [x] All @mcp.resource functions identified (3 found)
- [x] All helper functions identified (2 found)
- [x] Cross-tool calls mapped in dependency graph
- [x] .fn pattern compliance verified for each cross-call
- [x] Critical bug identified: spawn_child_agent:2336
- [x] Medium risk identified: get_task_resource:2355
- [x] Best practices documented
- [x] Visual dependency diagram created

---

## Call Hierarchy Summary

```
LEVEL 0: Helper Functions (Non-decorated)
├── get_comprehensive_task_status (line 1796)
└── validate_agent_completion (line 1882)

LEVEL 1: Entry Point Tools (No dependencies)
├── create_real_task (line 1100)
├── deploy_headless_agent (line 1200)
├── get_real_task_status (line 1500)
├── get_agent_output (line 1635)
└── kill_real_agent (line 1699)

LEVEL 2: Coordination Tools (Call Level 0 helpers)
├── update_agent_progress (line 2120) → get_comprehensive_task_status ✓
└── report_agent_finding (line 2261) → get_comprehensive_task_status ✓

LEVEL 3: Proxy Tools (Call Level 1 tools)
└── spawn_child_agent (line 2321) → deploy_headless_agent ❌ MISSING .fn

RESOURCE LAYER: May call any level
├── list_real_tasks (line 2338) - no dependencies ✓
├── get_task_resource (line 2352) → get_real_task_status ⚠️ NEEDS .fn?
└── get_task_progress_timeline (line 2358) - no dependencies ✓
```

---

## Circular Dependencies

**Status:** None detected ✓

The dependency graph is a clean DAG (Directed Acyclic Graph) with no circular dependencies. This is good architecture.

---

## Conclusion

The FastMCP architecture in real_mcp_server.py is well-structured with minimal tool-to-tool dependencies. However, there is **1 confirmed critical bug** and **1 medium priority investigation needed**:

1. **CRITICAL:** spawn_child_agent:2336 must use `deploy_headless_agent.fn(...)` instead of `deploy_headless_agent(...)`
2. **INVESTIGATE:** get_task_resource:2355 may need `get_real_task_status.fn(...)` - requires testing @mcp.resource wrapping behavior

The existing fixes for update_agent_progress and report_agent_finding (lines 1052 & 1099 mentioned in context) were **false alarms** - those functions correctly call get_comprehensive_task_status which is a helper function, not an @mcp.tool.

---

**Analysis Complete**
**Confidence Level:** HIGH (direct code inspection of all functions)
**Evidence:** Specific line numbers and code patterns documented above
