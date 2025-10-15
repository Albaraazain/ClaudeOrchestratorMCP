# 🚀 Quick Reference: Hardcoded Engine Selection

## TL;DR

✅ **Always specify `engine` parameter when deploying agents**
✅ **Use `engine="codex"` for coding tasks (GPT-5)**
✅ **Use `engine="claude"` for analysis tasks (Claude Sonnet 4.5)**
❌ **Cannot be overridden - it's hardcoded!**

## Quick Examples

### Deploy Coding Agent
```python
deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="builder",
    prompt="Build a REST API",
    engine="codex"  # ← GPT-5 for coding
)
```

### Deploy Analysis Agent
```python
deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="researcher",
    prompt="Research best practices",
    engine="claude"  # ← Claude Sonnet 4.5 for analysis
)
```

### Spawn Child Agent
```python
spawn_child_agent(
    task_id=task_id,
    parent_agent_id=parent_id,
    child_agent_type="fixer",
    child_prompt="Fix the bugs",
    engine="codex"  # ← Required parameter
)
```

## Engine Decision Tree

```
Need agent for...
│
├─ Coding/Implementation? → engine="codex" (GPT-5)
│  ├─ Building features
│  ├─ Fixing bugs
│  ├─ Writing tests
│  ├─ Code optimization
│  └─ Any programming task
│
└─ Analysis/Research? → engine="claude" (Claude Sonnet 4.5)
   ├─ Investigating issues
   ├─ Research
   ├─ Planning/Architecture
   ├─ Documentation
   └─ Non-coding tasks
```

## Hardcoded Mapping

| Engine | Model | Use For |
|--------|-------|---------|
| `"codex"` | `gpt-5` | Coding, implementation, bug fixes |
| `"claude"` | `claude-sonnet-4.5` | Analysis, research, investigation |

## Common Patterns

### Pattern 1: Research → Build → Test
```python
# Step 1: Research (Claude)
researcher = deploy_headless_agent(..., engine="claude")

# Step 2: Build (Codex)
builder = deploy_headless_agent(..., engine="codex", parent=researcher["agent_id"])

# Step 3: Test (Codex)
tester = deploy_headless_agent(..., engine="codex", parent=builder["agent_id"])
```

### Pattern 2: Parallel Analysis
```python
# All analysis tasks use Claude
for aspect in ["security", "performance", "maintainability"]:
    deploy_headless_agent(..., engine="claude")
```

### Pattern 3: Mixed Workflow
```python
# Investigate with Claude
investigator = deploy_headless_agent(..., engine="claude")

# Fix with Codex
fixer = deploy_headless_agent(..., engine="codex")

# Review with Claude
reviewer = deploy_headless_agent(..., engine="claude")
```

## Error Handling

```python
# ❌ This will fail
deploy_headless_agent(..., engine="gpt-5")
# Error: Invalid engine 'gpt-5'. Must be 'claude' or 'codex'

# ✅ This works
deploy_headless_agent(..., engine="codex")  # Correct!
```

## What's Changed?

### Old Way (REMOVED ❌)
```python
# Automatic detection - NO LONGER WORKS
deploy_headless_agent(
    task_id=task_id,
    agent_type="builder",
    prompt="Build API"
    # Model was auto-selected
)
```

### New Way (REQUIRED ✅)
```python
# Explicit engine selection - MUST USE
deploy_headless_agent(
    task_id=task_id,
    agent_type="builder",
    prompt="Build API",
    engine="codex"  # ← YOU MUST ADD THIS
)
```

## Important Notes

⚠️ **Breaking Change**: All code must be updated to include `engine` parameter

🔒 **Hardcoded**: The mapping cannot be changed via environment variables

📝 **Stored**: Both `engine` and `model` are saved in agent registry

🚫 **No Override**: There's NO way to override the model selection

## Need Help?

- **Full Guide**: See `MODEL_SELECTION.md`
- **Examples**: See `README.md`
- **Changes**: See `CHANGES_SUMMARY.md`

---

**Remember**: Just add `engine="codex"` or `engine="claude"` to every agent deployment!


