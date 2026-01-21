# Phase Handover: Investigation

**Phase ID:** phase-0
**Created:** 2026-01-14T18:11:42.239433

## Summary

Total findings: 32
By type: issue=26, recommendation=4, insight=2

Critical/High priority items:
  [CRITICAL] REVIEW FLOW AUDIT SUMMARY - 5 bugs found: (1) CRITICAL: needs_revision verdict ignored in aggregation - always approved (state_db.py:2382-2390); (2) HIGH: Duplicate verdicts allowed - no UNIQUE constr
  [HIGH] ARCHITECTURE: Mixed error handling strategy causes inconsistency. Some functions raise exceptions (good), others return {"success": False, "error": str} dicts (acceptable for MCP tools), others return
  [CRITICAL] RACE CONDITION FIX SUMMARY: (1) TOCTOU in deploy - merge check_can_spawn_agent and deploy_agent_atomic into single transaction with INSERT...SELECT WHERE; (2) TOCTOU in phase review - merge get_phase 
  [HIGH] SECURITY: No validation of reviewer authorization (real_mcp_server.py:5253-5268, state_db.py:2305-2320). submit_review_verdict and record_review_verdict don't verify: (1) review_id exists in reviews t
  [CRITICAL] MIGRATION PRIORITY SUMMARY: Found 14 AGENT_REGISTRY.json references. CRITICAL migrations needed: (1) Line 1941 kill_real_agent, (2) Line 4667 approve_phase_review. HIGH priority: Lines 1518, 2370, 279

## Key Findings

- **[CRITICAL] recommendation:** REVIEW FLOW AUDIT SUMMARY - 5 bugs found: (1) CRITICAL: needs_revision verdict ignored in aggregation - always approved (state_db.py:2382-2390); (2) HIGH: Duplicate verdicts allowed - no UNIQUE constraint (state_db.py:308-318); (3) HIGH: No reviewer authorization check (real_mcp_server.py:5253-5268); (4) MEDIUM: abort_stalled_review uses stale phase data (real_mcp_server.py:5593-5615); (5) MEDIUM: finalize_review never uses REJECTED status, only REVISING (state_db.py:2449)
  ```json
  {
  "priority_fixes": [
    "1. Fix check_review_complete to count needs_revision as rejection",
    "2. Add UNIQUE(review_id, reviewer_agent_id) to review_verdicts table",
    "3. Add reviewer authorization check before recording verdict",
    "4. Re-fetch phase data after abort_review call",
    "5. Decide REJECTED vs REVISING semantics and be consistent"
  ]
}
  ```
- **[HIGH] recommendation:** ARCHITECTURE: Mixed error handling strategy causes inconsistency. Some functions raise exceptions (good), others return {"success": False, "error": str} dicts (acceptable for MCP tools), others return None (bad). No consistent Result type or error hierarchy. Recommendation: (1) Define Result[T, E] type for fallible operations, (2) Replace bare 'except:' with 'except Exception:', (3) Always log exception details before swallowing, (4) Document which functions raise vs return errors
  ```json
  {
  "patterns_found": {
    "raising": "Migration functions, some SQLite ops",
    "returning_dict": "MCP tool functions, some utility functions",
    "returning_none": "File readers, helper functions"
  },
  "consistency_score": "3/10 - very inconsistent",
  "recommendation_priority": "HIGH - establish consistent error handling conventions before more code is written",
  "suggested_approach": "Use Result type pattern from Rust/TypeScript for fallible operations, reserve exceptions for truly exceptional conditions"
}
  ```
- **[CRITICAL] recommendation:** RACE CONDITION FIX SUMMARY: (1) TOCTOU in deploy - merge check_can_spawn_agent and deploy_agent_atomic into single transaction with INSERT...SELECT WHERE; (2) TOCTOU in phase review - merge get_phase + update_phase_status into atomic claim like claim_phase_for_review; (3) NESTED LOCKS in lifecycle.py - refactor to single lock or migrate to SQLite; (4) GLOBAL REGISTRY - migrate remaining LockedRegistryFile usages in health_daemon.py to SQLite; (5) REVIEW FINALIZATION - add claim_review_finalization() to prevent double finalize.
  ```json
  {
  "total_issues": 7,
  "critical": 1,
  "high": 4,
  "medium": 2,
  "fix_pattern": "Atomic check-and-modify operations using SQLite transactions or fcntl-based claims"
}
  ```
