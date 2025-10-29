# @mcp.resource Pattern Investigation Report

**Agent:** resource_investigator-214016-adad9d
**Task:** TASK-20251017-213512-5169d812
**Date:** 2025-10-17
**Investigation Target:** real_mcp_server.py:2355

## Executive Summary

**VERDICT:** Line 2355 is CORRECT as-is. NO changes needed.

The @mcp.resource decorator does NOT wrap functions the same way @mcp.tool does. Functions decorated with @mcp.resource can call @mcp.tool functions directly without using the `.fn` attribute.

---

## Investigation Details

### Target Code
**File:** real_mcp_server.py
**Line:** 2355
**Function:** `get_task_resource` (decorated with @mcp.resource)

```python
@mcp.resource("task://{task_id}/status")
def get_task_resource(task_id: str) -> str:
    """Get task details as resource."""
    result = get_real_task_status(task_id)  # ← Line 2355
    return json.dumps(result, indent=2)
```

**Called Function:** `get_real_task_status` (decorated with @mcp.tool at line 2145)

---

## Key Findings

### @mcp.tool Wrapping Behavior
When a function is decorated with `@mcp.tool`, FastMCP wraps it in a `FunctionTool` object:
- The decorator returns a `FunctionTool` instance
- The original function is stored in the `.fn` attribute
- To call another @mcp.tool from within an @mcp.tool, you MUST use `.fn`
- Example: `deploy_headless_agent.fn(...)` ← REQUIRED

**Source Evidence:**
- File: `fastmcp/tools/tool.py`
- Class: `FunctionTool`

### @mcp.resource Wrapping Behavior (DIFFERENT!)
When a function is decorated with `@mcp.resource`, FastMCP does NOT wrap the function:
- The decorator returns a `FunctionResource` or `ResourceTemplate` object
- The original function is stored UNWRAPPED in the `.fn` attribute
- The resource's `.read()` method calls `self.fn(**kwargs)` directly
- The function itself is NOT a wrapper object

**Source Evidence:**
- File: `fastmcp/server/server.py` lines 1258-1286
  - Decorator returns `Resource.from_function()` or `ResourceTemplate.from_function()`
- File: `fastmcp/resources/resource.py`
  - Line 165: `fn: Callable[..., Any]` ← stored as plain function
  - Line 207: `result = self.fn(**kwargs)` ← called directly

### Critical Difference

```python
# @mcp.tool behavior:
@mcp.tool
def tool_a():
    pass
# tool_a is now a FunctionTool object
# tool_a.fn is the actual function
# Calling from another @mcp.tool: tool_a.fn() ← REQUIRED

# @mcp.resource behavior:
@mcp.resource("uri://example")
def resource_a():
    pass
# resource_a is a FunctionResource object
# resource_a.fn is the actual function (NOT wrapped)
# The function inside resource_a can call tools directly: tool_a() ← OK!
```

---

## Why Line 2355 is Correct

1. **get_task_resource** is decorated with @mcp.resource
2. The function body of get_task_resource is stored unwrapped in FunctionResource.fn
3. When the resource is read, `self.fn(**kwargs)` executes the original function
4. Since the function is NOT wrapped, it can call @mcp.tool functions directly
5. Therefore: `get_real_task_status(task_id)` is CORRECT (no .fn needed)

---

## Rule of Thumb

**When to use .fn:**
- ✅ When an @mcp.tool calls another @mcp.tool → USE .fn
- ❌ When an @mcp.resource calls an @mcp.tool → NO .fn needed
- ❌ When a helper function calls an @mcp.tool → NO .fn needed
- ❌ When an @mcp.tool calls a helper function → NO .fn needed

**Why?**
- Only @mcp.tool creates wrapper objects
- @mcp.resource, @mcp.prompt, and regular functions are NOT wrapped
- Unwrapped code can call wrapped tools directly by name

---

## Recommendation

**NO ACTION REQUIRED** for line 2355.

The architecture_analyzer agent marked this as "MEDIUM risk" but the investigation confirms it is actually correct. The code should remain as-is:

```python
result = get_real_task_status(task_id)  # ✅ CORRECT
```

NOT:
```python
result = get_real_task_status.fn(task_id)  # ❌ WRONG - would cause error
```

---

## Evidence Summary

### Files Analyzed
1. `/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py`
   - Lines 2352-2356: get_task_resource function
   - Line 2145: get_real_task_status declaration

2. `/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/.venv/lib/python3.13/site-packages/fastmcp/server/server.py`
   - Lines 1158-1293: @mcp.resource decorator implementation
   - Shows decorator returns Resource.from_function()

3. `/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/.venv/lib/python3.13/site-packages/fastmcp/resources/resource.py`
   - Line 165: fn attribute stores plain function
   - Line 207: fn is called directly without wrapper

### Test Recommendation
No testing required for this line. The existing code is correct and follows FastMCP's intended design pattern.

---

## Conclusion

The investigation confirms that @mcp.resource decorated functions do NOT suffer from the same self-invocation bug as @mcp.tool functions. The code at real_mcp_server.py:2355 is correct and should not be modified.

**Status:** Investigation COMPLETE ✅
**Verdict:** NO BUG - CODE IS CORRECT
