"""
SQLite-backed materialized state for Claude Orchestrator.

Design:
- JSONL files remain the append-only source of truth (audit log / events).
- SQLite stores the latest derived state for fast, consistent reads and phase logic.
- Registry JSON remains for backwards compatibility, but is treated as a cache that may drift.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ALLOWED_AGENT_STATUSES = {
    "running",
    "working",
    "blocked",
    "completed",
    "failed",
    "error",
    "terminated",
    "reviewing",
    "phase_completed",
    "killed",
}

AGENT_TERMINAL_STATUSES = {"completed", "failed", "error", "terminated", "killed", "phase_completed"}
AGENT_ACTIVE_STATUSES = {"running", "working", "blocked", "reviewing"}


def normalize_agent_status(status: Any, progress: Any = None) -> str:
    if not status:
        return "working"
    s = str(status).lower()
    if s in ALLOWED_AGENT_STATUSES:
        return s
    if s in {"pending", "starting"}:
        return "running"
    try:
        p = int(progress) if progress is not None else None
    except Exception:
        p = None
    if p == 100:
        return "completed"
    if p == 0:
        return "running"
    return "working"


def _parse_dt(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        # Validate ISO format by parsing then re-serializing.
        return datetime.fromisoformat(str(value)).isoformat()
    except Exception:
        return None


def get_state_db_path(workspace_base: str) -> str:
    base = os.path.abspath(workspace_base)
    os.makedirs(os.path.join(base, "registry"), exist_ok=True)
    return os.path.join(base, "registry", "state.sqlite3")


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tasks (
          task_id TEXT PRIMARY KEY,
          workspace TEXT,
          workspace_base TEXT,
          description TEXT,
          status TEXT,
          priority TEXT,
          client_cwd TEXT,
          created_at TEXT,
          updated_at TEXT,
          current_phase_index INTEGER
        );

        CREATE TABLE IF NOT EXISTS phases (
          task_id TEXT NOT NULL,
          phase_index INTEGER NOT NULL,
          phase_id TEXT,
          name TEXT,
          status TEXT,
          created_at TEXT,
          started_at TEXT,
          completed_at TEXT,
          PRIMARY KEY (task_id, phase_index),
          FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS agents (
          agent_id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          type TEXT,
          tmux_session TEXT,
          parent TEXT,
          depth INTEGER,
          phase_index INTEGER,
          started_at TEXT,
          completed_at TEXT,
          status TEXT,
          progress INTEGER,
          last_update TEXT,
          prompt_preview TEXT,
          FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_agents_task ON agents(task_id);
        CREATE INDEX IF NOT EXISTS idx_agents_task_phase ON agents(task_id, phase_index);

        CREATE TABLE IF NOT EXISTS agent_progress_latest (
          task_id TEXT NOT NULL,
          agent_id TEXT NOT NULL,
          timestamp TEXT,
          status TEXT,
          progress INTEGER,
          message TEXT,
          PRIMARY KEY (task_id, agent_id),
          FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );
        """
    )


def _read_json_safely(path: str, max_attempts: int = 3) -> Optional[Dict[str, Any]]:
    for _ in range(max_attempts):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return json.load(f)
        except Exception:
            # Small backoff helps when a writer truncates/re-writes.
            try:
                import time

                time.sleep(0.03)
            except Exception:
                pass
    return None


def _read_last_jsonl_entry(path: str) -> Optional[Dict[str, Any]]:
    try:
        if not os.path.exists(path):
            return None
        from collections import deque

        tail = deque(maxlen=20)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line:
                    tail.append(line)
        for line in reversed(tail):
            try:
                return json.loads(line)
            except Exception:
                continue
        return None
    except Exception:
        return None


def ensure_db(workspace_base: str) -> str:
    db_path = get_state_db_path(workspace_base)
    conn = _connect(db_path)
    try:
        _init_db(conn)
    finally:
        conn.close()
    return db_path