- **[HIGH] issue:** SECURITY: No validation of reviewer authorization (real_mcp_server.py:5253-5268, state_db.py:2305-2320). submit_review_verdict and record_review_verdict don't verify: (1) review_id exists in reviews table, (2) reviewer_agent_id is in that review's reviewer_agent_ids. Any agent can submit verdicts to any review.
  ```json
  {
  "file1": "real_mcp_server.py",
  "function1": "submit_review_verdict",
  "file2": "orchestrator/state_db.py",
  "function2": "record_review_verdict",
  "impact": "Unauthorized agents can manipulate review outcomes",
  "fix": "Add validation: SELECT review_id FROM reviews WHERE review_id=? AND reviewer_agent_ids LIKE ?"
}
  ```
- **[CRITICAL] recommendation:** MIGRATION PRIORITY SUMMARY: Found 14 AGENT_REGISTRY.json references. CRITICAL migrations needed: (1) Line 1941 kill_real_agent, (2) Line 4667 approve_phase_review. HIGH priority: Lines 1518, 2370, 2798, 5675, 5743. MEDIUM: Lines 2915. LOW/Intentional: Lines 766, 2275, 4047, 4121, 4399. All SQLite equivalents exist in state_db.py.
  ```json
  {
  "total_references": 14,
  "critical": 2,
  "high": 5,
  "medium": 1,
  "low_intentional": 5,
  "already_migrated": 1,
  "migration_blockers": "None - all SQLite functions exist",
  "estimated_effort": "2-3 hours for critical+high migrations"
}
  ```
- **[HIGH] issue:** BUG: Duplicate verdicts possible - no unique constraint (state_db.py:308-318). review_verdicts table has no UNIQUE(review_id, reviewer_agent_id) constraint. Same reviewer can submit multiple verdicts, inflating verdict counts. check_review_complete() line 2379 just counts all verdicts, so 1 reviewer submitting 2x = looks like 2 reviewers.
  ```json
  {
  "file": "orchestrator/state_db.py",
  "function": "CREATE TABLE review_verdicts",
  "lines": "308-318",
  "fix": "Add UNIQUE(review_id, reviewer_agent_id) constraint to table schema"
}
  ```
- **[HIGH] issue:** Line 5743-5751: FULL READ in get_health_status. Reads entire registry to get agents list for health monitoring. Should migrate to get_agents_for_task (state_db.py:2014) which queries SQLite agents table directly.
  ```json
  {
  "line": 5743,
  "operation": "READ",
  "status": "needs-migration",
  "sqlite_equivalent": "get_agents_for_task (state_db.py:2014)",
  "priority": "HIGH - health monitoring reads entire registry frequently"
}
  ```
- **[HIGH] issue:** Line 5675-5689: FULL READ in get_phase_handover. Reads entire registry to access phases array and get phase_id. Should migrate to get_phase (state_db.py:2974) which retrieves phase data directly from SQLite.
  ```json
  {
  "line": 5675,
  "operation": "READ",
  "status": "needs-migration",
  "sqlite_equivalent": "get_phase (state_db.py:2974)",
  "priority": "HIGH - handover is critical for phase transitions"
}
  ```
- **[CRITICAL] issue:** Line 4667-4677: FULL READ+WRITE with LockedRegistryFile in approve_phase_review. This is a critical phase transition operation using JSON file locking. MUST migrate to SQLite update_phase_status (state_db.py:618) for atomic phase approval.
  ```json
  {
  "line": 4667,
  "operation": "READ+WRITE",
  "status": "needs-migration",
  "sqlite_equivalent": "update_phase_status (state_db.py:618)",
  "priority": "CRITICAL - phase transitions must be atomic in SQLite"
}
  ```
