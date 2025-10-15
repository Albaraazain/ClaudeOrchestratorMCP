# 🤖 Hardcoded Engine Selection

## Overview

The Claude Orchestrator uses **hardcoded model mapping** via explicit `engine` parameter, ensuring:
- **Codex engine** (`engine="codex"`) always uses **GPT-5** for code generation
- **Claude engine** (`engine="claude"`) always uses **Claude Sonnet 4.5** for analysis/research
- **NO environment variables** - prevents misreading behaviors completely

## How It Works

### Hardcoded Model Mapping

The system has a **simple, hardcoded dictionary** that maps engine names to models:

```python
ENGINE_TO_MODEL = {
    'claude': 'claude-sonnet-4.5',
    'codex': 'gpt-5'
}
```

This mapping:
- ✅ **Cannot be changed** via environment variables
- ✅ **Cannot be overridden** programmatically
- ✅ **Prevents misreading** of configuration
- ✅ **Explicit control** - you choose the engine for each agent

### Engine Parameter

When deploying an agent, you **must specify** the `engine` parameter:

- **`engine="codex"`** → Uses **GPT-5** (for coding/implementation)
- **`engine="claude"`** → Uses **Claude Sonnet 4.5** (for analysis/research)
- Any other value → **Error** (rejected at deployment)

## Usage Examples

### Example 1: Deploy a Codex Agent
```python
# Deploy a coding agent with explicit codex engine
agent = deploy_headless_agent(
    task_id=task_id,
    agent_type="builder",
    prompt="Build a REST API for user authentication",
    engine="codex"  # ✅ Explicitly use GPT-5
)
# Will use GPT-5 (hardcoded)
```

### Example 2: Deploy a Claude Agent
```python
# Deploy an analysis agent with explicit claude engine
agent = deploy_headless_agent(
    task_id=task_id,
    agent_type="investigator",
    prompt="Investigate database performance issues",
    engine="claude"  # ✅ Explicitly use Claude Sonnet 4.5
)
# Will use Claude Sonnet 4.5 (hardcoded)
```

### Example 3: Mixed Workflow
```python
# Step 1: Research with Claude
researcher = deploy_headless_agent(
    task_id=task_id,
    agent_type="researcher",
    prompt="Research best practices for API design",
    engine="claude"  # Analysis task → Claude
)

# Step 2: Implement with Codex
builder = deploy_headless_agent(
    task_id=task_id,
    agent_type="builder",
    prompt="Build API based on research findings",
    engine="codex",  # Coding task → GPT-5
    parent=researcher["agent_id"]
)

# Step 3: Review with Claude
reviewer = deploy_headless_agent(
    task_id=task_id,
    agent_type="reviewer",
    prompt="Review API implementation for security",
    engine="claude",  # Review task → Claude
    parent=builder["agent_id"]
)
```

### Example 4: Error Handling
```python
# This will fail with clear error
try:
    agent = deploy_headless_agent(
        task_id=task_id,
        agent_type="builder",
        prompt="Build something",
        engine="gpt"  # ❌ Invalid engine
    )
except Exception as e:
    print(e)  # "Invalid engine 'gpt'. Must be 'claude' or 'codex'"
```

## Configuration

### Hardcoded Mapping (Not Configurable)

The model mapping is **hardcoded in the source code** and **cannot be changed**:

```python
# In real_mcp_server.py - DO NOT EDIT
ENGINE_TO_MODEL = {
    'claude': 'claude-sonnet-4.5',
    'codex': 'gpt-5'
}
```

**Why hardcoded?**
- ✅ Prevents environment variable misreading
- ✅ Guarantees consistency across deployments
- ✅ No accidental model changes
- ✅ Explicit control via `engine` parameter

### Claude Flags

The `CLAUDE_FLAGS` environment variable should **NOT** include `--model`:

```bash
# ✅ CORRECT - no model flag (model is controlled by engine parameter)
export CLAUDE_FLAGS="--print --output-format stream-json --verbose --dangerously-skip-permissions"

# ❌ WRONG - model flag will be ignored anyway
export CLAUDE_FLAGS="--print --model some-model --verbose"
```

The system automatically builds the correct command with the hardcoded model.

## Verification

### Check Model Mapping
You can verify the hardcoded mapping:

```python
from real_mcp_server import get_model_for_engine, ENGINE_TO_MODEL

# Check hardcoded mapping
print(ENGINE_TO_MODEL)
# {'claude': 'claude-sonnet-4.5', 'codex': 'gpt-5'}

# Test engine resolution
print(get_model_for_engine('codex'))   # → gpt-5
print(get_model_for_engine('claude'))  # → claude-sonnet-4.5
```

### Monitor Agent Deployment
When agents are deployed, the logs show which engine and model are being used:

```
INFO - Agent builder-123456-abc (type: builder, engine: codex) using HARDCODED model: gpt-5
INFO - Agent investigator-123456-def (type: investigator, engine: claude) using HARDCODED model: claude-sonnet-4.5
```

### Check Agent Registry
After deployment, you can see the engine and model in the registry:

```python
status = get_real_task_status(task_id)
for agent in status['agents']['agents_list']:
    print(f"{agent['id']}: engine={agent['engine']}, model={agent['model']}")
```

## Benefits

✅ **Explicit Control** - You choose the engine for each agent  
✅ **No Environment Variables** - Zero configuration misreading  
✅ **Complete Override Protection** - Hardcoded mapping  
✅ **Clear Intent** - `engine="codex"` vs `engine="claude"` is obvious  
✅ **Type Safety** - Invalid engines are rejected immediately  
✅ **Audit Trail** - Engine and model stored in registry  

## Troubleshooting

### Agent Using Wrong Model
If an agent is using the wrong model:

1. Check the `engine` parameter you passed - it must be "claude" or "codex"
2. Verify in logs: look for "using HARDCODED model:" message
3. Check agent registry for the `engine` and `model` fields

### Invalid Engine Error
If you get "Invalid engine" error:

```python
# ❌ Wrong
engine="gpt-5"  # Invalid

# ✅ Correct
engine="codex"  # For GPT-5
engine="claude"  # For Claude Sonnet 4.5
```

### Environment Variable Confusion
**Remember:** The `CLAUDE_FLAGS` environment variable does NOT control model selection.
- Model selection is controlled ONLY by the `engine` parameter
- The hardcoded mapping cannot be changed
- No environment variables affect model choice

---

**Last Updated:** October 2025  
**Version:** 2.0