def record_progress(
    *,
    workspace_base: str,
    task_id: str,
    agent_id: str,
    timestamp: str,
    status: Any,
    message: str,
    progress: Any,
) -> None:
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        norm_status = normalize_agent_status(status, progress)
        try:
            p = int(progress)
        except Exception:
            p = 0
        ts = _parse_dt(timestamp) or datetime.now().isoformat()

        conn.execute(
            """
            INSERT INTO agent_progress_latest(task_id, agent_id, timestamp, status, progress, message)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(task_id, agent_id) DO UPDATE SET
              timestamp=excluded.timestamp,
              status=excluded.status,
              progress=excluded.progress,
              message=excluded.message
            """,
            (task_id, agent_id, ts, norm_status, p, message or ""),
        )

        # Also update the agents table (materialized latest state).
        completed_at = ts if norm_status in AGENT_TERMINAL_STATUSES and norm_status == "completed" else None
        conn.execute(
            """
            UPDATE agents
               SET status=?,
                   progress=?,
                   last_update=?,
                   completed_at=COALESCE(completed_at, ?)
             WHERE agent_id=? AND task_id=?
            """,
            (norm_status, p, ts, completed_at, agent_id, task_id),
        )
        conn.execute(
            "UPDATE tasks SET updated_at=? WHERE task_id=?",
            (ts, task_id),
        )
    finally:
        conn.close()