- **[HIGH] issue:** Line 2798-2809: FULL READ in get_task_findings. Reads entire registry then iterates agents to collect findings. Should migrate to get_agent_findings (state_db.py:1344) which queries SQLite directly with filters.
  ```json
  {
  "line": 2798,
  "operation": "READ",
  "status": "needs-migration",
  "sqlite_equivalent": "get_agent_findings (state_db.py:1344)",
  "priority": "HIGH - inefficient full registry read, SQLite has filtered query"
}
  ```

## Blockers

- [HIGH] SECURITY: No validation of reviewer authorization (real_mcp_server.py:5253-5268, state_db.py:2305-2320). submit_review_verdict and record_review_verdict don't verify: (1) review_id exists in reviews table, (2) reviewer_agent_id is in that review's reviewer_agent_ids. Any agent can submit verdicts to any review. (from review-flow-auditor-115404-8d0c0d)
- [HIGH] BUG: Duplicate verdicts possible - no unique constraint (state_db.py:308-318). review_verdicts table has no UNIQUE(review_id, reviewer_agent_id) constraint. Same reviewer can submit multiple verdicts, inflating verdict counts. check_review_complete() line 2379 just counts all verdicts, so 1 reviewer submitting 2x = looks like 2 reviewers. (from review-flow-auditor-115404-8d0c0d)
- [HIGH] Line 5743-5751: FULL READ in get_health_status. Reads entire registry to get agents list for health monitoring. Should migrate to get_agents_for_task (state_db.py:2014) which queries SQLite agents table directly. (from sqlite-migration-che-115406-83d900)
- [HIGH] Line 5675-5689: FULL READ in get_phase_handover. Reads entire registry to access phases array and get phase_id. Should migrate to get_phase (state_db.py:2974) which retrieves phase data directly from SQLite. (from sqlite-migration-che-115406-83d900)
- [CRITICAL] Line 4667-4677: FULL READ+WRITE with LockedRegistryFile in approve_phase_review. This is a critical phase transition operation using JSON file locking. MUST migrate to SQLite update_phase_status (state_db.py:618) for atomic phase approval. (from sqlite-migration-che-115406-83d900)
- [HIGH] Line 2798-2809: FULL READ in get_task_findings. Reads entire registry then iterates agents to collect findings. Should migrate to get_agent_findings (state_db.py:1344) which queries SQLite directly with filters. (from sqlite-migration-che-115406-83d900)
- [HIGH] Multiple paths calling _auto_spawn_phase_reviewers can race (real_mcp_server.py:3532-3542 + 3587-3594): Both the main path (line 3587) and the retry worker thread (line 3532) can call _auto_spawn_phase_reviewers. While claim_phase_for_review() prevents duplicate spawns WITHIN this function, the retry worker checks _maybe_auto_submit_phase_for_review_sqlite() first (which has its own race condition reported earlier). Multiple agents completing + retry workers = multiple code paths trying to transition/spawn. (from race-condition-hunte-115400-cfc373)
- [HIGH] Line 2370-2379: FULL READ with LockedRegistryFile in get_agent_output. Reads registry to find agent by ID. Should migrate to SQLite get_agent_by_id (state_db.py:2038) which is atomic and doesn't require file locking. (from sqlite-migration-che-115406-83d900)
- [HIGH] TOCTOU in _maybe_auto_submit_phase_for_review_sqlite (real_mcp_server.py:3463-3488): Reads phase...

## Recommendations for Next Phase

