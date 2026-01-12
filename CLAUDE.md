- how can you submit for review, and then approve yourself, this is not the intended behaviour, the intended behaviour, is to submit for review to multiple other agents, that review and decide whether you are allowed to proceed to the next phase or do the fixes like a state machine, this should all be handled in the background by the mcp as guidance and enforcer for the orchestrator

how does an agent move from one phase to another, do they create a new task? or just deploy agents, we said we want the phases mechanisim to be native and handle all logic behind the mcp, to enforce most control onto the orchestrator whether he likes it or not, as orchestrator often hellucinate or move away from track, and do it the easiest way possible, ultrathink

What SHOULD happen - MCP enforces everything:

Orchestrator calls deploy_agent →
  MCP auto-tracks phase association

Agent calls update_agent_progress(status="completed") →
  MCP checks: are ALL phase agents done? →
    YES → MCP auto-submits for review →
      MCP auto-spawns reviewer agents →
        Reviewers submit verdicts →
          MCP aggregates verdicts →
            APPROVED → MCP auto-advances phase →
              MCP returns "deploy agents for next phase: {description}"
            REJECTED → MCP keeps phase active, returns "fix issues: {findings}"

The orchestrator CANNOT:
- Self-approve
- Skip phases
- Bypass review
- Manually advance

Phase Enforcement Fixes Applied

1. advance_to_next_phase - Now Blocks Unless APPROVED

if current_status != 'APPROVED':
    return {"error": "PHASE_NOT_APPROVED: Cannot advance..."}

2. submit_phase_for_review - Auto-Triggers Reviewers

Now automatically calls _auto_spawn_phase_reviewers after setting status, preventing any manual approval path.

3. approve_phase_review - COMPLETELY BLOCKED

return {"error": "BLOCKED: Manual approval is not allowed. All approvals must come from reviewer agents."}

4. reject_phase_review - COMPLETELY BLOCKED

return {"error": "BLOCKED: Manual rejection is not allowed. All phase decisions must come from reviewer agents."}

5. get_phase_status - Enhanced with Detailed Guidance

Now returns:
- Review details (verdicts, findings summary, blockers)
- Clear actionable guidance field with what to do next
- Agent counts per phase

The Enforced Flow

1. create_real_task (phases MANDATORY)
   ↓
2. deploy_headless_agent (tagged with phase_index)
   ↓
3. Agents complete → AUTO-submit for review
   ↓
4. AUTO-spawn reviewer agents
   ↓
5. Reviewers call submit_review_verdict
   ↓
6. System aggregates verdicts → AUTO-approve/reject
   ↓
7. If APPROVED → orchestrator can call advance_to_next_phase
   If REJECTED → orchestrator must deploy fix agents

The orchestrator CANNOT:
- Self-approve ❌
- Self-reject ❌
- Skip phases ❌
- Bypass review ❌
- Manually advance before review ❌
- but be carefull we are using sqlite as registery now instead of json file
- can the global registery be sqlite aswell, since the json file has locking problems, and very buggy

## Project Context Feature (Jan 2026)

When creating tasks, you can pass `project_context` to provide testers/reviewers with critical project info:

```python
create_real_task(
    description="...",
    phases=[...],
    project_context={
        "dev_server_port": 3000,           # Port where dev server runs
        "start_command": "npm run dev",     # How to start the server
        "test_url": "http://localhost:3000", # Base URL for testing
        "framework": "Next.js",             # Framework used
        "test_credentials": {               # Optional test user credentials
            "email": "test@example.com",
            "password": "test123"
        }
    }
)
```

This info is automatically passed to:
- **Reviewer agents**: Shown in PROJECT CONTEXT section so they can verify deliverables on correct port
- **Final Testing phase agents**: Used to test against the correct server URL/port

### Why This Matters
Without project_context, testers often default to port 5173 (Vite) when the actual app might be running on:
- 3000 (Next.js, CRA)
- 4000/4010 (Backend APIs)
- 8080 (various)

### Phase Deliverables Warning
When creating phases without `deliverables` or `success_criteria`, the system now warns:
```
REVIEWER_CONTEXT_WARNING: Phases without deliverables (reviewers will see 'Not explicitly defined'): [Phase 1]
```

Always include deliverables per phase so reviewers know exactly what to verify.

## Handover System (Jan 2026 Fixes)

Handovers now auto-generate when:
1. **Phase approved via review**: `submit_review_verdict()` auto-generates handover from agent findings
2. **Phase manually advanced**: `advance_to_next_phase()` falls back to auto-generation if no explicit data

Reviewers can access handovers via:
```
mcp__claude-orchestrator__get_phase_handover(task_id="...", phase_index=0)
```

The legacy `trigger_agentic_review()` function was removed - all reviews now go through `_auto_spawn_phase_reviewers()`.

## Mandatory Final Testing Phase (Jan 2026)

**What changed:**
- Per-phase tester agents were REMOVED (unnecessary overhead for Investigation/Design phases)
- A "Final Testing" phase is now AUTO-APPENDED to every task

**How it works:**
1. When you call `create_real_task()`, if the last phase isn't already a testing phase (name contains "test", "testing", "verification", "qa", or "quality"), the system automatically appends a "Final Testing" phase
2. This phase includes:
   - Default deliverables for UI/API/test suite coverage
   - Success criteria for core flows, console errors, performance
   - Metadata tracking which phases it tests (`tests_deliverables_from`)

**Example:**
```python
# You provide:
phases = [
    {"name": "Investigation", ...},
    {"name": "Implementation", ...}
]

# System auto-appends:
# Phase 3: "Final Testing" with comprehensive testing deliverables
```

**Review flow per phase:**
- Phase N completes → 2 reviewers + 1 critique agent spawned
- NO tester agent spawned (testers only in Final Testing phase)
- Review focuses on code quality, logic, deliverables

**Final Testing phase flow:**
- Same review process (2 reviewers + 1 critique)
- Reviewers focus on test coverage and results
- `project_context` still used for port/URL info

**Skip auto-append:**
If you want to handle testing yourself, name your last phase with a testing keyword:
```python
phases = [
    {"name": "Investigation", ...},
    {"name": "Implementation", ...},
    {"name": "Testing & QA", ...}  # Won't auto-append another
]
```
- migrate all registory json files to sqlite database registeries, both global and local. ultrathink