def reconcile_task_workspace(task_workspace: str) -> Optional[str]:
    """
    Materialize state for a task workspace into SQLite.

    Reads:
    - AGENT_REGISTRY.json (metadata only)
    - progress/*_progress.jsonl (latest event per agent, source of truth)
    """
    registry_path = os.path.join(task_workspace, "AGENT_REGISTRY.json")
    if not os.path.exists(registry_path):
        return None

    registry = _read_json_safely(registry_path)
    if not registry:
        return None

    task_id = registry.get("task_id") or os.path.basename(task_workspace)
    workspace_base = os.path.dirname(os.path.abspath(task_workspace))
    db_path = ensure_db(workspace_base)

    conn = _connect(db_path)
    try:
        created_at = _parse_dt(registry.get("created_at")) or datetime.fromtimestamp(0).isoformat()
        updated_at = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO tasks(task_id, workspace, workspace_base, description, status, priority, client_cwd,
                              created_at, updated_at, current_phase_index)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(task_id) DO UPDATE SET
              workspace=excluded.workspace,
              workspace_base=excluded.workspace_base,
              description=COALESCE(excluded.description, tasks.description),
              status=COALESCE(excluded.status, tasks.status),
              priority=COALESCE(excluded.priority, tasks.priority),
              client_cwd=COALESCE(excluded.client_cwd, tasks.client_cwd),
              updated_at=excluded.updated_at,
              current_phase_index=excluded.current_phase_index
            """,
            (
                task_id,
                registry.get("workspace") or task_workspace,
                registry.get("workspace_base") or workspace_base,
                registry.get("task_description") or "",
                registry.get("status") or "INITIALIZED",
                registry.get("priority") or "P2",
                registry.get("client_cwd") or "",
                created_at,
                updated_at,
                int(registry.get("current_phase_index") or 0),
            ),
        )

        # Phases (metadata)
        phases = registry.get("phases") or []
        for idx, phase in enumerate(phases):
            conn.execute(
                """
                INSERT INTO phases(task_id, phase_index, phase_id, name, status, created_at, started_at, completed_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id, phase_index) DO UPDATE SET
                  phase_id=excluded.phase_id,
                  name=excluded.name,
                  status=excluded.status,
                  created_at=excluded.created_at,
                  started_at=excluded.started_at,
                  completed_at=excluded.completed_at
                """,
                (
                    task_id,
                    int(idx),
                    phase.get("id"),
                    phase.get("name"),
                    phase.get("status"),
                    _parse_dt(phase.get("created_at")),
                    _parse_dt(phase.get("started_at")),
                    _parse_dt(phase.get("completed_at")),
                ),
            )

        # Agents: registry metadata + JSONL-derived latest status/progress.
        for agent in registry.get("agents") or []:
            agent_id = agent.get("id") or agent.get("agent_id")
            if not agent_id:
                continue

            tracked = agent.get("tracked_files") or {}
            progress_path = tracked.get("progress_file") or os.path.join(
                task_workspace, "progress", f"{agent_id}_progress.jsonl"
            )
            last = _read_last_jsonl_entry(progress_path)

            merged_progress = last.get("progress") if last else agent.get("progress", 0)
            merged_status = last.get("status") if last else agent.get("status")
            norm_status = normalize_agent_status(merged_status, merged_progress)
            try:
                p = int(merged_progress)
            except Exception:
                p = int(agent.get("progress") or 0)

            last_update = _parse_dt((last or {}).get("timestamp")) or _parse_dt(agent.get("last_update")) or created_at
            started_at = _parse_dt(agent.get("started_at") or agent.get("start_time")) or created_at
            completed_at = _parse_dt(agent.get("completed_at") or agent.get("end_time"))
            if norm_status == "completed" and not completed_at:
                completed_at = _parse_dt((last or {}).get("timestamp")) or last_update

            conn.execute(
                """
                INSERT INTO agents(agent_id, task_id, type, tmux_session, parent, depth, phase_index,
                                   started_at, completed_at, status, progress, last_update, prompt_preview)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(agent_id) DO UPDATE SET
                  task_id=excluded.task_id,
                  type=excluded.type,
                  tmux_session=excluded.tmux_session,
                  parent=excluded.parent,
                  depth=excluded.depth,
                  phase_index=excluded.phase_index,
                  started_at=excluded.started_at,
                  completed_at=COALESCE(excluded.completed_at, agents.completed_at),
                  status=excluded.status,
                  progress=excluded.progress,
                  last_update=excluded.last_update,
                  prompt_preview=excluded.prompt_preview
                """,
                (
                    agent_id,
                    task_id,
                    agent.get("type") or agent.get("agent_type") or "unknown",
                    agent.get("tmux_session") or "",
                    agent.get("parent") or "orchestrator",
                    int(agent.get("depth") or 1),
                    int(agent.get("phase_index") or 0),
                    started_at,
                    completed_at,
                    norm_status,
                    p,
                    last_update,
                    (agent.get("prompt") or "")[:200],
                ),
            )

            if last:
                conn.execute(
                    """
                    INSERT INTO agent_progress_latest(task_id, agent_id, timestamp, status, progress, message)
                    VALUES(?,?,?,?,?,?)
                    ON CONFLICT(task_id, agent_id) DO UPDATE SET
                      timestamp=excluded.timestamp,
                      status=excluded.status,
                      progress=excluded.progress,
                      message=excluded.message
                    """,
                    (
                        task_id,
                        agent_id,
                        _parse_dt(last.get("timestamp")) or last_update,
                        norm_status,
                        p,
                        (last.get("message") or "") if isinstance(last, dict) else "",
                    ),
                )

        return db_path
    finally:
        conn.close()


def load_task_snapshot(*, workspace_base: str, task_id: str) -> Optional[Dict[str, Any]]:
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return None
        task = dict(row)

        phases = conn.execute(
            "SELECT * FROM phases WHERE task_id=? ORDER BY phase_index ASC",
            (task_id,),
        ).fetchall()
        task["phases"] = [dict(r) for r in phases]

        agents = conn.execute(
            "SELECT * FROM agents WHERE task_id=? ORDER BY started_at ASC",
            (task_id,),
        ).fetchall()
        task["agents"] = [dict(r) for r in agents]

        # Derived counts
        statuses = [a.get("status") for a in task["agents"]]
        task["counts"] = {
            "total": len(statuses),
            "active": sum(1 for s in statuses if s in AGENT_ACTIVE_STATUSES),
            "completed": sum(1 for s in statuses if s == "completed"),
            "terminal": sum(1 for s in statuses if s in AGENT_TERMINAL_STATUSES),
        }
        return task
    finally:
        conn.close()


def load_phase_snapshot(*, workspace_base: str, task_id: str, phase_index: int) -> Dict[str, Any]:
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        agents = conn.execute(
            "SELECT agent_id, type, status, progress, last_update FROM agents WHERE task_id=? AND phase_index=?",
            (task_id, int(phase_index)),
        ).fetchall()
        agent_rows = [dict(r) for r in agents]
        completed = [a for a in agent_rows if a.get("status") in {"completed", "phase_completed"}]
        failed = [a for a in agent_rows if a.get("status") in {"failed", "error", "terminated", "killed"}]
        pending = [a for a in agent_rows if a.get("status") not in AGENT_TERMINAL_STATUSES]
        return {
            "agents": agent_rows,
            "counts": {
                "total": len(agent_rows),
                "completed": len(completed),
                "failed": len(failed),
                "pending": len(pending),
                "all_done": (len(agent_rows) > 0 and len(pending) == 0),
            },
        }
    finally:
        conn.close()


def load_recent_progress_latest(*, workspace_base: str, task_id: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Return most recent agent progress updates (latest per agent), ordered by timestamp desc."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT task_id, agent_id, timestamp, status, progress, message
              FROM agent_progress_latest
             WHERE task_id=?
             ORDER BY timestamp DESC
             LIMIT ?
            """,
            (task_id, int(limit)),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_global_counts(*, workspace_base: str) -> Dict[str, int]:
    """
    Get global counts derived from SQLite database.

    Returns:
        Dict with keys: total_tasks, active_tasks, completed_tasks, failed_tasks,
                       total_agents, active_agents, completed_agents, failed_agents
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        # Task counts
        task_counts = conn.execute("""
            SELECT
                COUNT(*) as total_tasks,
                SUM(CASE WHEN status IN ('ACTIVE', 'IN_PROGRESS', 'RUNNING') THEN 1 ELSE 0 END) as active_tasks,
                SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_tasks,
                SUM(CASE WHEN status IN ('FAILED', 'ERROR', 'TERMINATED') THEN 1 ELSE 0 END) as failed_tasks
            FROM tasks
        """).fetchone()

        # Agent counts - using normalized statuses from AGENT_ACTIVE_STATUSES and AGENT_TERMINAL_STATUSES
        agent_counts = conn.execute(f"""
            SELECT
                COUNT(*) as total_agents,
                SUM(CASE WHEN status IN {tuple(AGENT_ACTIVE_STATUSES)} THEN 1 ELSE 0 END) as active_agents,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_agents,
                SUM(CASE WHEN status IN ('failed', 'error', 'terminated', 'killed') THEN 1 ELSE 0 END) as failed_agents
            FROM agents
        """).fetchone()

        return {
            "total_tasks": task_counts["total_tasks"] or 0,
            "active_tasks": task_counts["active_tasks"] or 0,
            "completed_tasks": task_counts["completed_tasks"] or 0,
            "failed_tasks": task_counts["failed_tasks"] or 0,
            "total_agents": agent_counts["total_agents"] or 0,
            "active_agents": agent_counts["active_agents"] or 0,
            "completed_agents": agent_counts["completed_agents"] or 0,
            "failed_agents": agent_counts["failed_agents"] or 0,
        }
    finally:
        conn.close()


def get_task_counts(*, workspace_base: str, task_id: str) -> Dict[str, int]:
    """
    Get counts for a specific task from SQLite.

    Returns:
        Dict with keys: total_agents, active_agents, completed_agents, failed_agents,
                       total_phases, active_phases, completed_phases
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        # Agent counts for this task
        agent_counts = conn.execute(f"""
            SELECT
                COUNT(*) as total_agents,
                SUM(CASE WHEN status IN {tuple(AGENT_ACTIVE_STATUSES)} THEN 1 ELSE 0 END) as active_agents,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_agents,
                SUM(CASE WHEN status IN ('failed', 'error', 'terminated', 'killed') THEN 1 ELSE 0 END) as failed_agents
            FROM agents
            WHERE task_id = ?
        """, (task_id,)).fetchone()

        # Phase counts for this task
        phase_counts = conn.execute("""
            SELECT
                COUNT(*) as total_phases,
                SUM(CASE WHEN status IN ('ACTIVE', 'AWAITING_REVIEW', 'UNDER_REVIEW', 'REVISING') THEN 1 ELSE 0 END) as active_phases,
                SUM(CASE WHEN status = 'APPROVED' THEN 1 ELSE 0 END) as completed_phases
            FROM phases
            WHERE task_id = ?
        """, (task_id,)).fetchone()

        return {
            "total_agents": agent_counts["total_agents"] or 0,
            "active_agents": agent_counts["active_agents"] or 0,
            "completed_agents": agent_counts["completed_agents"] or 0,
            "failed_agents": agent_counts["failed_agents"] or 0,
            "total_phases": phase_counts["total_phases"] or 0,
            "active_phases": phase_counts["active_phases"] or 0,
            "completed_phases": phase_counts["completed_phases"] or 0,
        }
    finally:
        conn.close()


