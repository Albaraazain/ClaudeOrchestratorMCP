# Claude Code Orchestrator (MCP)

An MCP server that orchestrates **headless Claude agents** — and an optional Gemini design agent — through a strict, review-gated phase lifecycle. Use it to break a large task into phases, deploy multiple agents per phase, and have a separate reviewer agent gate progression to the next phase.

> **Status:** beta. The state machine is enforced and tested; expect rough edges in the dashboard and CLI tooling.

---

## What it actually does

You give the orchestrator a task with a list of phases. For each phase it:

1. Spins up worker agents (Opus / Sonnet / Gemini) in detached `tmux` sessions.
2. Tracks every agent's progress, findings, and output in SQLite.
3. When all workers in a phase finish, auto-spawns a **reviewer** + **critique** agent.
4. The reviewer's verdict (`approved` / `needs_revision` / `rejected`) gates the next phase.
5. On rejection, you deploy fix agents and the cycle repeats — up to a configurable number of revision rounds before escalating.

The orchestrator **cannot** self-approve, skip phases, or bypass review. The state machine is enforced server-side.

### Phase state machine

```
PENDING → ACTIVE → IN_REVIEW → APPROVED ─▶ (next phase activates)
                            ├─ REVISION_NEEDED → FIXING → IN_REVIEW
                            └─ ESCALATED ─▶ APPROVED (forced) | IN_REVIEW (retry) | FAILED
```

Full transition rules and tool semantics live in [`CLAUDE.md`](./CLAUDE.md) and [`AGENTS.md`](./AGENTS.md).

---

## Requirements

- macOS or Linux
- Python ≥ 3.10
- `tmux` (workers run inside tmux sessions)
- The `claude` CLI on `$PATH`, authenticated (`claude auth login`) — workers shell out to it
- Optional: `gemini` CLI for `deploy_design_agent`
- An MCP-compatible client: Claude Code, Claude Desktop, Cursor, etc.

---

## Install

```bash
git clone https://github.com/Albaraazain/ClaudeOrchestratorMCP.git
cd ClaudeOrchestratorMCP

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Smoke-check the server boots:

```bash
python3 real_mcp_server.py
# Ctrl+C — it's a stdio MCP server, this is just a sanity check
```

---

## Wire it into your MCP client

Copy `.mcp.json.example` to wherever your client expects its MCP config and replace the absolute paths.

**Claude Code** (`~/.claude.json` or project `.mcp.json`):

```json
{
  "mcpServers": {
    "claude-orchestrator": {
      "command": "/ABSOLUTE/PATH/TO/ClaudeOrchestratorMCP/venv/bin/python3",
      "args": ["real_mcp_server.py"],
      "cwd": "/ABSOLUTE/PATH/TO/ClaudeOrchestratorMCP"
    }
  }
}
```

Or register via the Claude CLI:

```bash
claude mcp add claude-orchestrator \
  /ABSOLUTE/PATH/TO/venv/bin/python3 \
  /ABSOLUTE/PATH/TO/real_mcp_server.py
```

Restart your client. You should see ~25 tools registered under `claude-orchestrator`.

---

## Quick start

From inside your MCP client, the typical flow is:

```
1. create_real_task(description=..., phases=[...])
2. get_phase_status(task_id)              ← always your guide for "what next?"
3. deploy_opus_agent(...) / deploy_sonnet_agent(...)
4. check_phase_progress(task_id)          ← while agents run
5. (system auto-submits for review when all workers finish)
6. get_review_status(task_id)             ← while reviewer is working
7. APPROVED → next phase auto-activates, go back to step 2.
   REVISION_NEEDED → deploy fix agents, then mark_revision_ready(task_id).
