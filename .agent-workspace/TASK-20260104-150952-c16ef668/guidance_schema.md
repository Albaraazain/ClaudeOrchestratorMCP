# MCP Tool Guidance Pattern Schema

## Executive Summary

This document defines a standardized guidance pattern for all MCP tool responses to eliminate orchestrator confusion and improve autonomous decision-making capabilities.

## The Problem

Current MCP tools have inconsistent guidance patterns:
- Some tools use `guidance` objects with multiple fields
- Others use simple `next_action` strings
- Many tools (16 out of 21) lack guidance entirely
- Error responses often lack recovery instructions
- Implicit state changes are not communicated

## Standardized Guidance Schema

### Core Schema Definition

```json
{
  "guidance": {
    "current_state": "string",      // What state/condition the system is in
    "next_action": "string",         // Primary action the orchestrator should take
    "available_actions": [           // List of all valid actions in current state
      "string"
    ],
    "warnings": [                    // Issues needing attention (optional)
      "string"
    ],
    "blocked_reason": "string|null", // If blocked, explain why (optional)
    "context": {                     // Additional context (optional)
      "key": "value"
    }
  }
}
```

### Field Definitions

#### `current_state` (REQUIRED)
- **Purpose**: Describes the current system state or condition
- **Format**: Brief, descriptive string (e.g., "phase_active", "review_in_progress", "task_completed")
- **Examples**:
  - "phase_active_agents_working"
  - "phase_approved_ready_to_advance"
  - "review_blocked_by_failures"
  - "task_initialization"

#### `next_action` (REQUIRED)
- **Purpose**: Primary recommended action for the orchestrator
- **Format**: Action-oriented instruction starting with a verb
- **Examples**:
  - "Deploy agents using deploy_headless_agent"
  - "Wait for 3 agents to complete"
  - "Call submit_phase_for_review"
  - "Fix validation errors and retry"

#### `available_actions` (REQUIRED)
- **Purpose**: List ALL valid actions available in the current state
- **Format**: Array of action descriptors
- **Examples**:
  ```json
  [
    "deploy_headless_agent - Add more agents",
    "get_agent_output - Monitor agent progress",
    "kill_real_agent - Terminate stuck agents"
  ]
  ```

#### `warnings` (OPTIONAL)
- **Purpose**: Alert orchestrator to issues requiring attention
- **Format**: Array of warning messages
- **When to include**: When there are non-blocking issues
- **Examples**:
  ```json
  [
    "2 agents have been running for over 30 minutes",
    "Registry shows inconsistent agent counts",
    "Phase deadline approaching (2 hours remaining)"
  ]
  ```

#### `blocked_reason` (OPTIONAL)
- **Purpose**: Explain why an action cannot proceed
- **Format**: Detailed explanation string or null
- **When to include**: When the requested action is blocked
- **Examples**:
  - "Cannot advance: Current phase status is 'ACTIVE', must be 'APPROVED'"
  - "Review already in progress with review_id: rev-abc123"
  - "Maximum agent limit (45) reached"

#### `context` (OPTIONAL)
- **Purpose**: Additional contextual information
- **Format**: Key-value pairs
- **When to include**: When extra data would help decision-making
- **Examples**:
  ```json
  {
    "agents_running": 5,
    "phase_index": 2,
    "total_phases": 4,
    "elapsed_time": "15m",
    "review_id": "rev-xyz789"
  }
  ```

## Implementation Examples

### Example 1: Successful Task Creation
```json
{
  "success": true,
  "task_id": "TASK-20260104-123456-abc",
  "phases": [...],
  "guidance": {
    "current_state": "task_initialized",
    "next_action": "Deploy agents for Phase 1 using deploy_headless_agent",
    "available_actions": [
      "deploy_headless_agent - Start phase work",
      "get_real_task_status - Check task details",
      "get_phase_status - View phase state"
    ],
    "warnings": null,
    "blocked_reason": null,
    "context": {
      "first_phase": "Investigation",
      "total_phases": 3
    }
  }
}
```

### Example 2: Phase Blocked - Needs Review
```json
{
  "success": true,
  "phase_status": "ACTIVE",
  "all_agents_done": true,
  "guidance": {
    "current_state": "phase_complete_awaiting_review",
    "next_action": "Call submit_phase_for_review to request review",
    "available_actions": [
      "submit_phase_for_review - Request phase review",
      "deploy_headless_agent - Deploy additional agents",
      "get_agent_output - Check agent logs"
    ],
    "warnings": [
      "3 agents reported warnings in their findings"
    ],
    "blocked_reason": null,
    "context": {
      "completed_agents": 5,
      "phase_name": "Implementation"
    }
  }
}
```