def get_dashboard_summary(*, workspace_base: str, limit: int = 20) -> Dict[str, Any]:
    """
    Get comprehensive summary for dashboard display.

    Returns:
        Dict with:
        - global_counts: All global count statistics
        - recent_tasks: List of recent task summaries with their agent counts
        - active_agents: List of currently active agents
        - task_status_distribution: Count of tasks by status
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        # Get global counts
        global_counts = get_global_counts(workspace_base=workspace_base)

        # Get recent tasks with their counts
        recent_tasks = conn.execute(f"""
            SELECT
                t.task_id,
                t.description,
                t.status as task_status,
                t.priority,
                t.created_at,
                t.updated_at,
                t.current_phase_index,
                COUNT(DISTINCT a.agent_id) as total_agents,
                SUM(CASE WHEN a.status IN {tuple(AGENT_ACTIVE_STATUSES)} THEN 1 ELSE 0 END) as active_agents,
                SUM(CASE WHEN a.status = 'completed' THEN 1 ELSE 0 END) as completed_agents,
                AVG(CASE WHEN a.progress IS NOT NULL THEN a.progress ELSE 0 END) as avg_progress
            FROM tasks t
            LEFT JOIN agents a ON t.task_id = a.task_id
            GROUP BY t.task_id
            ORDER BY t.created_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

        # Get list of active agents
        active_agents = conn.execute(f"""
            SELECT
                a.agent_id,
                a.task_id,
                a.type,
                a.status,
                a.progress,
                a.last_update,
                a.tmux_session,
                t.description as task_description
            FROM agents a
            JOIN tasks t ON a.task_id = t.task_id
            WHERE a.status IN {tuple(AGENT_ACTIVE_STATUSES)}
            ORDER BY a.last_update DESC
            LIMIT 50
        """).fetchall()

        # Get task status distribution
        status_dist = conn.execute("""
            SELECT
                status,
                COUNT(*) as count
            FROM tasks
            GROUP BY status
        """).fetchall()

        return {
            "global_counts": global_counts,
            "recent_tasks": [dict(r) for r in recent_tasks],
            "active_agents": [dict(r) for r in active_agents],
            "task_status_distribution": {row["status"]: row["count"] for row in status_dist},
        }
    finally:
        conn.close()