1. REVIEW FLOW AUDIT SUMMARY - 5 bugs found: (1) CRITICAL: needs_revision verdict ignored in aggregation - always approved (state_db.py:2382-2390); (2) HIGH: Duplicate verdicts allowed - no UNIQUE constraint (state_db.py:308-318); (3) HIGH: No reviewer authorization check (real_mcp_server.py:5253-5268); (4) MEDIUM: abort_stalled_review uses stale phase data (real_mcp_server.py:5593-5615); (5) MEDIUM: finalize_review never uses REJECTED status, only REVISING (state_db.py:2449)
2. ARCHITECTURE: Mixed error handling strategy causes inconsistency. Some functions raise exceptions (good), others return {"success": False, "error": str} dicts (acceptable for MCP tools), others return None (bad). No consistent Result type or error hierarchy. Recommendation: (1) Define Result[T, E] type for fallible operations, (2) Replace bare 'except:' with 'except Exception:', (3) Always log exception details before swallowing, (4) Document which functions raise vs return errors
3. RACE CONDITION FIX SUMMARY: (1) TOCTOU in deploy - merge check_can_spawn_agent and deploy_agent_atomic into single transaction with INSERT...SELECT WHERE; (2) TOCTOU in phase review - merge get_phase + update_phase_status into atomic claim like claim_phase_for_review; (3) NESTED LOCKS in lifecycle.py - refactor to single lock or migrate to SQLite; (4) GLOBAL REGISTRY - migrate remaining LockedRegistryFile usages in health_daemon.py to SQLite; (5) REVIEW FINALIZATION - add claim_review_finalization() to prevent double finalize.
4. MIGRATION PRIORITY SUMMARY: Found 14 AGENT_REGISTRY.json references. CRITICAL migrations needed: (1) Line 1941 kill_real_agent, (2) Line 4667 approve_phase_review. HIGH priority: Lines 1518, 2370, 2798, 5675, 5743. MEDIUM: Lines 2915. LOW/Intentional: Lines 766, 2275, 4047, 4121, 4399. All SQLite equivalents exist in state_db.py.
5. Review 2 insights from Investigation phase before proceeding
6. Address 26 potentially unresolved issues from Investigation
7. PRIORITY: Verify 7 critical items have been fully addressed
8. Ensure implementation addresses all issues identified during investigation

## Artifacts Created

- `real_mcp_server.py`: From issue
- `orchestrator/state_db.py`: From issue
- `real_mcp_server.py`: From issue
- `real_mcp_server.py`: From issue
- `real_mcp_server.py`: From issue
- `real_mcp_server.py`: From issue
- `orchestrator/state_db.py`: From issue
- `real_mcp_server.py + state_db.py`: From issue
- `orchestrator/health_daemon.py`: From issue
- `orchestrator/lifecycle.py`: From issue

## Phase Metrics

| Metric | Value |
|--------|-------|
| Agents Deployed | 0 |
| Completed | 0 |
| Failed | 0 |
| Blocked | 0 |
| Duration Seconds | 0 |
| Findings Count | 32 |

---

