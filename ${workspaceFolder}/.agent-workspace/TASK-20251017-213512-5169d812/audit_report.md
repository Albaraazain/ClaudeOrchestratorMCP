# FastMCP Tool Self-Invocation Audit Report

**Auditor:** code_auditor-213536-71587d
**Date:** 2025-10-17
**File Analyzed:** real_mcp_server.py (2432 lines)
**Task:** Identify all FastMCP @mcp.tool functions calling other @mcp.tool functions without .fn attribute

## Critical Context

In FastMCP, when an `@mcp.tool` decorated function calls another `@mcp.tool` function, you MUST use the `.fn` attribute to access the underlying function:

- ❌ WRONG: `other_tool(args)`
- ✅ CORRECT: `other_tool.fn(args)`

**Reason:** `@mcp.tool` wraps functions in a `FunctionTool` object. Direct calls fail with: `'FunctionTool' object is not callable`

## Summary of Findings

**Total @mcp.tool functions:** 8
**Total @mcp.resource functions:** 3
**Critical bugs found:** 1 (potentially 2)
**False alarms:** 2

## All @mcp.tool Functions Inventory

1. `create_real_task` (line 1100) - No cross-calls to other @mcp.tool functions ✅
2. `deploy_headless_agent` (line 1200) - No cross-calls to other @mcp.tool functions ✅
3. `get_real_task_status` (line 1500) - No cross-calls to other @mcp.tool functions ✅
4. `get_agent_output` (line 1635) - No cross-calls to other @mcp.tool functions ✅
5. `kill_real_agent` (line 1699) - No cross-calls to other @mcp.tool functions ✅
6. `update_agent_progress` (line 2120) - Calls `get_comprehensive_task_status` (NOT @mcp.tool - helper function) ✅
7. `report_agent_finding` (line 2261) - Calls `get_comprehensive_task_status` (NOT @mcp.tool - helper function) ✅
8. `spawn_child_agent` (line 2321) - ❌ **CRITICAL BUG FOUND**

## CRITICAL BUG #1: spawn_child_agent → deploy_headless_agent

**File:** real_mcp_server.py
**Line:** 2336
**Severity:** CRITICAL

**Calling Function:** `spawn_child_agent` (@mcp.tool at line 2321)
**Called Function:** `deploy_headless_agent` (@mcp.tool at line 1200)

**Current Code (WRONG):**
```python
@mcp.tool
def spawn_child_agent(task_id: str, parent_agent_id: str, child_agent_type: str, child_prompt: str) -> Dict[str, Any]:
    """Spawn a child agent - called by agents to create sub-agents."""
    # Delegate to existing deployment function
    return deploy_headless_agent(task_id, child_agent_type, child_prompt, parent_agent_id)
```

**Fixed Code (CORRECT):**
```python
@mcp.tool
def spawn_child_agent(task_id: str, parent_agent_id: str, child_agent_type: str, child_prompt: str) -> Dict[str, Any]:
    """Spawn a child agent - called by agents to create sub-agents."""
    # Delegate to existing deployment function
    return deploy_headless_agent.fn(task_id, child_agent_type, child_prompt, parent_agent_id)
```

**Impact:**
- Any agent attempting to spawn a child agent will encounter: `'FunctionTool' object is not callable`
- This breaks the entire orchestration hierarchy beyond depth=1
- Prevents agents from creating specialized sub-agents

**Confirmation:** Also confirmed by test_planner-213540-c1473a agent

## POTENTIAL BUG #2: @mcp.resource → @mcp.tool Cross-Call

**File:** real_mcp_server.py
**Line:** 2355
**Severity:** MEDIUM (requires verification)

**Calling Function:** `get_task_resource` (@mcp.resource at line 2352)
**Called Function:** `get_real_task_status` (@mcp.tool at line 1500)

