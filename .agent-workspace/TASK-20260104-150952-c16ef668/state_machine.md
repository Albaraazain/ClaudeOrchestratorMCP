# Phase State Machine Documentation

## Overview

The Claude Orchestrator MCP implements an 8-state phase management system to enforce proper agent coordination and review processes. This document provides complete mapping of all states, transitions, and orchestrator guidance.

## State Machine Diagram

```
┌─────────┐      ┌────────┐      ┌─────────────────┐      ┌──────────────┐      ┌──────────┐
│ PENDING │──────► ACTIVE │──────► AWAITING_REVIEW │──────► UNDER_REVIEW │──────► APPROVED │
└─────────┘      └────────┘      └─────────────────┘      └──────────────┘      └──────────┘
                      ▲                                           │                      │
                      │                                           ▼                      ▼
                      │         ┌──────────┐              ┌──────────┐         ┌────────────┐
                      └─────────│ REVISING │◄─────────────│ REJECTED │         │ COMPLETED  │
                                └──────────┘              └──────────┘         └────────────┘
                                                                  │
                                                                  ▼
                                                           ┌────────────┐
                                                           │ ESCALATED  │
                                                           └────────────┘
```

## State Definitions and Transitions

### 1. PENDING

**Definition**: Phase is queued but not yet started.

**Valid Actions**:
- Wait for current phase completion
- Cannot deploy agents yet
- Cannot transition manually

**Blocked Actions**:
- ❌ deploy_headless_agent (wrong phase)
- ❌ submit_phase_for_review (not active)
- ❌ advance_to_next_phase (not approved)

**Transitions**:
- → **ACTIVE**: Automatically when previous phase completes and advances

**Orchestrator Guidance**:
```json
{
  "status": "PENDING",
  "action": "WAIT: Phase queued. Will activate after current phase completes.",
  "blocked_reason": "Not the current active phase"
}
```

---

### 2. ACTIVE

**Definition**: Phase is currently being worked on by agents.

**Valid Actions**:
- ✅ deploy_headless_agent - Deploy agents to work on phase
- ✅ get_agent_output - Monitor agent progress
- ✅ kill_real_agent - Terminate problematic agents
- ⚠️ submit_phase_for_review - Manual submit (auto-submit preferred)

**Blocked Actions**:
- ❌ advance_to_next_phase (not approved yet)
- ❌ approve_phase_review (no review exists)
- ❌ reject_phase_review (blocked - must be from reviewers)

**Transitions**:
- → **AWAITING_REVIEW**: Automatically when all phase agents complete OR manually via submit_phase_for_review

**Orchestrator Guidance**:

**Case 1: No agents deployed**
```json
{
  "status": "ACTIVE",
  "action": "DEPLOY AGENTS: No agents deployed. Use deploy_headless_agent to start work.",
  "blocked_reason": null
}
```

**Case 2: Agents working**
```json
{
  "status": "ACTIVE",
  "action": "WAIT: 3 agents still working. Monitor with get_agent_output.",
  "blocked_reason": null
}
```

**Case 3: All agents done**
```json
{
  "status": "ACTIVE",
  "action": "REVIEW PENDING: All agents done. System will auto-trigger review.",
  "blocked_reason": null
}
```

---

### 3. AWAITING_REVIEW

**Definition**: Phase work complete, reviewer agents being spawned.

**Valid Actions**:
- ✅ get_phase_status - Check review spawn status
- ✅ get_review_status - Check if reviewers deployed

**Blocked Actions**:
- ❌ deploy_headless_agent (phase complete, review starting)
- ❌ submit_phase_for_review (already submitted)
- ❌ advance_to_next_phase (not approved)
- ❌ approve_phase_review (auto-review active)
- ❌ reject_phase_review (blocked always)

**Transitions**:
- → **UNDER_REVIEW**: Automatically after reviewer agents spawn

**Orchestrator Guidance**:
```json
{
  "status": "AWAITING_REVIEW",
  "action": "REVIEWERS SPAWNING: Agentic reviewers being deployed. Wait for UNDER_REVIEW status.",
  "blocked_reason": null
}
```

---

### 4. UNDER_REVIEW

**Definition**: Reviewer agents actively reviewing phase work.