### Example 3: Error with Recovery Guidance
```json
{
  "success": false,
  "error": "PHASE_NOT_APPROVED",
  "guidance": {
    "current_state": "phase_blocked_not_approved",
    "next_action": "Wait for review completion or call get_review_status",
    "available_actions": [
      "get_review_status - Check review progress",
      "get_phase_status - View detailed phase state",
      "trigger_agentic_review - Start review if not started"
    ],
    "warnings": null,
    "blocked_reason": "Cannot advance: Phase 'Implementation' has status 'UNDER_REVIEW', must be 'APPROVED'",
    "context": {
      "current_phase": "Implementation",
      "current_status": "UNDER_REVIEW",
      "required_status": "APPROVED"
    }
  }
}
```

### Example 4: Review in Progress
```json
{
  "success": true,
  "review_status": "in_progress",
  "guidance": {
    "current_state": "review_active",
    "next_action": "Wait for 2 remaining reviewers to submit verdicts",
    "available_actions": [
      "get_review_status - Check review progress",
      "get_agent_output - Monitor reviewer agents",
      "abort_stalled_review - Abort if reviewers crash"
    ],
    "warnings": [
      "Reviewer 'rev-agent-002' has been idle for 10 minutes"
    ],
    "blocked_reason": null,
    "context": {
      "reviewers_submitted": 1,
      "reviewers_total": 3,
      "review_id": "rev-xyz789",
      "elapsed_time": "5m"
    }
  }
}
```

## Phase-Specific Guidance Patterns

### Phase State: PENDING
```json
{
  "current_state": "phase_pending",
  "next_action": "Phase will auto-activate when ready",
  "available_actions": ["get_phase_status - Check phase details"]
}
```

### Phase State: ACTIVE
```json
{
  "current_state": "phase_active",
  "next_action": "Deploy agents using deploy_headless_agent",
  "available_actions": [
    "deploy_headless_agent - Deploy phase agents",
    "get_agent_output - Monitor agents",
    "check_phase_progress - Check completion"
  ]
}
```

### Phase State: AWAITING_REVIEW
```json
{
  "current_state": "phase_awaiting_review",
  "next_action": "Call trigger_agentic_review to spawn reviewers",
  "available_actions": [
    "trigger_agentic_review - Start review",
    "get_phase_status - Check details"
  ]
}
```

### Phase State: UNDER_REVIEW
```json
{
  "current_state": "phase_under_review",
  "next_action": "Wait for reviewer verdicts",
  "available_actions": [
    "get_review_status - Check progress",
    "abort_stalled_review - Abort if stuck"
  ]
}
```

### Phase State: APPROVED
```json
{
  "current_state": "phase_approved",
  "next_action": "Call advance_to_next_phase to proceed",
  "available_actions": [
    "advance_to_next_phase - Move to next phase",
    "get_phase_handover - Review handover document"
  ]
}
```

### Phase State: REVISING
```json
{
  "current_state": "phase_revising",
  "next_action": "Deploy agents to fix issues identified in review",
  "available_actions": [
    "deploy_headless_agent - Deploy fix agents",
    "get_review_status - Check review feedback",
    "submit_phase_for_review - Re-submit when ready"
  ]
}
```

### Phase State: REJECTED
```json
{
  "current_state": "phase_rejected",
  "next_action": "Review rejection reasons and plan fixes",
  "available_actions": [
    "get_review_status - View rejection details",
    "deploy_headless_agent - Deploy agents to fix"
  ]
}
```

### Phase State: ESCALATED
```json
{
  "current_state": "phase_escalated",
  "next_action": "Manual intervention required - all reviewers failed",
  "available_actions": [
    "approve_phase_review - Force approval with force_escalated=true",
    "trigger_agentic_review - Retry with new reviewers"
  ]
}
```

## Implementation Guidelines

### 1. Always Include Guidance
Every MCP tool response MUST include a `guidance` field, even for errors:
```python
return {
    "success": False,
    "error": "Invalid task ID",
    "guidance": {
        "current_state": "error_invalid_input",
        "next_action": "Verify task ID format and retry",
        "available_actions": ["create_real_task - Create new task"],
        "warnings": null,
        "blocked_reason": "Task ID 'invalid' does not match expected format"
    }
}
```