<!-- HANDOVER_JSON_START
{
  "phase_id": "phase-0",
  "phase_name": "Investigation",
  "created_at": "2026-01-14T18:11:42.239433",
  "summary": "Total findings: 32\nBy type: issue=26, recommendation=4, insight=2\n\nCritical/High priority items:\n  [CRITICAL] REVIEW FLOW AUDIT SUMMARY - 5 bugs found: (1) CRITICAL: needs_revision verdict ignored in aggregation - always approved (state_db.py:2382-2390); (2) HIGH: Duplicate verdicts allowed - no UNIQUE constr\n  [HIGH] ARCHITECTURE: Mixed error handling strategy causes inconsistency. Some functions raise exceptions (good), others return {\"success\": False, \"error\": str} dicts (acceptable for MCP tools), others return\n  [CRITICAL] RACE CONDITION FIX SUMMARY: (1) TOCTOU in deploy - merge check_can_spawn_agent and deploy_agent_atomic into single transaction with INSERT...SELECT WHERE; (2) TOCTOU in phase review - merge get_phase \n  [HIGH] SECURITY: No validation of reviewer authorization (real_mcp_server.py:5253-5268, state_db.py:2305-2320). submit_review_verdict and record_review_verdict don't verify: (1) review_id exists in reviews t\n  [CRITICAL] MIGRATION PRIORITY SUMMARY: Found 14 AGENT_REGISTRY.json references. CRITICAL migrations needed: (1) Line 1941 kill_real_agent, (2) Line 4667 approve_phase_review. HIGH priority: Lines 1518, 2370, 279",
  "key_findings": [
    {
      "type": "recommendation",
      "severity": "critical",
      "message": "REVIEW FLOW AUDIT SUMMARY - 5 bugs found: (1) CRITICAL: needs_revision verdict ignored in aggregation - always approved (state_db.py:2382-2390); (2) HIGH: Duplicate verdicts allowed - no UNIQUE constraint (state_db.py:308-318); (3) HIGH: No reviewer authorization check (real_mcp_server.py:5253-5268); (4) MEDIUM: abort_stalled_review uses stale phase data (real_mcp_server.py:5593-5615); (5) MEDIUM: finalize_review never uses REJECTED status, only REVISING (state_db.py:2449)",
      "data": {
        "priority_fixes": [
          "1. Fix check_review_complete to count needs_revision as rejection",
          "2. Add UNIQUE(review_id, reviewer_agent_id) to review_verdicts table",
          "3. Add reviewer authorization check before recording verdict",
          "4. Re-fetch phase data after abort_review call",
          "5. Decide REJECTED vs REVISING semantics and be consistent"
        ]
      }
    },
    {
      "type": "recommendation",
      "severity": "high",
      "message": "ARCHITECTURE: Mixed error handling strategy causes inconsistency. Some functions raise exceptions (good), others return {\"success\": False, \"error\": str} dicts (acceptable for MCP tools), others return None (bad). No consistent Result type or error hierarchy. Recommendation: (1) Define Result[T, E] type for fallible operations, (2) Replace bare 'except:' with 'except Exception:', (3) Always log exception details before swallowing, (4) Document which functions raise vs return errors",
      "data": {
        "patterns_found": {
          "raising": "Migration functions, some SQLite ops",
          "returning_dict": "MCP tool functions, some utility functions",
          "returning_none": "File readers, helper functions"
        },
        "consistency_score": "3/10 - very inconsistent",
        "recommendation_priority": "HIGH - establish consistent error handling conventions before more code is written",
        "suggested_approach": "Use Result type pattern from Rust/TypeScript for fallible operations, reserve exceptions for truly exceptional conditions"
      }
    },
    {
      "type": "recommendation",
      "severity": "critical",
      "message": "RACE CONDITION FIX SUMMARY: (1) TOCTOU in deploy - merge check_can_spawn_agent and deploy_agent_atomic into single transaction with INSERT...SELECT WHERE; (2) TOCTOU in phase review - merge get_phase + update_phase_status into atomic claim like claim_phase_for_review; (3) NESTED LOCKS in lifecycle.py - refactor to single lock or migrate to SQLite; (4) GLOBAL REGISTRY - migrate remaining LockedRegistryFile usages in health_daemon.py to SQLite; (5) REVIEW FINALIZATION - add claim_review_finalization() to prevent double finalize.",
      "data": {
        "total_issues": 7,
        "critical": 1,
        "high": 4,
        "medium": 2,
        "fix_pattern": "Atomic check-and-modify operations using SQLite transactions or fcntl-based claims"
      }
    },
    {
      "type": "issue",
      "severity": "high",
      "message": "SECURITY: No validation of reviewer authorization (real_mcp_server.py:5253-5268, state_db.py:2305-2320). submit_review_verdict and record_review_verdict don't verify: (1) review_id exists in reviews table, (2) reviewer_agent_id is in that review's reviewer_agent_ids. Any agent can submit verdicts to any review.",
      "data": {
        "file1": "real_mcp_server.py",
        "function1": "submit_review_verdict",
        "file2": "orchestrator/state_db.py",
        "function2": "record_review_verdict",
        "impact": "Unauthorized agents can manipulate review outcomes",
        "fix": "Add validation: SELECT review_id FROM reviews WHERE review_id=? AND reviewer_agent_ids LIKE ?"
      }
    },
    {
      "type": "recommendation",
      "severity": "critical",
      "message": "MIGRATION PRIORITY SUMMARY: Found 14 AGENT_REGISTRY.json references. CRITICAL migrations needed: (1) Line 1941 kill_real_agent, (2) Line 4667 approve_phase_review. HIGH priority: Lines 1518, 2370, 2798, 5675, 5743. MEDIUM: Lines 2915. LOW/Intentional: Lines 766, 2275, 4047, 4121, 4399. All SQLite equivalents exist in state_db.py.",
      "data": {
        "total_references": 14,
        "critical": 2,
        "high": 5,
        "medium": 1,
        "low_intentional": 5,
        "already_migrated": 1,
        "migration_blockers": "None - all SQLite functions exist",
        "estimated_effort": "2-3 hours for critical+high migrations"
      }
    },
    {
      "type": "issue",
      "severity": "high",
      "message": "BUG: Duplicate verdicts possible - no unique constraint (state_db.py:308-318). review_verdicts table has no UNIQUE(review_id, reviewer_agent_id) constraint. Same reviewer can submit multiple verdicts, inflating verdict counts. check_review_complete() line 2379 just counts all verdicts, so 1 reviewer submitting 2x = looks like 2 reviewers.",
      "data": {
        "file": "orchestrator/state_db.py",
        "function": "CREATE TABLE review_verdicts",
        "lines": "308-318",
        "fix": "Add UNIQUE(review_id, reviewer_agent_id) constraint to table schema"
      }
    },
    {
      "type": "issue",
      "severity": "high",
      "message": "Line 5743-5751: FULL READ in get_health_status. Reads entire registry to get agents list for health monitoring. Should migrate to get_agents_for_task (state_db.py:2014) which queries SQLite agents table directly.",
      "data": {
        "line": 5743,
        "operation": "READ",
        "status": "needs-migration",
        "sqlite_equivalent": "get_agents_for_task (state_db.py:2014)",
        "priority": "HIGH - health monitoring reads entire registry frequently"
      }
    },
    {
      "type": "issue",
      "severity": "high",
      "message": "Line 5675-5689: FULL READ in get_phase_handover. Reads entire registry to access phases array and get phase_id. Should migrate to get_phase (state_db.py:2974) which retrieves phase data directly from SQLite.",
      "data": {
        "line": 5675,
        "operation": "READ",
        "status": "needs-migration",
        "sqlite_equivalent": "get_phase (state_db.py:2974)",
        "priority": "HIGH - handover is critical for phase transitions"
      }
    },
    {
      "type": "issue",
      "severity": "critical",
      "message": "Line 4667-4677: FULL READ+WRITE with LockedRegistryFile in approve_phase_review. This is a critical phase transition operation using JSON file locking. MUST migrate to SQLite update_phase_status (state_db.py:618) for atomic phase approval.",
      "data": {
        "line": 4667,
        "operation": "READ+WRITE",
        "status": "needs-migration",
        "sqlite_equivalent": "update_phase_status (state_db.py:618)",
        "priority": "CRITICAL - phase transitions must be atomic in SQLite"
      }
    },
    {
      "type": "issue",
      "severity": "high",
      "message": "Line 2798-2809: FULL READ in get_task_findings. Reads entire registry then iterates agents to collect findings. Should migrate to get_agent_findings (state_db.py:1344) which queries SQLite directly with filters.",
      "data": {
        "line": 2798,
        "operation": "READ",
        "status": "needs-migration",
        "sqlite_equivalent": "get_agent_findings (state_db.py:1344)",
        "priority": "HIGH - inefficient full registry read, SQLite has filtered query"
      }
    }
  ],
  "blockers": [
    "[HIGH] SECURITY: No validation of reviewer authorization (real_mcp_server.py:5253-5268, state_db.py:2305-2320). submit_review_verdict and record_review_verdict don't verify: (1) review_id exists in reviews table, (2) reviewer_agent_id is in that review's reviewer_agent_ids. Any agent can submit verdicts to any review. (from review-flow-auditor-115404-8d0c0d)",
    "[HIGH] BUG: Duplicate verdicts possible - no unique constraint (state_db.py:308-318). review_verdicts table has no UNIQUE(review_id, reviewer_agent_id) constraint. Same reviewer can submit multiple verdicts, inflating verdict counts. check_review_complete() line 2379 just counts all verdicts, so 1 reviewer submitting 2x = looks like 2 reviewers. (from review-flow-auditor-115404-8d0c0d)",
    "[HIGH] Line 5743-5751: FULL READ in get_health_status. Reads entire registry to get agents list for health monitoring. Should migrate to get_agents_for_task (state_db.py:2014) which queries SQLite agents table directly. (from sqlite-migration-che-115406-83d900)",
    "[HIGH] Line 5675-5689: FULL READ in get_phase_handover. Reads entire registry to access phases array and get phase_id. Should migrate to get_phase (state_db.py:2974) which retrieves phase data directly from SQLite. (from sqlite-migration-che-115406-83d900)",
    "[CRITICAL] Line 4667-4677: FULL READ+WRITE with LockedRegistryFile in approve_phase_review. This is a critical phase transition operation using JSON file locking. MUST migrate to SQLite update_phase_status (state_db.py:618) for atomic phase approval. (from sqlite-migration-che-115406-83d900)",
    "[HIGH] Line 2798-2809: FULL READ in get_task_findings. Reads entire registry then iterates agents to collect findings. Should migrate to get_agent_findings (state_db.py:1344) which queries SQLite directly with filters. (from sqlite-migration-che-115406-83d900)",
    "[HIGH] Multiple paths calling _auto_spawn_phase_reviewers can race (real_mcp_server.py:3532-3542 + 3587-3594): Both the main path (line 3587) and the retry worker thread (line 3532) can call _auto_spawn_phase_reviewers. While claim_phase_for_review() prevents duplicate spawns WITHIN this function, the retry worker checks _maybe_auto_submit_phase_for_review_sqlite() first (which has its own race condition reported earlier). Multiple agents completing + retry workers = multiple code paths trying to transition/spawn. (from race-condition-hunte-115400-cfc373)",
    "[HIGH] Line 2370-2379: FULL READ with LockedRegistryFile in get_agent_output. Reads registry to find agent by ID. Should migrate to SQLite get_agent_by_id (state_db.py:2038) which is atomic and doesn't require file locking. (from sqlite-migration-che-115406-83d900)",
    "[HIGH] TOCTOU in _maybe_auto_submit_phase_for_review_sqlite (real_mcp_server.py:3463-3488): Reads phase status at line 3474-3480 (get_phase), then updates status at 3484-3488 (update_phase_status). Race window exists where two concurrent agents completing could both read 'ACTIVE' status, both pass the check, and both try to update to 'AWAITING_REVIEW'. This can cause duplicate reviewer spawn attempts. (from race-condition-hunte-115400-cfc373)",
    "[CRITICAL] Line 1941-1949: FULL READ in kill_real_agent. Reads entire AGENT_REGISTRY.json to find agent by ID. This MUST be migrated to SQLite get_agent_by_id which already exists in state_db.py line 2038. (from sqlite-migration-che-115406-83d900)",
    "[CRITICAL] BUG: 'needs_revision' verdict ignored in aggregation (state_db.py:2382-2390). check_review_complete() only counts 'approved' and 'rejected' verdicts. If both reviewers submit 'needs_revision', final verdict becomes 'approved' (0 approve >= 0 reject = ties go to approved). This bypasses the entire revision flow. (from review-flow-auditor-115404-8d0c0d)",
    "[HIGH] Line 1518-1525: FALLBACK READ in deploy_claude_tmux_agent. When SQLite load_task_snapshot fails, falls back to reading AGENT_REGISTRY.json. This should be migrated - if SQLite is empty, the task doesn't exist, not a valid fallback scenario. (from sqlite-migration-che-115406-83d900)",
    "[CRITICAL] TOCTOU Race Condition in deploy_claude_tmux_agent (real_mcp_server.py:1027-1033 vs 1155+): check_can_spawn_agent() checks constraints BUT returns BEFORE agent is inserted. Between check (line 1027-1033) and INSERT (via deploy_agent_atomic called later around line 1155+), another concurrent request can pass the same check. Both will think they can spawn, causing duplicate agents that violate max_concurrent/max_agents limits. (from race-condition-hunte-115400-cfc373)",
    "[HIGH] 30+ bare 'except:' blocks that catch ALL exceptions including KeyboardInterrupt and SystemExit. These prevent proper error propagation and debugging. Critical locations: orchestrator/status.py:229,236 (silent pass), orchestrator/lifecycle.py:479,595,520,628,653 (returns generic errors), real_mcp_server.py:2920,2834,2853,2940 (continue on failure), orchestrator/state_db.py:2732,2922,3005 (fallback to empty data) (from error-handler-audito-115409-44d39b)",
    "[HIGH] lifecycle.py:990-1118 - NESTED LockedRegistryFile pattern still in use. Main lock at line 990, then NESTED locks at lines 1085 and 1100 for cleanup result updates. If cleanup fails, inner lock acquisition at 1100 can deadlock if same process already holds outer lock (reentrant lock scenario depends on fcntl implementation). (from race-condition-hunte-115400-cfc373)"
  ],
  "recommendations": [
    "REVIEW FLOW AUDIT SUMMARY - 5 bugs found: (1) CRITICAL: needs_revision verdict ignored in aggregation - always approved (state_db.py:2382-2390); (2) HIGH: Duplicate verdicts allowed - no UNIQUE constraint (state_db.py:308-318); (3) HIGH: No reviewer authorization check (real_mcp_server.py:5253-5268); (4) MEDIUM: abort_stalled_review uses stale phase data (real_mcp_server.py:5593-5615); (5) MEDIUM: finalize_review never uses REJECTED status, only REVISING (state_db.py:2449)",
    "ARCHITECTURE: Mixed error handling strategy causes inconsistency. Some functions raise exceptions (good), others return {\"success\": False, \"error\": str} dicts (acceptable for MCP tools), others return None (bad). No consistent Result type or error hierarchy. Recommendation: (1) Define Result[T, E] type for fallible operations, (2) Replace bare 'except:' with 'except Exception:', (3) Always log exception details before swallowing, (4) Document which functions raise vs return errors",
    "RACE CONDITION FIX SUMMARY: (1) TOCTOU in deploy - merge check_can_spawn_agent and deploy_agent_atomic into single transaction with INSERT...SELECT WHERE; (2) TOCTOU in phase review - merge get_phase + update_phase_status into atomic claim like claim_phase_for_review; (3) NESTED LOCKS in lifecycle.py - refactor to single lock or migrate to SQLite; (4) GLOBAL REGISTRY - migrate remaining LockedRegistryFile usages in health_daemon.py to SQLite; (5) REVIEW FINALIZATION - add claim_review_finalization() to prevent double finalize.",
    "MIGRATION PRIORITY SUMMARY: Found 14 AGENT_REGISTRY.json references. CRITICAL migrations needed: (1) Line 1941 kill_real_agent, (2) Line 4667 approve_phase_review. HIGH priority: Lines 1518, 2370, 2798, 5675, 5743. MEDIUM: Lines 2915. LOW/Intentional: Lines 766, 2275, 4047, 4121, 4399. All SQLite equivalents exist in state_db.py.",
    "Review 2 insights from Investigation phase before proceeding",
    "Address 26 potentially unresolved issues from Investigation",
    "PRIORITY: Verify 7 critical items have been fully addressed",
    "Ensure implementation addresses all issues identified during investigation"
  ],
  "artifacts": [
    {
      "path": "real_mcp_server.py",
      "description": "From issue"
    },
    {
      "path": "orchestrator/state_db.py",
      "description": "From issue"
    },
    {
      "path": "real_mcp_server.py",
      "description": "From issue"
    },
    {
      "path": "real_mcp_server.py",
      "description": "From issue"
    },
    {
      "path": "real_mcp_server.py",
      "description": "From issue"
    },
    {
      "path": "real_mcp_server.py",
      "description": "From issue"
    },
    {
      "path": "orchestrator/state_db.py",
      "description": "From issue"
    },
    {
      "path": "real_mcp_server.py + state_db.py",
      "description": "From issue"
    },
    {
      "path": "orchestrator/health_daemon.py",
      "description": "From issue"
    },
    {
      "path": "orchestrator/lifecycle.py",
      "description": "From issue"
    }
  ],
  "metrics": {
    "agents_deployed": 0,
    "completed": 0,
    "failed": 0,
    "blocked": 0,
    "duration_seconds": 0,
    "findings_count": 32
  }
}
HANDOVER_JSON_END -->