**Valid Actions**:
- ✅ get_review_status - Monitor reviewer progress
- ✅ get_agent_output - Check individual reviewer logs
- ✅ abort_stalled_review - If reviewers crash/stall

**Blocked Actions**:
- ❌ deploy_headless_agent (review in progress)
- ❌ submit_phase_for_review (already in review)
- ❌ advance_to_next_phase (not approved)
- ❌ approve_phase_review (auto-review blocks manual)
- ❌ reject_phase_review (blocked always)

**Transitions**:
- → **APPROVED**: Automatically if majority reviewers approve
- → **REJECTED**: Automatically if reviewers find critical issues
- → **REVISING**: Automatically if reviewers request changes
- → **ESCALATED**: Automatically if all reviewers crash

**Orchestrator Guidance**:
```json
{
  "status": "UNDER_REVIEW",
  "action": "REVIEW IN PROGRESS: 2/3 reviewers submitted. Wait for verdicts.",
  "blocked_reason": null,
  "review": {
    "reviewers_submitted": 2,
    "reviewers_expected": 3
  }
}
```

---

### 5. APPROVED

**Definition**: Phase passed review, ready to advance.

**Valid Actions**:
- ✅ advance_to_next_phase - Move to next phase
- ✅ get_phase_handover - Retrieve handover doc

**Blocked Actions**:
- ❌ deploy_headless_agent (phase complete)
- ❌ submit_phase_for_review (already approved)
- ❌ approve_phase_review (already approved)
- ❌ reject_phase_review (blocked always)

**Transitions**:
- → **COMPLETED**: Via advance_to_next_phase (current phase marked complete, next becomes ACTIVE)

**Orchestrator Guidance**:

**Case 1: More phases exist**
```json
{
  "status": "APPROVED",
  "action": "PROCEED: Phase approved. Use advance_to_next_phase to start 'Implementation Phase'.",
  "blocked_reason": null
}
```

**Case 2: Final phase**
```json
{
  "status": "APPROVED",
  "action": "TASK COMPLETE: All phases approved. Task finished successfully.",
  "blocked_reason": null
}
```

---

### 6. REJECTED

**Definition**: Phase failed review due to critical issues.

**Valid Actions**:
- ✅ deploy_headless_agent - Deploy fix agents
- ✅ get_review_status - Review rejection details
- ✅ trigger_agentic_review - Spawn new reviewers after fixes

**Blocked Actions**:
- ❌ advance_to_next_phase (not approved)
- ❌ approve_phase_review (must fix and re-review)
- ❌ reject_phase_review (blocked always)

**Transitions**:
- → **REVISING**: When fix agents are deployed
- → **ACTIVE**: After fixes applied

**Orchestrator Guidance**:
```json
{
  "status": "REJECTED",
  "action": "PHASE REJECTED: Critical issues found. Review findings and deploy fix agents.",
  "blocked_reason": [
    "Security vulnerability in authentication flow",
    "Missing error handling in payment processing"
  ]
}
```

---

### 7. REVISING

**Definition**: Phase under revision after review feedback.

**Valid Actions**:
- ✅ deploy_headless_agent - Deploy agents to fix issues
- ✅ submit_phase_for_review - Re-submit after fixes
- ✅ get_agent_output - Monitor fix progress

**Blocked Actions**:
- ❌ advance_to_next_phase (not approved)
- ❌ approve_phase_review (must re-review)
- ❌ reject_phase_review (blocked always)

**Transitions**:
- → **ACTIVE**: After deploying fix agents
- → **AWAITING_REVIEW**: Via submit_phase_for_review after fixes

**Orchestrator Guidance**:
```json
{
  "status": "REVISING",
  "action": "FIX REQUIRED: Address blockers and re-submit for review.",
  "blocked_reason": [
    "Add input validation to form fields",
    "Implement proper error boundaries"
  ]
}
```

---

### 8. ESCALATED

**Definition**: Review process failed (all reviewers crashed/stalled).

**Valid Actions**:
- ✅ abort_stalled_review - Clear stalled review
- ✅ trigger_agentic_review - Spawn new reviewers
- ✅ approve_phase_review (with force_escalated=true) - Manual override

