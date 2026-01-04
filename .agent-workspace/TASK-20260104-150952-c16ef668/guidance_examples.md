# MCP Tool Guidance Examples

## Tool-Specific Guidance Implementations

### 1. create_real_task

#### Current (No Guidance)
```json
{
  "success": true,
  "task_id": "TASK-20260104-123456-abc",
  "phases": [...],
  "warnings": [...]
}
```

#### Updated (With Guidance)
```json
{
  "success": true,
  "task_id": "TASK-20260104-123456-abc",
  "phases": [...],
  "warnings": [...],
  "guidance": {
    "current_state": "task_created",
    "next_action": "Deploy agents for Phase 1 'Investigation' using deploy_headless_agent",
    "available_actions": [
      "deploy_headless_agent - Start phase 1 work",
      "get_real_task_status - View full task details",
      "get_phase_status - Check phase state"
    ],
    "warnings": null,
    "blocked_reason": null,
    "context": {
      "first_phase": "Investigation",
      "total_phases": 3,
      "recommended_agents": ["investigator", "analyzer", "researcher"]
    }
  }
}
```

### 2. deploy_headless_agent

#### Current (No Guidance)
```json
{
  "success": true,
  "agent_id": "investigator-123456-abc",
  "session_name": "TASK-xxx-AGENT-yyy",
  "message": "Agent deployed successfully"
}
```

#### Updated (With Guidance)
```json
{
  "success": true,
  "agent_id": "investigator-123456-abc",
  "session_name": "TASK-xxx-AGENT-yyy",
  "message": "Agent deployed successfully",
  "guidance": {
    "current_state": "agent_deployed",
    "next_action": "Monitor agent with get_agent_output or deploy more agents",
    "available_actions": [
      "get_agent_output - Monitor this agent's progress",
      "deploy_headless_agent - Deploy additional agents",
      "check_phase_progress - Check overall phase status"
    ],
    "warnings": null,
    "blocked_reason": null,
    "context": {
      "agents_in_phase": 3,
      "agents_running": 2,
      "phase_name": "Investigation"
    }
  }
}
```

### 3. get_real_task_status

#### Current (Partial Guidance)
```json
{
  "success": true,
  "task_id": "TASK-xxx",
  "status": {...},
  "agents": {...}
}
```

#### Updated (Enhanced Guidance)
```json
{
  "success": true,
  "task_id": "TASK-xxx",
  "status": {...},
  "agents": {...},
  "guidance": {
    "current_state": "phase_2_active_agents_working",
    "next_action": "Wait for 3 agents to complete, monitor with get_agent_output",
    "available_actions": [
      "get_agent_output - Check agent logs",
      "check_phase_progress - Check if ready for review",
      "deploy_headless_agent - Add more agents if needed",
      "kill_real_agent - Terminate stuck agents"
    ],
    "warnings": [
      "Agent 'analyzer-789' has been running for 45 minutes"
    ],
    "blocked_reason": null,
    "context": {
      "current_phase": "Implementation",
      "phase_index": 1,
      "total_phases": 3,
      "agents_active": 3,
      "agents_completed": 2
    }
  }
}
```

### 4. update_agent_progress

#### Current (Coordination Info Only)
```json
{
  "success": true,
  "own_update": {...},
  "coordination_info": {...}
}
```

#### Updated (With Guidance)
```json
{
  "success": true,
  "own_update": {...},
  "coordination_info": {...},
  "guidance": {
    "current_state": "agent_progress_updated",
    "next_action": "Continue with agent work or check peer findings",
    "available_actions": [
      "report_agent_finding - Share discoveries",
      "spawn_child_agent - Create sub-agent if needed",
      "get_task_findings - Review peer discoveries"
    ],
    "warnings": null,
    "blocked_reason": null,
    "context": {
      "peer_agents_active": 4,
      "peer_findings_available": 12,
      "your_progress": 50
    }
  }
}
```

