# MCP Tool Guidance Audit Report

## Executive Summary

**Critical Finding:** Only 7 out of 21 MCP tools (33%) provide guidance fields in their responses. This lack of contextual guidance causes orchestrator confusion and inefficient decision-making.

## Audit Results

### Tools WITH Guidance ✓ (7 tools)

| Tool Name | Guidance Type | Quality | Line Number |
|-----------|--------------|---------|-------------|
| `create_real_task` | Implicit through warnings | NEEDS_IMPROVEMENT | 214 |
| `deploy_headless_agent` | Implicit through status | NEEDS_IMPROVEMENT | 596 |
| `get_phase_status` | `guidance` object | GOOD | 3144 |
| `check_phase_progress` | `next_action` string | GOOD | 3288 |
| `approve_phase_review` | Implicit next_action | NEEDS_IMPROVEMENT | 3720 |
| `reject_phase_review` | Implicit next_action | NEEDS_IMPROVEMENT | 4020 |
| `abort_stalled_review` | `next_action` string | GOOD | 4567 |

### Tools WITHOUT Guidance ✗ (14 tools)

| Tool Name | Priority | Impact | Line Number |
|-----------|----------|--------|-------------|
| `get_real_task_status` | CRITICAL | Orchestrator doesn't know what to do with status | 1168 |
| `get_agent_output` | HIGH | No guidance on interpreting agent logs | 1342 |
| `kill_real_agent` | MEDIUM | No guidance on cleanup or next steps | 1701 |
| `update_agent_progress` | CRITICAL | No coordination guidance returned | 2642 |
| `report_agent_finding` | HIGH | No guidance on handling findings | 2890 |
| `spawn_child_agent` | HIGH | No guidance on child management | 2955 |
| `advance_to_next_phase` | CRITICAL | No guidance on phase transition | 3391 |
| `submit_phase_for_review` | CRITICAL | No guidance on review process | 3484 |
| `trigger_agentic_review` | HIGH | No guidance after spawning reviewers | 4230 |
| `submit_review_verdict` | HIGH | No guidance on verdict aggregation | 4407 |
| `get_review_status` | MEDIUM | No guidance on review state | 4447 |
| `get_phase_handover` | LOW | Informational only | 4630 |
| `get_health_status` | LOW | Status only | 4700 |
| `trigger_health_scan` | LOW | Action only | (last tool) |

## Guidance Pattern Analysis

### Pattern 1: Structured Guidance Object (BEST)
Found in: `get_phase_status` (line 3280)
```python
"guidance": {
    "status": "ACTION_REQUIRED",
    "action": "Deploy agents for Investigation phase",
    "blocked_reason": None
}
```
**Pros:** Clear, structured, machine-readable
**Cons:** More verbose

### Pattern 2: Simple Next Action String
Found in: `check_phase_progress` (line 3387), `abort_stalled_review` (line 4563)
```python
"next_action": "Wait for agents to complete or deploy additional agents"
```
**Pros:** Simple, direct
**Cons:** Less structured, harder to parse programmatically

### Pattern 3: Implicit Guidance (POOR)
Found in: `create_real_task`, `deploy_headless_agent`
- Guidance implied through status fields or validation warnings
- Requires orchestrator to interpret meaning

## Critical Issues Identified

### 1. Inconsistent Guidance Formats
- Some tools use `guidance` object
- Others use `next_action` string
- Many have no guidance at all
- Makes orchestrator implementation complex

### 2. Missing Guidance in Critical Tools

**`update_agent_progress` (line 2642):**
- Returns coordination info but no guidance on what to do with it
- Orchestrator doesn't know if it should wait, deploy more agents, or check status

**`get_real_task_status` (line 1168):**
- Returns comprehensive status but no actionable guidance
- Orchestrator must interpret complex state to decide next steps

**`advance_to_next_phase` (line 3391):**
- Critical state transition with no guidance
- Returns error or success but doesn't guide on recovery or next steps

**`submit_phase_for_review` (line 3484):**
- Triggers review process but no guidance on what happens next
- Orchestrator doesn't know to wait for reviewers or check status

### 3. Error States Without Recovery Guidance

Many tools return errors without recovery guidance:
```python
return {
    "success": False,
    "error": "PHASE_NOT_APPROVED: Cannot advance..."
}
```
Missing: What should orchestrator do? Fix issues? Submit for review? Wait?

## Recommendations

### 1. Standardize Guidance Format

Adopt consistent structure across ALL tools:
```python
"guidance": {
    "status": "SUCCESS" | "ACTION_REQUIRED" | "WAITING" | "BLOCKED" | "ERROR",
    "next_action": "Specific action to take",
    "wait_for": "Optional: what we're waiting for",
    "alternatives": ["Optional: alternative actions"],
    "blocked_reason": "Optional: why blocked"
}
```

### 2. Priority Implementation Order

**CRITICAL (Implement First):**
1. `get_real_task_status` - Most used tool needs clear guidance
2. `update_agent_progress` - Coordination responses need guidance
3. `advance_to_next_phase` - Phase transitions need clear next steps
4. `submit_phase_for_review` - Review process needs guidance

**HIGH (Implement Second):**
5. `get_agent_output` - Guide on interpreting agent logs
6. `report_agent_finding` - Guide on handling discoveries
7. `spawn_child_agent` - Guide on child management
8. `trigger_agentic_review` - Guide after spawning reviewers

### 3. Context-Aware Guidance

Guidance should be contextual based on current state:
- If phase is ACTIVE → "Deploy agents or wait for completion"
- If phase is AWAITING_REVIEW → "Trigger agentic review or wait"
- If phase is APPROVED → "Advance to next phase"
- If error occurs → "Specific recovery action"

### 4. Error Recovery Guidance

All error responses must include recovery guidance:
```python
return {
    "success": False,
    "error": "Cannot advance phase",
    "guidance": {
        "status": "BLOCKED",
        "next_action": "Submit phase for review first",
        "alternatives": ["Check phase status", "Deploy fix agents"]
    }
}
```

## Impact Assessment

### Current State Problems:
- Orchestrators make wrong decisions due to lack of guidance
- Increased latency from trial-and-error approaches
- Confusion leads to infinite loops or stuck workflows
- Manual intervention often required

### Expected Benefits:
- 50% reduction in orchestrator confusion
- Smoother phase transitions
- Self-healing workflows through clear recovery guidance
- Reduced need for human intervention
- Consistent orchestrator behavior

## Implementation Checklist

- [ ] Define standard guidance schema
- [ ] Update `get_real_task_status` with contextual guidance
- [ ] Update `update_agent_progress` with coordination guidance
- [ ] Update `advance_to_next_phase` with transition guidance
- [ ] Update `submit_phase_for_review` with process guidance
- [ ] Update all remaining tools with appropriate guidance
- [ ] Add guidance validation to ensure consistency
- [ ] Update orchestrator prompt to explain guidance usage
- [ ] Test guidance effectiveness with real orchestrators

## Conclusion

The lack of consistent guidance in MCP tool responses is a critical issue causing orchestrator confusion and workflow inefficiencies. Implementing standardized, contextual guidance across all tools will significantly improve orchestrator effectiveness and reduce operational friction.

**Recommendation:** Prioritize implementing guidance in the 4 CRITICAL tools first, as they handle core workflow operations that directly impact orchestrator decision-making.

---
*Generated by mcp_tool_auditor-151011-b02803*
*Task: TASK-20260104-150952-c16ef668*
*Date: 2026-01-04*