**Blocked Actions**:
- ❌ deploy_headless_agent (resolve review first)
- ❌ advance_to_next_phase (not approved)
- ❌ reject_phase_review (blocked always)

**Transitions**:
- → **AWAITING_REVIEW**: Via trigger_agentic_review after abort
- → **APPROVED**: Via approve_phase_review with force flag

**Orchestrator Guidance**:
```json
{
  "status": "ESCALATED",
  "action": "ESCALATED - MANUAL INTERVENTION REQUIRED: All reviewers crashed. Options: (1) Use abort_stalled_review and trigger_agentic_review to retry with new reviewers, (2) Use approve_phase_review with force flag if work is actually complete.",
  "blocked_reason": "All 3 reviewer agents terminated without submitting verdicts",
  "escalated": true
}
```

---

## Automatic Transitions

The system enforces several automatic state transitions to prevent manual manipulation:

| Trigger | Automatic Transition | Enforced By |
|---------|---------------------|-------------|
| All phase agents complete | ACTIVE → AWAITING_REVIEW | update_agent_progress (lines 2789-2805) |
| Reviewer agents spawned | AWAITING_REVIEW → UNDER_REVIEW | _auto_spawn_phase_reviewers |
| All reviewers submit verdicts | UNDER_REVIEW → APPROVED/REJECTED/REVISING | submit_review_verdict |
| All reviewers crash | UNDER_REVIEW → ESCALATED | Health daemon detection |
| Manual submit_phase_for_review | Auto-spawns reviewers | Lines 3531-3548 |

## Enforcement Rules

### What the Orchestrator CANNOT Do

1. **Self-approve phases**
   - `approve_phase_review` blocked when auto-review active (lines 3672-3681)
   - Returns: `"BLOCKED: This phase has an auto-review in progress"`

2. **Self-reject phases**
   - `reject_phase_review` ALWAYS blocked (lines 3735-3746)
   - Returns: `"BLOCKED: Manual rejection is not allowed"`

3. **Skip phases**
   - `advance_to_next_phase` requires APPROVED status (lines 3434-3445)
   - Returns: `"PHASE_NOT_APPROVED: Cannot advance phase"`

4. **Bypass review**
   - Auto-submit triggers when all agents complete
   - submit_phase_for_review auto-spawns reviewers

5. **Manipulate review verdicts**
   - Only reviewer agents can call submit_review_verdict
   - Verdicts aggregated automatically by system

## Guidance Field Structure

All phase-related MCP tools should return consistent guidance:

```json
{
  "success": true,
  "guidance": {
    "status": "ACTIVE|AWAITING_REVIEW|UNDER_REVIEW|etc",
    "action": "Clear directive on what to do next",
    "blocked_reason": null | ["List of blockers"],
    "escalated": false | true
  },
  "review": {
    "review_id": "review-123",
    "status": "in_progress|completed",
    "reviewers_submitted": 2,
    "reviewers_expected": 3,
    "final_verdict": null | "approved|rejected",
    "findings_summary": {
      "total": 15,
      "critical": 2,
      "high": 3,
      "blockers": 1
    }
  }
}
```

## Key Files and Line References

- **State definitions**: real_mcp_server.py:235-237
- **get_phase_status**: real_mcp_server.py:3145-3285
- **Auto-submit logic**: real_mcp_server.py:2789-2805
- **submit_phase_for_review**: real_mcp_server.py:3485-3555
- **approve_phase_review (blocked)**: real_mcp_server.py:3559-3717
- **reject_phase_review (blocked)**: real_mcp_server.py:3721-3746
- **advance_to_next_phase**: real_mcp_server.py:3392-3481
- **trigger_agentic_review**: real_mcp_server.py:4021+

## Summary

The phase state machine enforces a rigid, reviewer-driven workflow:

1. Phases start as PENDING, become ACTIVE one at a time
2. Agents work in ACTIVE phase
3. System auto-submits for review when agents complete
4. Reviewer agents independently verify work
5. System auto-transitions based on reviewer consensus
6. Orchestrator can only advance after approval
7. Manual approval/rejection completely blocked (except ESCALATED override)

This design prevents the orchestrator from gaming the system while ensuring work quality through mandatory peer review.