### 5. advance_to_next_phase

#### Current (Error Only)
```json
{
  "success": false,
  "error": "PHASE_NOT_APPROVED",
  "hint": "Phase must be APPROVED by reviewers...",
  "current_phase": "Implementation",
  "current_status": "UNDER_REVIEW"
}
```

#### Updated (With Structured Guidance)
```json
{
  "success": false,
  "error": "PHASE_NOT_APPROVED",
  "guidance": {
    "current_state": "phase_blocked_under_review",
    "next_action": "Wait for review completion, check status with get_review_status",
    "available_actions": [
      "get_review_status - Check review progress",
      "get_agent_output - Monitor reviewer agents",
      "abort_stalled_review - Abort if reviewers crashed"
    ],
    "warnings": null,
    "blocked_reason": "Phase 'Implementation' is currently UNDER_REVIEW. Must be APPROVED before advancement.",
    "context": {
      "current_phase": "Implementation",
      "current_status": "UNDER_REVIEW",
      "required_status": "APPROVED",
      "review_id": "rev-abc123"
    }
  }
}
```

### 6. submit_phase_for_review

#### Current (No Guidance)
```json
{
  "success": true,
  "message": "Phase submitted for review",
  "phase": "Implementation",
  "status": "AWAITING_REVIEW"
}
```

#### Updated (With Guidance)
```json
{
  "success": true,
  "message": "Phase submitted for review",
  "phase": "Implementation",
  "status": "AWAITING_REVIEW",
  "guidance": {
    "current_state": "phase_awaiting_review",
    "next_action": "Call trigger_agentic_review to spawn reviewer agents",
    "available_actions": [
      "trigger_agentic_review - Deploy reviewer agents",
      "get_phase_status - Check phase details"
    ],
    "warnings": null,
    "blocked_reason": null,
    "context": {
      "phase_name": "Implementation",
      "agents_completed": 5,
      "auto_review_available": true
    }
  }
}
```

### 7. trigger_agentic_review

#### Current (Basic Guidance)
```json
{
  "success": true,
  "review_id": "rev-123",
  "reviewers_spawned": ["reviewer-1", "reviewer-2"],
  "next_action": "Monitor review with get_review_status"
}
```

#### Updated (Structured Guidance)
```json
{
  "success": true,
  "review_id": "rev-123",
  "reviewers_spawned": ["reviewer-1", "reviewer-2"],
  "guidance": {
    "current_state": "review_initiated",
    "next_action": "Wait for reviewers to complete, monitor with get_review_status",
    "available_actions": [
      "get_review_status - Check review progress",
      "get_agent_output - Monitor individual reviewers",
      "abort_stalled_review - Abort if reviewers fail"
    ],
    "warnings": null,
    "blocked_reason": null,
    "context": {
      "review_id": "rev-123",
      "num_reviewers": 2,
      "phase_under_review": "Implementation",
      "expected_duration": "5-10 minutes"
    }
  }
}
```

### 8. get_agent_output

#### Current (No Guidance)
```json
{
  "success": true,
  "output": "...",
  "metadata": {...}
}
```

#### Updated (With Interpretation Guidance)
```json
{
  "success": true,
  "output": "...",
  "metadata": {...},
  "guidance": {
    "current_state": "agent_active",
    "next_action": "Agent still working, continue monitoring or check other agents",
    "available_actions": [
      "get_agent_output - Continue monitoring",
      "check_phase_progress - Check overall phase status",
      "kill_real_agent - Terminate if stuck"
    ],
    "warnings": [
      "Agent has been on same task for 20 minutes"
    ],
    "blocked_reason": null,
    "context": {
      "agent_status": "working",
      "agent_progress": 60,
      "recent_activity": "Analyzing codebase",
      "error_count": 0
    }
  }
}
```

### 9. kill_real_agent

#### Current (No Guidance)
```json
{
  "success": true,
  "message": "Agent terminated",
  "cleanup_performed": true
}
```

