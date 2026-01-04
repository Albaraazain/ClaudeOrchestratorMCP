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
