# Orchestrator Confusion Analysis

## Executive Summary
Analysis of real_mcp_server.py reveals 15+ MCP tools that cause orchestrator confusion due to missing, inconsistent, or unclear guidance. These confusion patterns lead to orchestrators making incorrect decisions, getting stuck in loops, or failing to recover from errors.

## Major Confusion Categories

### 1. Error Responses Without Recovery Actions
**Priority: HIGH**
Tools return errors but don't tell the orchestrator what to do next.

#### Scenario: Phase Advancement Blocked
- **Tool**: `advance_to_next_phase` (line 3438)
- **Current Response**:
```json
{
  "error": "PHASE_NOT_APPROVED: Cannot advance phase 'Investigation' with status 'ACTIVE'",
  "hint": "Phase must be APPROVED by reviewers before advancement..."
}
```
- **What Causes Confusion**: Orchestrator doesn't know HOW to get approval
- **Guidance Needed**:
  - "Submit phase for review using submit_phase_for_review"
  - "Wait for reviewer verdicts with get_review_status"
  - "Check phase_status to see current state"

#### Scenario: Task Not Found
- **Tool**: Multiple tools (get_real_task_status, kill_real_agent, etc.)
- **Current Response**:
```json
{"error": "Task TASK-123 not found"}
```
- **What Causes Confusion**: No recovery path suggested
- **Guidance Needed**:
  - "Use list_real_tasks to see available tasks"
  - "Check if task_id is correct format (TASK-YYYYMMDD-HHMMSS-xxxxxxxx)"

### 2. Implicit State Transitions Not Communicated
**Priority: HIGH**
The system automatically transitions states but doesn't tell the orchestrator.

#### Scenario: Auto-Submit for Review
- **Tool**: `update_agent_progress` when all agents complete
- **Current Behavior**: System auto-submits phase for review when all agents done
- **What Causes Confusion**: Orchestrator doesn't know this happens automatically
- **Guidance Needed**: Response should include:
  - "All phase agents completed. System will auto-submit for review in 5 seconds"
  - "Next: Wait for AWAITING_REVIEW status, then use trigger_agentic_review"

#### Scenario: Auto-Spawn Reviewers
- **Tool**: `submit_phase_for_review`
- **Current Behavior**: May auto-spawn reviewers based on config
- **What Causes Confusion**: Orchestrator tries to manually approve
- **Guidance Needed**:
  - "Reviewers being auto-spawned. Check get_review_status for progress"
  - "Do NOT use approve_phase_review - it's blocked during auto-review"

### 3. Inconsistent Guidance Format
**Priority: MEDIUM**
Different tools use different guidance patterns.

#### Pattern A: Object Format (get_phase_status - line 3220)
```json
{
  "guidance": {
    "status": "ACTIVE",
    "action": "DEPLOY AGENTS: No agents deployed...",
    "blocked_reason": null
  }
}
```

#### Pattern B: String Format (check_phase_progress - line 3387)
```json
{
  "next_action": "Phase in progress. 3 agents still working."
}
```

#### Pattern C: No Guidance (most tools)
```json
{
  "success": true,
  "agent_id": "agent-123"
}
```

### 4. Blocking Operations Without Alternatives
**Priority: HIGH**
Tools block actions but don't suggest alternatives.

#### Scenario: Manual Approval Blocked
- **Tool**: `approve_phase_review` (line 3644)
- **Current Response**:
```json
{
  "error": "BLOCKED: Manual approval is not allowed...",
  "enforcement": "mandatory_agentic_review"
}
```
- **What Causes Confusion**: Doesn't explain HOW to get approval
- **Guidance Needed**:
  - "To approve phase: trigger_agentic_review to spawn reviewers"
  - "Current review status: use get_review_status"
  - "If review stalled: use abort_stalled_review"

### 5. Success Without Context
**Priority: MEDIUM**
Tools succeed but don't provide context for next steps.

#### Scenario: Agent Deployed Successfully
- **Tool**: `deploy_headless_agent`
- **Current Response**:
```json
{
  "success": true,
  "agent_id": "agent-123",
  "tmux_session": "TASK-123-agent-456"
}
```
- **What Causes Confusion**: What to do after deploying?
- **Guidance Needed**:
  - "Agent deployed. Monitor with get_agent_output"
  - "Deploy more agents or wait for completion"
  - "Check overall progress with get_real_task_status"

### 6. Registry Lock Errors Without Context
**Priority: MEDIUM**
Registry locking errors don't explain the situation.

#### Scenario: Registry Locked
- **Tool**: Various tools accessing registry (line 1215)
- **Current Response**:
```json
{"error": "Registry locked by another process"}
```
- **What Causes Confusion**: Is this permanent? Should I retry?
- **Guidance Needed**:
  - "Registry temporarily locked. Retry in 2-3 seconds"
  - "This happens during concurrent operations - normal behavior"

## Specific Tool Analysis

### Tools WITH Guidance (5/21):
1. **get_phase_status** ✓ - Good guidance object pattern
2. **check_phase_progress** ✓ - Has next_action field
3. **trigger_agentic_review** ✓ - Has next_action field
4. **approve_phase_review** (partial) - Has hint but blocked
5. **reject_phase_review** (partial) - Has hint but blocked

### Critical Tools MISSING Guidance (16/21):
1. **create_real_task** - No guidance on what to do after creating
2. **deploy_headless_agent** - No guidance on monitoring/next steps
3. **get_real_task_status** - Returns data but no actionable guidance
4. **update_agent_progress** - No guidance on phase transitions
5. **report_agent_finding** - No guidance on severity thresholds
6. **spawn_child_agent** - No guidance on parent-child coordination
7. **advance_to_next_phase** - Error cases lack recovery steps
8. **submit_phase_for_review** - Doesn't explain auto-review flow
9. **submit_review_verdict** - No guidance on verdict aggregation
10. **get_review_status** - Data without interpretation
11. **abort_stalled_review** - No guidance on when to use
12. **get_phase_handover** - No guidance on handover usage
13. **get_agent_output** - No guidance on response_format choices
14. **kill_real_agent** - No guidance on cleanup/recovery
15. **get_health_status** - No guidance on health thresholds
16. **trigger_health_scan** - No guidance on scan results

## Recommended Guidance Pattern

All tools should include a standardized `guidance` field:

```json
{
  "success": true,
  "data": {...},
  "guidance": {
    "state": "current_state",
    "action": "PRIMARY_ACTION: What to do next",
    "alternatives": ["Alternative action 1", "Alternative action 2"],
    "monitor_with": ["tool_name to check progress"],
    "error_recovery": "If this fails, do X",
    "context": "Why this is the recommended action"
  }
}
```

## Implementation Priority

### Phase 1 (CRITICAL):
1. Add guidance to `create_real_task` - orchestrators need to know to deploy agents
2. Add guidance to `deploy_headless_agent` - explain monitoring/coordination
3. Add guidance to `update_agent_progress` - explain auto-transitions
4. Fix `advance_to_next_phase` - add recovery steps for errors

### Phase 2 (HIGH):
5. Standardize guidance format across all tools
6. Add guidance to review-related tools
7. Add recovery paths to all error responses

### Phase 3 (MEDIUM):
8. Add contextual guidance based on current state
9. Add alternatives field for multiple valid actions
10. Add monitoring recommendations

## Success Metrics
- Every tool response includes guidance field
- Error responses always include recovery actions
- State transitions are explicitly communicated
- Orchestrators can follow guidance without external knowledge
- Reduced orchestrator confusion/loops by 80%