#### Updated (With Cleanup Guidance)
```json
{
  "success": true,
  "message": "Agent terminated",
  "cleanup_performed": true,
  "guidance": {
    "current_state": "agent_terminated",
    "next_action": "Deploy replacement agent or check phase progress",
    "available_actions": [
      "deploy_headless_agent - Deploy replacement",
      "check_phase_progress - Check if phase can proceed",
      "get_real_task_status - View overall status"
    ],
    "warnings": [
      "Phase has only 1 active agent remaining"
    ],
    "blocked_reason": null,
    "context": {
      "terminated_agent": "investigator-123",
      "reason": "Stuck for 60 minutes",
      "agents_remaining": 1,
      "phase_name": "Investigation"
    }
  }
}
```

### 10. Error Response Examples

#### Registry Lock Error
```json
{
  "success": false,
  "error": "Registry locked by another process",
  "guidance": {
    "current_state": "registry_locked",
    "next_action": "Wait 5 seconds and retry the operation",
    "available_actions": [
      "get_real_task_status - Retry after waiting",
      "get_health_status - Check system health"
    ],
    "warnings": null,
    "blocked_reason": "Another agent is currently updating the registry",
    "context": {
      "lock_holder": "agent-xyz",
      "lock_duration": "2s",
      "retry_after": 5
    }
  }
}
```

#### Invalid Input Error
```json
{
  "success": false,
  "error": "Invalid task ID format",
  "guidance": {
    "current_state": "input_validation_error",
    "next_action": "Provide valid task ID in format TASK-YYYYMMDD-HHMMSS-xxxxx",
    "available_actions": [
      "create_real_task - Create new task",
      "list_tasks - List existing tasks (if available)"
    ],
    "warnings": null,
    "blocked_reason": "Task ID 'invalid-id' does not match expected pattern",
    "context": {
      "expected_format": "TASK-YYYYMMDD-HHMMSS-xxxxx",
      "provided": "invalid-id",
      "example": "TASK-20260104-123456-abc123"
    }
  }
}
```

## Implementation Checklist

### Tools with Guidance (Need Enhancement)
- [x] get_phase_status - Has guidance object (enhance consistency)
- [x] check_phase_progress - Has next_action (convert to object)
- [x] trigger_agentic_review - Has next_action (convert to object)
- [x] abort_stalled_review - Has basic guidance (enhance)
- [ ] get_review_status - Partial guidance (enhance)
- [ ] approve_phase_review - Blocked message (add guidance)
- [ ] reject_phase_review - Blocked message (add guidance)

### Tools WITHOUT Guidance (Need Implementation)
- [ ] create_real_task - CRITICAL
- [ ] deploy_headless_agent - CRITICAL
- [ ] get_real_task_status - CRITICAL
- [ ] update_agent_progress - CRITICAL
- [ ] report_agent_finding - HIGH
- [ ] advance_to_next_phase - HIGH (has hint, needs structure)
- [ ] submit_phase_for_review - HIGH
- [ ] get_agent_output - MEDIUM
- [ ] kill_real_agent - MEDIUM
- [ ] spawn_child_agent - MEDIUM
- [ ] submit_review_verdict - MEDIUM
- [ ] get_phase_handover - LOW
- [ ] get_health_status - LOW
- [ ] trigger_health_scan - LOW

## Pattern Summary

Every tool response should follow this structure:
```python
result = {
    "success": True/False,
    # ... tool-specific fields ...
    "guidance": {
        "current_state": "descriptive_state",
        "next_action": "Specific action to take",
        "available_actions": [
            "tool_name - Description"
        ],
        "warnings": [...] or null,
        "blocked_reason": "..." or null,
        "context": {
            # State-specific context
        }
    }
}
```

This ensures orchestrators always know:
1. What state they're in
2. What to do next
3. What options are available
4. What issues to be aware of
5. Why something is blocked (if applicable)
6. Additional context for decision-making