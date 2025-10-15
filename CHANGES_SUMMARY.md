# 🔧 Changes Summary: Hardcoded Engine Selection

## Overview
Implemented hardcoded engine selection with explicit `engine` parameter to prevent misreading behaviors and ensure consistent model usage across all agent deployments.

## Key Changes

### 1. **Hardcoded Engine-to-Model Mapping**
**File:** `real_mcp_server.py`

- Added `ENGINE_TO_MODEL` dictionary with hardcoded mapping:
  ```python
  ENGINE_TO_MODEL = {
      'claude': 'claude-sonnet-4.5',
      'codex': 'gpt-5'
  }
  ```
- Created `get_model_for_engine(engine)` function that validates and resolves engines
- **NO environment variables** are read for model selection
- Invalid engines raise `ValueError` immediately

### 2. **Updated Function Signatures**

#### `deploy_headless_agent()`
**Added parameter:** `engine: str`

```python
def deploy_headless_agent(
    task_id: str,
    agent_type: str, 
    prompt: str,
    engine: str,  # NEW: Required parameter
    parent: str = "orchestrator"
) -> Dict[str, Any]:
```

#### `spawn_child_agent()`
**Added parameter:** `engine: str`

```python
def spawn_child_agent(
    task_id: str, 
    parent_agent_id: str, 
    child_agent_type: str, 
    child_prompt: str, 
    engine: str  # NEW: Required parameter
) -> Dict[str, Any]:
```

#### `create_agent_wrapper()`
**Added parameter:** `engine: str`

```python
def create_agent_wrapper(
    agent_id: str, 
    workspace: str, 
    agent_prompt: str, 
    agent_type: str, 
    engine: str  # NEW: Required parameter
) -> str:
```

### 3. **Model Selection Logic**

**Before:**
- Model was determined by agent type keywords (automatic detection)
- Environment variables could influence selection
- Complex matching logic

**After:**
- Model is explicitly controlled via `engine` parameter
- `engine="codex"` → GPT-5 (hardcoded)
- `engine="claude"` → Claude Sonnet 4.5 (hardcoded)
- No automatic detection, no environment variables

### 4. **Enhanced Agent Registry**

Agents now store both `engine` and `model` in registry:

```json
{
  "id": "agent-123456",
  "type": "builder",
  "engine": "codex",
  "model": "gpt-5",
  ...
}
```

### 5. **Updated Documentation**

**Files Updated:**
- `README.md` - Updated all examples to include `engine` parameter
- `MODEL_SELECTION.md` - Complete rewrite explaining hardcoded approach
- All usage examples now show explicit engine selection

## Usage Examples

### Before (Old Way - REMOVED)
```python
# Automatic detection based on agent type
agent = deploy_headless_agent(
    task_id=task_id,
    agent_type="builder",
    prompt="Build API"
)
# Model was auto-selected based on "builder" keyword
```

### After (New Way - REQUIRED)
```python
# Explicit engine selection required
agent = deploy_headless_agent(
    task_id=task_id,
    agent_type="builder",
    prompt="Build API",
    engine="codex"  # REQUIRED: explicitly choose engine
)
# Model is gpt-5 (hardcoded for codex)
```

## Breaking Changes

⚠️ **All existing code must be updated** to include the `engine` parameter:

1. **`deploy_headless_agent()`** - Now requires `engine` parameter
2. **`spawn_child_agent()`** - Now requires `engine` parameter
3. **Agent prompts** - Updated to show engine parameter in MCP function calls

## Benefits

✅ **Zero Ambiguity** - Explicit `engine="codex"` or `engine="claude"`
✅ **No Misreading** - No environment variables to misread
✅ **Hardcoded Safety** - Mapping cannot be accidentally changed
✅ **Clear Audit Trail** - Engine and model stored in registry
✅ **Type Safety** - Invalid engines rejected immediately

## Migration Guide

### Update Your Code

**Old Code:**
```python
deploy_headless_agent(
    task_id=task_id,
    agent_type="fixer",
    prompt="Fix bugs"
)
```

**New Code:**
```python
deploy_headless_agent(
    task_id=task_id,
    agent_type="fixer",
    prompt="Fix bugs",
    engine="codex"  # ADD THIS
)
```

### Engine Selection Guidelines

- **Use `engine="codex"` for:**
  - Code generation/implementation
  - Bug fixing
  - Code optimization
  - Testing code
  - Any programming tasks

- **Use `engine="claude"` for:**
  - Analysis and research
  - Investigation
  - Planning and architecture
  - Documentation
  - Non-coding tasks

## Testing

All tests pass:
- ✅ Hardcoded mapping verification
- ✅ Valid engine resolution
- ✅ Invalid engine rejection
- ✅ Environment variable isolation
- ✅ Function signature validation

## Files Modified

1. `real_mcp_server.py` - Core implementation
2. `README.md` - All examples updated
3. `MODEL_SELECTION.md` - Complete documentation rewrite
4. `progress_watchdog.sh` - Model reference updated

## Files Created

1. `CHANGES_SUMMARY.md` - This file
2. `MODEL_SELECTION.md` - Detailed engine selection guide (updated)

---

**Version:** 2.0
**Date:** October 2025
**Breaking Change:** Yes - `engine` parameter now required


