# Codex Orchestrator MCP — System Rules

## Phase State Machine (Mar 2026)

The MCP enforces a strict phase lifecycle. The orchestrator CANNOT bypass it.

### States

| State | Meaning | What to do |
|-------|---------|------------|
| **PENDING** | Waiting for previous phase to complete | Nothing — system auto-activates when prior phase is APPROVED |
| **ACTIVE** | Work agents should be deployed | Deploy agents with `deploy_opus_agent` / `deploy_sonnet_agent` |
| **IN_REVIEW** | Reviewer agents evaluating the work | Wait. Check progress with `get_review_status` |
| **APPROVED** | Phase passed review | System auto-activated the next phase. Deploy agents for it |
| **REVISION_NEEDED** | Review found issues requiring fixes | Deploy fix agents (auto-transitions to FIXING) |
| **FIXING** | Fix agents deployed and working | Call `mark_revision_ready` once ALL fix agents are deployed |
| **ESCALATED** | Reviewers crashed or max revision rounds exceeded | Use `approve_phase_review(force_escalated=True)` or abort and retry |
| **FAILED** | Phase explicitly abandoned (terminal) | No further action possible |

### Transition Diagram

```
PENDING → ACTIVE → IN_REVIEW → APPROVED (auto-activates next PENDING phase)
                              → REVISION_NEEDED → FIXING → IN_REVIEW (auto-resubmit)
                              → ESCALATED
                                  → APPROVED (force_escalated)
                                  → IN_REVIEW (abort + retry)
                                  → FAILED (abandon)
```

### Valid Transitions (enforced — invalid transitions are blocked)

```
PENDING           → ACTIVE
ACTIVE            → IN_REVIEW
IN_REVIEW         → APPROVED, REVISION_NEEDED, ESCALATED
REVISION_NEEDED   → FIXING
FIXING            → IN_REVIEW, ESCALATED
ESCALATED         → APPROVED, IN_REVIEW, FAILED
APPROVED          → (terminal)
FAILED            → (terminal)
```

### The Enforced Flow

```
1. create_real_task(phases=[...])          — phases are MANDATORY
      ↓
2. deploy_opus_agent / deploy_sonnet_agent — tagged with phase_index
      ↓
3. All agents complete                    — system auto-submits (ACTIVE → IN_REVIEW)
      ↓
4. System auto-spawns reviewers           — 1 Opus reviewer + 1 Opus critique agent
      ↓
5. Reviewer calls submit_review_verdict   — approved / rejected / needs_revision
      ↓
6. System finalizes verdict               — single reviewer decides
      ↓
7a. APPROVED → system auto-advances to next phase
7b. REVISION_NEEDED → orchestrator must fix:
      ↓
    i.   Deploy fix agents               — phase auto-transitions to FIXING
    ii.  Deploy more fix agents if needed
    iii. Call mark_revision_ready()       — signals "I'm done deploying fix agents"
    iv.  All fix agents complete          — system auto-resubmits for re-review
    v.   If rejected again, repeat (up to 3 rounds, then ESCALATED)
```

### The Revision Cycle in Detail

When a phase gets `REVISION_NEEDED`:

1. **Deploy fix agents** — the first `deploy_opus_agent`/`deploy_sonnet_agent` call auto-transitions the phase from `REVISION_NEEDED` to `FIXING`
2. **Deploy more fix agents** if needed — phase stays in `FIXING`
3. **Call `mark_revision_ready(task_id)`** — this tells the system "all my fix agents are deployed"
4. **Wait** — when all fix agents complete AND revision_ready is set, the system auto-resubmits for review
5. **Revision round counter** — each cycle increments `revision_round`. After `max_revision_rounds` (default 3), the phase auto-ESCALATES instead of re-reviewing

Why `mark_revision_ready` exists: without it, if you deploy 3 fix agents sequentially, the first agent completing would trigger an auto-resubmit before agents 2 and 3 are even deployed. The flag prevents premature resubmission.

### The Orchestrator CANNOT

- Self-approve — `approve_phase_review` is BLOCKED (except for ESCALATED with `force_escalated=True`)
- Skip phases — transitions are enforced
- Bypass review — `submit_phase_for_review` auto-spawns reviewers
- Manually advance — phase advancement happens automatically on APPROVED
- Resubmit without fixing — `REVISION_NEEDED` can ONLY transition to `FIXING` (by deploying agents)
- Resubmit prematurely — auto-resubmit requires `mark_revision_ready` flag