```

A minimal task:

```python
create_real_task(
  description="Add OAuth login to the auth service",
  phases=[
    {
      "name": "Investigation",
      "deliverables": ["Doc describing current auth flow", "List of touch points"],
      "success_criteria": ["All auth call sites identified", "Migration plan reviewed"],
    },
    {
      "name": "Implementation",
      "deliverables": ["OAuth handler", "Updated middleware", "Migration"],
      "success_criteria": ["All tests pass", "Existing sessions still work"],
    },
    {
      "name": "Testing & QA",
      "deliverables": ["E2E test for login flow", "Manual test report"],
      "success_criteria": ["Happy path + 2 error paths covered"],
    },
  ],
  project_context={
    "dev_server_port": 3000,
    "start_command": "npm run dev",
    "test_url": "http://localhost:3000",
  },
)
```

If your last phase name doesn't contain `test`, `testing`, `verification`, `qa`, or `quality`, the orchestrator auto-appends a Final Testing phase.

---

## Tool reference (cheat sheet)

| Goal | Tool |
|------|------|
| What should I do next? | `get_phase_status` |
| Watch agents work | `check_phase_progress` |
| Deploy worker | `deploy_opus_agent`, `deploy_sonnet_agent` |
| Deploy design agent (Gemini) | `deploy_design_agent` |
| Signal "all fix agents deployed" | `mark_revision_ready` |
| Watch review | `get_review_status` |
| Read prior-phase context | `get_accumulated_task_context`, `get_phase_handover` |
| Force-approve crashed review | `approve_phase_review(force_escalated=True)` |
| Abort a stuck review | `abort_stalled_review` |
| Read agent output | `get_agent_output` |
| Kill an agent | `kill_real_agent` |

Full tool docstrings are in [`real_mcp_server.py`](./real_mcp_server.py); state machine semantics in [`CLAUDE.md`](./CLAUDE.md).

---

## Repository layout

```
real_mcp_server.py     # MCP server entry point (stdio)
orchestrator/          # core: state machine, deployment, review, handover, health daemon
  state_db.py          #   SQLite source of truth
  lifecycle.py         #   phase transitions
  deployment.py        #   tmux agent spawn
  review.py            #   reviewer/critique flow
  health_daemon.py     #   detects dead reviewers, retries / escalates
dashboard/             # FastAPI backend + React/Tauri frontend (optional UI)
scripts/               # ops scripts (registry management)
tests/                 # pytest suite for state_db + review schema
.mcp.json.example      # copy this to wire into your MCP client
```

`.agent-workspace/` is created at runtime to hold agent prompts, findings, and progress logs. It is gitignored — runs are not for sharing.

---

## Optional: dashboard

A web UI under `dashboard/` visualizes tasks, phases, and agent logs in real time. It's a FastAPI backend + React frontend with a Tauri desktop wrapper.

```bash
cd dashboard
./start-dashboard.sh    # boots backend (8765) + frontend
```

The dashboard is **not** required to use the MCP server. Treat it as a debug/observability tool.

---

## Development

```bash
pip install -e ".[dev]"
pytest tests/
```

Tests cover the state machine, review schema, and migrations. There is no end-to-end agent test — running real agents requires the `claude` CLI and bills your account.

---

## Troubleshooting

**`No module named 'fastmcp.server.tasks.routing'`** — your `fastmcp` is too old. The 2.x line lacks that submodule; we require 3.x:

```bash
pip install --upgrade 'fastmcp>=3.0.0,<4.0.0'
```

The server now fails fast at startup with this same fix command if it detects an incompatible version.

---

## Known limitations

- Workers run as detached `tmux` sessions on the host machine. There is **no sandboxing** — agents have the same filesystem and shell access as the user running the MCP server.
- The `claude` CLI must be authenticated and on `$PATH` for every shell `tmux` spawns. If your shell rc files don't put it there, agents will fail silently.
- Agent outputs can be large. SQLite is the source of truth; JSONL files are append-only audit logs.
- Review is single-reviewer + single-critique. There is no consensus across multiple reviewers.

---

## License

MIT — see [`LICENSE`](./LICENSE).

## Contributing

Issues and PRs welcome. Please run `pytest tests/` and keep the state machine invariants intact (see `CLAUDE.md`).