### 2. State-Driven Guidance
Guidance should always reflect the current state and provide state-appropriate actions:
```python
if phase_status == 'ACTIVE':
    if agents_running > 0:
        guidance["current_state"] = "phase_active_agents_working"
        guidance["next_action"] = f"Wait for {agents_running} agents to complete"
    else:
        guidance["current_state"] = "phase_active_no_agents"
        guidance["next_action"] = "Deploy agents using deploy_headless_agent"
```

### 3. Error Recovery Guidance
All error responses must include recovery guidance:
```python
if error_type == "registry_locked":
    return {
        "success": False,
        "error": "Registry locked by another process",
        "guidance": {
            "current_state": "registry_lock_conflict",
            "next_action": "Wait 5 seconds and retry",
            "available_actions": [
                "get_real_task_status - Check if lock released",
                "kill_real_agent - Terminate blocking agent if stuck"
            ],
            "blocked_reason": "Another agent is currently updating the registry"
        }
    }
```

### 4. Progressive Disclosure
Include more context for complex situations:
```python
if complex_situation:
    guidance["context"] = {
        "agents_status": agent_summary,
        "phase_progress": f"{completed}/{total}",
        "estimated_time": "10m",
        "bottlenecks": identified_issues
    }
```

### 5. Actionable Language
Use clear, imperative verbs in `next_action`:
- ✅ "Deploy 3 investigator agents using deploy_headless_agent"
- ✅ "Wait for review completion (2 of 3 reviewers done)"
- ❌ "You might want to deploy agents"
- ❌ "Review is happening"

## Tools Requiring Guidance Updates

### Priority 1 - Core Flow Tools (CRITICAL)
1. **create_real_task** - Add guidance for initial phase deployment
2. **deploy_headless_agent** - Add guidance for agent coordination
3. **get_real_task_status** - Add comprehensive state guidance
4. **update_agent_progress** - Add coordination guidance
5. **report_agent_finding** - Add finding impact guidance

### Priority 2 - Phase Management Tools
6. **advance_to_next_phase** - Enhance error guidance
7. **submit_phase_for_review** - Add review preparation guidance
8. **approve_phase_review** - Add blocking explanation
9. **reject_phase_review** - Add blocking explanation
10. **trigger_agentic_review** - Enhance existing guidance

### Priority 3 - Monitoring Tools
11. **get_agent_output** - Add interpretation guidance
12. **kill_real_agent** - Add cleanup guidance
13. **spawn_child_agent** - Add hierarchy guidance
14. **get_review_status** - Add verdict interpretation
15. **abort_stalled_review** - Enhance recovery guidance

### Priority 4 - Utility Tools
16. **get_phase_handover** - Add handover usage guidance
17. **get_health_status** - Add health action guidance
18. **trigger_health_scan** - Add scan result guidance
19. **get_task_findings** - Add finding priority guidance

## Migration Strategy

### Phase 1: Standardize Existing Guidance (Week 1)
- Update `get_phase_status` to use full schema
- Update `check_phase_progress` to use object instead of string
- Ensure consistency across phase tools

### Phase 2: Add to Core Tools (Week 1-2)
- Implement guidance in all Priority 1 tools
- Focus on error recovery guidance
- Add state transition notifications

### Phase 3: Complete Coverage (Week 2-3)
- Add guidance to remaining tools
- Implement context fields where valuable
- Add warnings for edge cases

### Phase 4: Testing & Refinement (Week 3-4)
- Test with real orchestrator scenarios
- Refine guidance language based on usage
- Document patterns that work best

## Success Metrics

1. **Coverage**: 100% of MCP tools include guidance field
2. **Consistency**: All guidance follows the standard schema
3. **Actionability**: Every guidance includes specific next_action
4. **Recovery**: All errors include recovery steps
5. **Context**: Complex states include helpful context

## Conclusion

This standardized guidance pattern will:
- Eliminate orchestrator confusion about what to do next
- Provide consistent, predictable responses across all tools
- Enable fully autonomous orchestration without human intervention
- Reduce failed orchestration attempts due to unclear state
- Improve error recovery and resilience

The schema is designed to be:
- **Comprehensive** - Covers all scenarios
- **Consistent** - Same structure everywhere
- **Actionable** - Always tells what to do
- **Contextual** - Provides necessary information
- **Extensible** - Can add fields as needed