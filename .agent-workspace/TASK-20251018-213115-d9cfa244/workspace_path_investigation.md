# Workspace Path Investigation: ${workspaceFolder} Issue

**Investigation Date:** 2025-10-18
**Investigator:** workspace_path_investigator-213147-db6fbe

---

## Executive Summary

**ROOT CAUSE:** Claude Code/Codex MCP client is passing the LITERAL string `"${workspaceFolder}/.agent-workspace"` to the MCP server without expanding it. This is a VSCode/Claude Code template variable that should be resolved to the actual project directory before being passed as an environment variable.

**IMPACT:** 5 tasks created in wrong location, split across two workspace directories.

---

## Detailed Findings

### 1. Source of ${workspaceFolder}

**Location:** Claude Code's MCP configuration (Codex MCP connection manager)

**Evidence from logs:**
```
env: Some({
  "CLAUDE_ORCHESTRATOR_WORKSPACE": "${workspaceFolder}/.agent-workspace",
  ...
})
```

**File:** real_mcp_server.py:38
```python
WORKSPACE_BASE = os.getenv('CLAUDE_ORCHESTRATOR_WORKSPACE', os.path.abspath('.agent-workspace'))
```

The environment variable is being set by Claude Code/Codex when it launches the MCP server, but **${workspaceFolder} is NOT being expanded** - it's passed as a literal string.

**NOT found in:**
- `.mcp.json` (this file only has command, not env vars)
- Shell config files (~/.zshrc, ~/.bashrc, etc.)
- Project-level config files

### 2. Timeline of Literal Directory Creation

**Literal Directory:**
- Path: `${workspaceFolder}/.agent-workspace/`
- Created: Oct 17, 2025 21:35
- Tasks inside: 5 tasks
  - TASK-20251017-213512-5169d812
  - TASK-20251017-215604-df6a3cbd
  - TASK-20251018-212410-ec53cbb6
  - TASK-20251018-213115-d9cfa244 (current task)
  - registry/

**Proper Directory:**
- Path: `/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/.agent-workspace/`
- Created: Oct 17, 2025 21:57
- Tasks inside: 58 tasks (from Sept 14 - Oct 18)

### 3. Why resolve_workspace_variables() Isn't Being Called

**Function Location:** real_mcp_server.py:1051-1100

**What it does:**
- Resolves template variables like `${workspaceFolder}` to actual paths
- Uses `os.getcwd()` to get current project directory
- Handles multiple variable formats

**The Problem:**
- The function EXISTS and is CORRECT
- But it's ONLY called at line 1351 (in one specific context)
- It's NOT called on `WORKSPACE_BASE` during initialization at line 38
- By the time Python reads `os.getenv('CLAUDE_ORCHESTRATOR_WORKSPACE')`, the damage is done - it's already a literal string

**Current Usage:**
```python
# Line 38: Environment variable read WITHOUT resolution
WORKSPACE_BASE = os.getenv('CLAUDE_ORCHESTRATOR_WORKSPACE', os.path.abspath('.agent-workspace'))

# Line 1051-1100: Function definition (correct, but unused for this case)
def resolve_workspace_variables(path: str) -> str:
    ...

# Line 1351: Only place it's called (not for WORKSPACE_BASE)
```

### 4. Impact Assessment

**Tasks Affected:** 5 tasks in wrong location (Oct 17-18)

**Functionality Status:**
- Tasks in literal directory: Likely orphaned/inaccessible
- Tasks in proper directory: Working correctly
- Current task (TASK-20251018-213115-d9cfa244): Created in wrong location

**Migration Required:** Yes, move 5 tasks from literal to proper location

---

## Recommended Solutions

### Option 1: Fix in real_mcp_server.py (Server-Side Fix)
**Recommended** - More reliable, doesn't depend on client behavior

```python
# Line 38: Add resolution
WORKSPACE_BASE = resolve_workspace_variables(
    os.getenv('CLAUDE_ORCHESTRATOR_WORKSPACE', os.path.abspath('.agent-workspace'))
)
```

**However:** This creates a chicken-and-egg problem because `resolve_workspace_variables()` is defined AFTER `WORKSPACE_BASE` (line 1051 vs line 38).

**Solution:** Move `resolve_workspace_variables()` function definition BEFORE line 38, or use inline resolution.

### Option 2: Fix in Claude Code/Codex (Client-Side Fix)
Claude Code/Codex should expand `${workspaceFolder}` BEFORE passing it to the MCP server.

**Required Change:** In Claude Code's MCP configuration handling, expand template variables before setting environment variables.

### Option 3: Hybrid Approach (Most Robust)
1. Client expands variables when possible
2. Server also validates and re-expands as safety net

---

## Code References

- **WORKSPACE_BASE initialization:** real_mcp_server.py:38
- **resolve_workspace_variables() function:** real_mcp_server.py:1051-1100
- **resolve_workspace_variables() usage:** real_mcp_server.py:1351
- **MCP config:** .mcp.json (no env vars here)
- **Actual env var source:** Claude Code/Codex MCP connection manager (internal)

---

## Testing Verification

```bash
# Current state
$ echo "$CLAUDE_ORCHESTRATOR_WORKSPACE"
${workspaceFolder}/.agent-workspace

# What it should be
/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/.agent-workspace

# Directory structure
$ ls -la /Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/ | grep workspace
drwxr-xr-x@  3 albaraa  staff      96 Oct 17 21:35 ${workspaceFolder}
drwxr-xr-x@ 60 albaraa  staff    1920 Oct 17 21:57 .agent-workspace

# Task counts
- Proper location: 58 tasks
- Wrong location: 5 tasks
```

---

## Conclusion

The issue is definitively a **variable expansion problem in the MCP client** (Claude Code/Codex). The MCP server receives a literal `"${workspaceFolder}"` string instead of the expanded path.

**Immediate Fix:** Modify real_mcp_server.py line 38 to call resolve_workspace_variables() on the env var value.

**Long-term Fix:** Update Claude Code/Codex to expand template variables before passing to MCP servers.