# Compatibility helpers for incremental migration (if needed)
def increment_active_agents(*, workspace_base: str, task_id: str) -> None:
    """
    Compatibility helper - no-op since counts are derived from DB.
    Kept for backward compatibility during migration.
    """
    pass  # Counts are derived, not stored


def decrement_active_agents(*, workspace_base: str, task_id: str) -> None:
    """
    Compatibility helper - no-op since counts are derived from DB.
    Kept for backward compatibility during migration.
    """
    pass  # Counts are derived, not stored


# ========================================================================================
# TASK AND AGENT LIFECYCLE TRANSITION FUNCTIONS
# ========================================================================================

def transition_task_to_active(*, workspace_base: str, task_id: str) -> bool:
    """
    Transition task from INITIALIZED to ACTIVE when first agent starts.

    Returns True if transition occurred, False if already active or failed.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        # Check current status
        row = conn.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return False

        current_status = row["status"]
        if current_status not in ["INITIALIZED", "PENDING"]:
            # Already active or in some other state
            return False

        # Transition to ACTIVE
        timestamp = datetime.now().isoformat()
        conn.execute(
            "UPDATE tasks SET status='ACTIVE', updated_at=? WHERE task_id=?",
            (timestamp, task_id)
        )

        # Log the transition
        print(f"[STATE_DB] Task {task_id} transitioned from {current_status} to ACTIVE")
        return True
    finally:
        conn.close()


def transition_task_to_completed(*, workspace_base: str, task_id: str) -> bool:
    """
    Transition task to COMPLETED when all agents are done.

    Returns True if transition occurred, False if not ready or failed.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        # Check if all agents are terminal
        agents = conn.execute(
            "SELECT agent_id, status FROM agents WHERE task_id=?",
            (task_id,)
        ).fetchall()

        if not agents:
            # No agents, can't complete
            return False

        # Check if all agents are in terminal status
        non_terminal = [a for a in agents if a["status"] not in AGENT_TERMINAL_STATUSES]
        if non_terminal:
            # Some agents still running
            return False

        # Check current task status
        row = conn.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return False

        current_status = row["status"]
        if current_status in ["COMPLETED", "FAILED", "CANCELLED"]:
            # Already in terminal state
            return False

        # Determine final status based on agent outcomes
        failed_count = sum(1 for a in agents if a["status"] in {"failed", "error", "terminated", "killed"})
        final_status = "FAILED" if failed_count > len(agents) // 2 else "COMPLETED"

        # Transition to final status
        timestamp = datetime.now().isoformat()
        conn.execute(
            "UPDATE tasks SET status=?, updated_at=? WHERE task_id=?",
            (final_status, timestamp, task_id)
        )

        # Log the transition
        print(f"[STATE_DB] Task {task_id} transitioned from {current_status} to {final_status}")
        print(f"[STATE_DB]   - Total agents: {len(agents)}, Failed: {failed_count}")
        return True
    finally:
        conn.close()