**Current Code:**
```python
@mcp.resource("task://{task_id}/status")
def get_task_resource(task_id: str) -> str:
    """Get task details as resource."""
    result = get_real_task_status(task_id)
    return json.dumps(result, indent=2)
```

**Question:** Does `@mcp.resource` decorator wrap functions the same way as `@mcp.tool`?

**If YES → Fixed Code Required:**
```python
@mcp.resource("task://{task_id}/status")
def get_task_resource(task_id: str) -> str:
    """Get task details as resource."""
    result = get_real_task_status.fn(task_id)
    return json.dumps(result, indent=2)
```

**Recommendation:** Test this code path or inspect FastMCP documentation to verify if @mcp.resource has same wrapping behavior.

## FALSE ALARMS (Correctly Implemented)

### update_agent_progress → get_comprehensive_task_status (line 2246)
✅ CORRECT - `get_comprehensive_task_status` is a regular Python function (line 1796), NOT decorated with @mcp.tool

### report_agent_finding → get_comprehensive_task_status (line 2305)
✅ CORRECT - Same as above, regular function call is appropriate

## Dependency Graph of @mcp.tool Functions

```
@mcp.tool functions:
├── create_real_task (1100)
├── deploy_headless_agent (1200)
├── get_real_task_status (1500)
├── get_agent_output (1635)
├── kill_real_agent (1699)
├── update_agent_progress (2120)
│   └── calls: get_comprehensive_task_status() [regular function ✅]
├── report_agent_finding (2261)
│   └── calls: get_comprehensive_task_status() [regular function ✅]
└── spawn_child_agent (2321)
    └── calls: deploy_headless_agent() [❌ MISSING .fn]

@mcp.resource functions:
├── list_real_tasks (2338)
├── get_task_resource (2352)
│   └── calls: get_real_task_status() [⚠️ VERIFY IF .fn NEEDED]
└── get_task_progress_timeline (2358)
```

## Testing Recommendations

1. **Test spawn_child_agent fix immediately** - This is blocking orchestration functionality
2. **Test @mcp.resource → @mcp.tool call pattern** - Verify if .fn is needed for get_task_resource
3. **Add regression tests** - Ensure agents can successfully spawn children after fix
4. **Add FastMCP wrapping tests** - Verify all decorator types wrap functions consistently

## Previously Fixed Bugs (Historical Context)

From CLAUDE.md documentation, these bugs were already fixed:

### Fixed Bug #1: update_agent_progress (line 1052)
- Changed `get_status(...)` to `get_status.fn(...)`

### Fixed Bug #2: report_agent_finding (line 1099)
- Changed `get_status(...)` to `get_status.fn(...)`

**Note:** Current audit at lines 2120 and 2261 shows these call `get_comprehensive_task_status` (regular function) correctly, so different code pattern now exists.

## Audit Methodology

1. ✅ Searched for all `@mcp.tool` decorators (found 8)
2. ✅ Searched for all `@mcp.resource` decorators (found 3)
3. ✅ Read each decorated function completely
4. ✅ Identified all internal function calls
5. ✅ Verified which calls target other @mcp.tool functions
6. ✅ Checked for .fn attribute usage
7. ✅ Distinguished between @mcp.tool calls and regular function calls
8. ✅ Documented findings with line numbers and code snippets

## Conclusion

**CRITICAL FIX REQUIRED:** Line 2336 in `spawn_child_agent` must use `deploy_headless_agent.fn(...)` instead of `deploy_headless_agent(...)`

**VERIFICATION NEEDED:** Line 2355 in `get_task_resource` may need to use `get_real_task_status.fn(...)` - depends on @mcp.resource wrapping behavior

**CODE QUALITY:** Most of the codebase correctly separates @mcp.tool calls from regular helper function calls. Only 1 confirmed bug found.

---

**Evidence Quality:** HIGH
- Complete file analyzed
- All @mcp.tool functions inventoried
- Cross-references validated
- Line numbers cited
- Code snippets provided