### Tool Quick Reference

| Goal | Tool | When |
|------|------|------|
| Check what to do next | `get_phase_status` | Always — this is the primary guidance tool |
| Monitor agent progress | `check_phase_progress` | While agents are working |
| Deploy Codex agents | `deploy_opus_agent` / `deploy_sonnet_agent` | Phase is ACTIVE or REVISION_NEEDED/FIXING |
| Deploy Gemini design agent | `deploy_design_agent` | UI/UX design, visual feedback, creative tasks |
| Signal fix agents done deploying | `mark_revision_ready` | Phase is FIXING, all fix agents deployed |
| Check review progress | `get_review_status` | Phase is IN_REVIEW |
| Force-approve crashed review | `approve_phase_review(force_escalated=True)` | Phase is ESCALATED only |
| Abort stuck review | `abort_stalled_review` | Review stuck, reviewers dead |
| Get context from prior phases | `get_accumulated_task_context` | Agents need prior phase context |
| Get phase handover | `get_phase_handover` | Review what previous phase produced |

## Gemini Design Agent

`deploy_design_agent` uses Google's Gemini CLI instead of Codex. Use it for:
- UI/UX design exploration and recommendations
- Visual layout and styling decisions
- Design system analysis and accessibility audits
- Creative brainstorming and ideation
- Image analysis and visual feedback

The Gemini agent participates in the same phase/review lifecycle as Codex agents.
It runs in tmux, is tracked in SQLite, and the completion notifier handles its exit.

Available models: `gemini-3.1-pro-preview` (default — best for design), `gemini-3-flash-preview`, `gemini-2.5-pro`, `gemini-2.5-flash`

Key differences from Codex agents:
- Uses `-y` (yolo mode) instead of `--dangerously-skip-permissions`
- Does NOT have native MCP access to the orchestrator — reports completion via file
- Model stored as `gemini:<model>` in SQLite to distinguish from Codex models
- Requires `fnm env` in tmux (auto-handled)

### Legacy State Names

Old state names are automatically normalized. If you see these in old data, they map to:

| Old Name | New Name |
|----------|----------|
| AWAITING_REVIEW | IN_REVIEW |
| UNDER_REVIEW | IN_REVIEW |
| REJECTED | REVISION_NEEDED |
| REVISING | REVISION_NEEDED |

## Storage

- **SQLite** is the source of truth for all state (agents, tasks, phases, reviews, findings)
- JSONL files are append-only audit logs
- JSON registry files are legacy caches — may drift from SQLite

## Project Context Feature

When creating tasks, pass `project_context` to provide reviewers/testers with critical project info:

```python
create_real_task(
    description="...",
    phases=[...],
    project_context={
        "dev_server_port": 3000,
        "start_command": "npm run dev",
        "test_url": "http://localhost:3000",
        "framework": "Next.js",
        "test_credentials": {"email": "test@example.com", "password": "test123"}
    }
)
```

This is automatically shown to reviewer agents and Final Testing phase agents.

Always include `deliverables` and `success_criteria` per phase so reviewers know exactly what to verify.

## Mandatory Final Testing Phase

`create_real_task()` auto-appends a "Final Testing" phase if the last phase name doesn't contain "test", "testing", "verification", "qa", or "quality".

To skip auto-append, name your last phase with a testing keyword:
```python
phases = [
    {"name": "Investigation", ...},
    {"name": "Implementation", ...},
    {"name": "Testing & QA", ...}  # Won't auto-append another
]
```

## Handover System

Handovers auto-generate when a phase is approved via review. Access via:
```
get_phase_handover(task_id="...", phase_index=0)
```

## Review System

- 1 Opus REVIEWER agent (submits verdict: approved/rejected/needs_revision)
- 1 Opus CRITIQUE agent (senior dev perspective, observations only, no verdict impact)
- Both `rejected` and `needs_revision` verdicts result in `REVISION_NEEDED` phase status
- Health daemon auto-retries crashed reviewers (up to 2 retries), then ESCALATES
- Retry counts are persisted in SQLite (survives server restarts)