def check_task_completion(*, workspace_base: str, task_id: str) -> bool:
    """
    Check if all agents for a task are in terminal state.

    Returns True if all agents are terminal (completed/failed/terminated).
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        agents = conn.execute(
            "SELECT status FROM agents WHERE task_id=?",
            (task_id,)
        ).fetchall()

        if not agents:
            return False

        # Check if all agents are terminal
        for agent in agents:
            if agent["status"] not in AGENT_TERMINAL_STATUSES:
                return False

        return True
    finally:
        conn.close()


def mark_agent_terminal(
    *,
    workspace_base: str,
    agent_id: str,
    status: str,
    reason: str = "",
    auto_rollup: bool = True
) -> Dict[str, Any]:
    """
    Mark an agent as terminal (completed/failed/terminated).

    Args:
        workspace_base: Base workspace directory
        agent_id: Agent ID to mark terminal
        status: Terminal status (must be in AGENT_TERMINAL_STATUSES)
        reason: Optional reason for termination
        auto_rollup: If True, automatically check and transition task status

    Returns:
        Dict with agent info and any task transitions that occurred
    """
    if status not in AGENT_TERMINAL_STATUSES:
        raise ValueError(f"Status {status} is not a terminal status. Must be one of: {AGENT_TERMINAL_STATUSES}")

    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        # Get agent and task info
        row = conn.execute(
            "SELECT agent_id, task_id, status as current_status FROM agents WHERE agent_id=?",
            (agent_id,)
        ).fetchone()

        if not row:
            return {"error": f"Agent {agent_id} not found"}

        task_id = row["task_id"]
        current_status = row["current_status"]

        if current_status in AGENT_TERMINAL_STATUSES:
            return {"already_terminal": True, "agent_id": agent_id, "status": current_status}

        # Mark agent as terminal
        timestamp = datetime.now().isoformat()
        conn.execute(
            """
            UPDATE agents
            SET status=?,
                completed_at=?,
                last_update=?
            WHERE agent_id=?
            """,
            (status, timestamp, timestamp, agent_id)
        )

        # Also update progress table
        progress_val = 100 if status == "completed" else 0
        conn.execute(
            """
            INSERT INTO agent_progress_latest(task_id, agent_id, timestamp, status, progress, message)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(task_id, agent_id) DO UPDATE SET
              timestamp=excluded.timestamp,
              status=excluded.status,
              progress=excluded.progress,
              message=excluded.message
            """,
            (task_id, agent_id, timestamp, status, progress_val, reason)
        )

        result = {
            "agent_id": agent_id,
            "task_id": task_id,
            "transitioned_to": status,
            "from_status": current_status,
            "reason": reason
        }

        # Auto-rollup: Check if task should transition
        if auto_rollup:
            # Check if all agents are now terminal
            if check_task_completion(workspace_base=workspace_base, task_id=task_id):
                # Try to transition task to completed
                if transition_task_to_completed(workspace_base=workspace_base, task_id=task_id):
                    result["task_transition"] = "COMPLETED"

        return result
    finally:
        conn.close()


def get_active_agent_count(*, workspace_base: str, task_id: str) -> int:
    """
    Get accurate count of active (non-terminal) agents for a task.

    Returns count of agents in AGENT_ACTIVE_STATUSES.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) as count
            FROM agents
            WHERE task_id=? AND status IN ({})
            """.format(','.join('?' * len(AGENT_ACTIVE_STATUSES))),
            (task_id, *AGENT_ACTIVE_STATUSES)
        ).fetchone()

        return row["count"] if row else 0
    finally:
        conn.close()


def get_phase_agent_counts(*, workspace_base: str, task_id: str, phase_index: int) -> Dict[str, int]:
    """
    Get agent counts for a specific phase.

    Returns dict with counts: total, active, completed, failed, pending
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        agents = conn.execute(
            "SELECT status FROM agents WHERE task_id=? AND phase_index=?",
            (task_id, int(phase_index))
        ).fetchall()

        statuses = [a["status"] for a in agents]

        return {
            "total": len(statuses),
            "active": sum(1 for s in statuses if s in AGENT_ACTIVE_STATUSES),
            "completed": sum(1 for s in statuses if s == "completed"),
            "failed": sum(1 for s in statuses if s in {"failed", "error", "terminated", "killed"}),
            "pending": sum(1 for s in statuses if s not in AGENT_TERMINAL_STATUSES)
        }
    finally:
        conn.close()


def get_global_active_counts(*, workspace_base: str) -> Dict[str, int]:
    """
    Get accurate global counts of active tasks and agents from SQLite.

    Returns dict with active_tasks and active_agents counts.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        # Count active tasks (tasks with status='ACTIVE')
        active_tasks_row = conn.execute(
            "SELECT COUNT(*) as count FROM tasks WHERE status='ACTIVE'"
        ).fetchone()
        active_tasks = active_tasks_row["count"] if active_tasks_row else 0

        # Count active agents (agents with active status)
        active_agents_row = conn.execute(
            """
            SELECT COUNT(*) as count
            FROM agents
            WHERE status IN ({})
            """.format(','.join('?' * len(AGENT_ACTIVE_STATUSES))),
            (*AGENT_ACTIVE_STATUSES,)
        ).fetchone()
        active_agents = active_agents_row["count"] if active_agents_row else 0

        return {
            "active_tasks": active_tasks,
            "active_agents": active_agents
        }
    finally:
        conn.close()
