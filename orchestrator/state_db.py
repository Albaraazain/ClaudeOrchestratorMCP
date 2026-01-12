"""
SQLite-backed materialized state for Claude Orchestrator - ENHANCED VERSION.

Design:
- JSONL files remain the append-only source of truth (audit log / events).
- SQLite stores the latest derived state for fast, consistent reads and phase logic.
- Registry JSON remains for backwards compatibility, but is treated as a cache that may drift.

Enhancements:
- Added missing columns to agents table: model, claude_pid, cursor_pid, tracked_files
- Added new tables: reviews, agent_findings, handovers
- Added CRUD functions for lifecycle management and dashboard integration
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


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

# Task statuses for lifecycle management
TASK_STATUSES = {
    "INITIALIZED",
    "ACTIVE",
    "COMPLETED",
    "FAILED",
    "CANCELLED"
}

# Phase statuses for state machine
PHASE_STATUSES = {
    "PENDING",
    "ACTIVE",
    "AWAITING_REVIEW",
    "UNDER_REVIEW",
    "APPROVED",
    "REJECTED",
    "REVISING",
    "ESCALATED"
}


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
    """Initialize database schema with all required tables and indexes."""

    # First, create the base tables
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
          description TEXT,
          deliverables TEXT,      -- JSON array of expected deliverables for this phase
          success_criteria TEXT,  -- JSON array of success criteria for this phase
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
          model TEXT,
          tmux_session TEXT,
          parent TEXT,
          depth INTEGER,
          phase_index INTEGER,
          claude_pid INTEGER,
          cursor_pid INTEGER,
          tracked_files TEXT,  -- JSON field for tracked files
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
        CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

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

        -- New table: reviews for agentic review system
        CREATE TABLE IF NOT EXISTS reviews (
          review_id TEXT PRIMARY KEY,
          task_id TEXT NOT NULL,
          phase_index INTEGER NOT NULL,
          status TEXT, -- in_progress, completed, aborted
          verdict TEXT, -- approved, rejected, mixed
          created_at TEXT,
          completed_at TEXT,
          reviewer_notes TEXT,
          reviewer_agent_ids TEXT, -- JSON array of reviewer agent IDs
          critique_agent_id TEXT, -- ID of the critique agent
          FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_reviews_task ON reviews(task_id);
        CREATE INDEX IF NOT EXISTS idx_reviews_phase ON reviews(task_id, phase_index);

        -- New table: agent_findings for discoveries
        CREATE TABLE IF NOT EXISTS agent_findings (
          finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT NOT NULL,
          agent_id TEXT NOT NULL,
          phase_index INTEGER,
          finding_type TEXT, -- issue, solution, insight, recommendation, blocker
          severity TEXT, -- low, medium, high, critical
          message TEXT,
          data TEXT, -- JSON field for additional data
          created_at TEXT,
          FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
          FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_findings_task ON agent_findings(task_id);
        CREATE INDEX IF NOT EXISTS idx_findings_agent ON agent_findings(agent_id);
        CREATE INDEX IF NOT EXISTS idx_findings_type ON agent_findings(finding_type);
        CREATE INDEX IF NOT EXISTS idx_findings_severity ON agent_findings(severity);
        CREATE INDEX IF NOT EXISTS idx_findings_created ON agent_findings(created_at);

        -- New table: handovers for phase transitions
        CREATE TABLE IF NOT EXISTS handovers (
          handover_id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT NOT NULL,
          from_phase_index INTEGER NOT NULL,
          to_phase_index INTEGER NOT NULL,
          summary TEXT,
          key_findings TEXT, -- JSON array
          blockers TEXT, -- JSON array
          recommendations TEXT, -- JSON array
          created_at TEXT,
          FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_handovers_task ON handovers(task_id);
        CREATE INDEX IF NOT EXISTS idx_handovers_phase ON handovers(from_phase_index, to_phase_index);
        """
    )

    # Check if we need to add missing columns to existing agents table (migration)
    cursor = conn.execute("PRAGMA table_info(agents)")
    columns = {row[1] for row in cursor.fetchall()}

    # Add missing columns via ALTER TABLE if they don't exist
    migrations = []

    if 'model' not in columns:
        migrations.append("ALTER TABLE agents ADD COLUMN model TEXT;")
    if 'claude_pid' not in columns:
        migrations.append("ALTER TABLE agents ADD COLUMN claude_pid INTEGER;")
    if 'cursor_pid' not in columns:
        migrations.append("ALTER TABLE agents ADD COLUMN cursor_pid INTEGER;")
    if 'tracked_files' not in columns:
        migrations.append("ALTER TABLE agents ADD COLUMN tracked_files TEXT;")

    for migration in migrations:
        try:
            conn.execute(migration)
            # Don't print to stdout in MCP server - it breaks the protocol
            # print(f"Applied migration: {migration}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                # Log to stderr instead if needed for debugging
                import sys
                print(f"[STATE_DB] Migration error: {e}", file=sys.stderr)
                # Re-raise to ensure we know about failures
                raise

    # Create indexes for the new columns (if they were just added)
    if migrations:
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_claude_pid ON agents(claude_pid);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_agents_cursor_pid ON agents(cursor_pid);")
        except sqlite3.OperationalError:
            pass  # Indexes may already exist

    # Check if we need to add missing columns to existing phases table (migration)
    cursor = conn.execute("PRAGMA table_info(phases)")
    phase_columns = {row[1] for row in cursor.fetchall()}

    phase_migrations = []
    if 'description' not in phase_columns:
        phase_migrations.append("ALTER TABLE phases ADD COLUMN description TEXT;")
    if 'deliverables' not in phase_columns:
        phase_migrations.append("ALTER TABLE phases ADD COLUMN deliverables TEXT;")
    if 'success_criteria' not in phase_columns:
        phase_migrations.append("ALTER TABLE phases ADD COLUMN success_criteria TEXT;")

    for migration in phase_migrations:
        try:
            conn.execute(migration)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                import sys
                print(f"[STATE_DB] Phase migration error: {e}", file=sys.stderr)
                raise

    # =========================================================================
    # NEW TABLES FOR FULL SQLITE MIGRATION (Jan 2026)
    # These replace JSON registry file operations with SQLite transactions
    # =========================================================================

    conn.executescript(
        """
        -- Individual reviewer verdicts (replaces JSON reviews[].verdicts array)
        CREATE TABLE IF NOT EXISTS review_verdicts (
            verdict_id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            reviewer_agent_id TEXT,
            verdict TEXT NOT NULL,  -- approved, rejected, needs_revision
            findings TEXT,          -- JSON array of findings
            reviewer_notes TEXT,
            submitted_at TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_verdicts_review ON review_verdicts(review_id);
        CREATE INDEX IF NOT EXISTS idx_verdicts_task ON review_verdicts(task_id);

        -- Critique submissions (replaces JSON reviews[].critique object)
        CREATE TABLE IF NOT EXISTS critique_submissions (
            critique_id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            critique_agent_id TEXT,
            observations TEXT,      -- JSON array of observations
            summary TEXT,
            recommendations TEXT,   -- JSON array
            submitted_at TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_critique_review ON critique_submissions(review_id);

        -- Task configuration (replaces JSON max_agents, max_concurrent, project_context, etc.)
        CREATE TABLE IF NOT EXISTS task_config (
            task_id TEXT PRIMARY KEY,
            max_agents INTEGER DEFAULT 50,
            max_concurrent INTEGER DEFAULT 20,
            max_depth INTEGER DEFAULT 5,
            project_context TEXT,       -- JSON for dev_server_port, test_url, framework, etc.
            constraints TEXT,           -- JSON array
            relevant_files TEXT,        -- JSON array
            conversation_history TEXT,  -- JSON array (last 15 messages)
            background_context TEXT,
            expected_deliverables TEXT, -- JSON array
            success_criteria TEXT,      -- JSON array
            FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
        );

        -- Agent parent-child relationships (for spawn hierarchy tracking)
        CREATE TABLE IF NOT EXISTS agent_hierarchy (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            parent_agent_id TEXT,       -- NULL or "orchestrator" for root agents
            child_agent_id TEXT NOT NULL,
            spawned_at TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
            UNIQUE(task_id, child_agent_id)
        );

        CREATE INDEX IF NOT EXISTS idx_hierarchy_parent ON agent_hierarchy(parent_agent_id);
        CREATE INDEX IF NOT EXISTS idx_hierarchy_child ON agent_hierarchy(child_agent_id);
        """
    )

    # Add num_reviewers and auto_spawned columns to reviews table if missing
    cursor = conn.execute("PRAGMA table_info(reviews)")
    review_columns = {row[1] for row in cursor.fetchall()}

    review_migrations = []
    if 'num_reviewers' not in review_columns:
        review_migrations.append("ALTER TABLE reviews ADD COLUMN num_reviewers INTEGER DEFAULT 2;")
    if 'auto_spawned' not in review_columns:
        review_migrations.append("ALTER TABLE reviews ADD COLUMN auto_spawned INTEGER DEFAULT 0;")
    if 'phase_name' not in review_columns:
        review_migrations.append("ALTER TABLE reviews ADD COLUMN phase_name TEXT;")

    for migration in review_migrations:
        try:
            conn.execute(migration)
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                import sys
                print(f"[STATE_DB] Review migration error: {e}", file=sys.stderr)
                raise

    # Add review_id and final_verdict columns to agents table if missing
    if 'review_id' not in columns:
        try:
            conn.execute("ALTER TABLE agents ADD COLUMN review_id TEXT;")
        except sqlite3.OperationalError:
            pass
    if 'final_verdict' not in columns:
        try:
            conn.execute("ALTER TABLE agents ADD COLUMN final_verdict TEXT;")
        except sqlite3.OperationalError:
            pass


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


# ============================================================================
# NEW CRUD FUNCTIONS FOR LIFECYCLE MANAGEMENT AND DASHBOARD INTEGRATION
# ============================================================================


def create_task_with_phases(
    *,
    workspace_base: str,
    task_id: str,
    workspace: str,
    description: str,
    priority: str = "P2",
    client_cwd: Optional[str] = None,
    phases: List[Dict[str, Any]],
    project_context: Optional[Dict[str, Any]] = None,
    max_agents: int = 45,
    max_concurrent: int = 20,
    max_depth: int = 5
) -> Dict[str, Any]:
    """
    Create a new task with its phases directly in SQLite.

    SQLITE MIGRATION: Replaces JSON-based task creation.
    This is the primary entry point for task creation - no JSON files needed.

    Returns:
        Dict with success status and task_id
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()

        conn.execute("BEGIN IMMEDIATE")

        try:
            # Insert task record
            conn.execute(
                """
                INSERT INTO tasks (
                    task_id, workspace, workspace_base, description, status, priority,
                    client_cwd, created_at, updated_at, current_phase_index
                ) VALUES (?, ?, ?, ?, 'INITIALIZED', ?, ?, ?, ?, 0)
                """,
                (task_id, workspace, workspace_base, description, priority, client_cwd, now, now)
            )

            # Insert phase records
            for idx, phase in enumerate(phases):
                phase_id = phase.get('id') or f"phase-{uuid.uuid4().hex[:8]}"
                phase_status = 'ACTIVE' if idx == 0 else 'PENDING'

                conn.execute(
                    """
                    INSERT INTO phases (
                        task_id, phase_index, phase_id, name, description,
                        deliverables, success_criteria, status, created_at, started_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        idx,
                        phase_id,
                        phase.get('name', f'Phase {idx + 1}'),
                        phase.get('description', ''),
                        json.dumps(phase.get('deliverables', [])),
                        json.dumps(phase.get('success_criteria', [])),
                        phase_status,
                        now,
                        now if idx == 0 else None  # Only first phase starts immediately
                    )
                )

            # Insert task config
            conn.execute(
                """
                INSERT INTO task_config (
                    task_id, max_agents, max_concurrent, max_depth, project_context
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (task_id, max_agents, max_concurrent, max_depth,
                 json.dumps(project_context) if project_context else None)
            )

            conn.execute("COMMIT")

            logger.info(f"[SQLITE] Created task {task_id} with {len(phases)} phases")
            return {"success": True, "task_id": task_id}

        except Exception as e:
            conn.execute("ROLLBACK")
            logger.error(f"[SQLITE] Failed to create task {task_id}: {e}")
            return {"success": False, "error": str(e)}

    finally:
        conn.close()


def update_task_status(*, workspace_base: str, task_id: str, new_status: str) -> bool:
    """Update task status for lifecycle transitions."""
    if new_status not in TASK_STATUSES:
        raise ValueError(f"Invalid task status: {new_status}. Must be one of {TASK_STATUSES}")

    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()
        result = conn.execute(
            """
            UPDATE tasks
            SET status = ?, updated_at = ?
            WHERE task_id = ?
            """,
            (new_status, now, task_id)
        )

        # If task is completed/failed, mark all active agents as terminated
        if new_status in ("COMPLETED", "FAILED", "CANCELLED"):
            conn.execute(
                """
                UPDATE agents
                SET status = 'terminated', completed_at = ?
                WHERE task_id = ? AND status IN ('running', 'working', 'blocked', 'reviewing')
                """,
                (now, task_id)
            )

        return result.rowcount > 0
    finally:
        conn.close()


def update_task_phase_index(*, workspace_base: str, task_id: str, new_phase_index: int) -> bool:
    """Update the current phase index for a task."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()
        result = conn.execute(
            """
            UPDATE tasks
            SET current_phase_index = ?, updated_at = ?
            WHERE task_id = ?
            """,
            (new_phase_index, now, task_id)
        )
        return result.rowcount > 0
    finally:
        conn.close()


def update_phase_status(*, workspace_base: str, task_id: str, phase_index: int, new_status: str) -> bool:
    """Update phase status for state machine transitions."""
    if new_status not in PHASE_STATUSES:
        raise ValueError(f"Invalid phase status: {new_status}. Must be one of {PHASE_STATUSES}")

    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()

        # Update phase status
        result = conn.execute(
            """
            UPDATE phases
            SET status = ?
            WHERE task_id = ? AND phase_index = ?
            """,
            (new_status, task_id, phase_index)
        )

        # Set started_at when transitioning to ACTIVE
        if new_status == "ACTIVE":
            conn.execute(
                """
                UPDATE phases
                SET started_at = ?
                WHERE task_id = ? AND phase_index = ? AND started_at IS NULL
                """,
                (now, task_id, phase_index)
            )

        # Set completed_at when transitioning to APPROVED
        elif new_status == "APPROVED":
            conn.execute(
                """
                UPDATE phases
                SET completed_at = ?
                WHERE task_id = ? AND phase_index = ? AND completed_at IS NULL
                """,
                (now, task_id, phase_index)
            )

        # Update task updated_at
        conn.execute(
            "UPDATE tasks SET updated_at = ? WHERE task_id = ?",
            (now, task_id)
        )

        return result.rowcount > 0
    finally:
        conn.close()


def record_agent_finding(
    *,
    workspace_base: str,
    task_id: str,
    agent_id: str,
    finding_type: str,
    severity: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    phase_index: Optional[int] = None
) -> int:
    """Record an agent finding/discovery."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()

        # Get phase_index if not provided
        if phase_index is None:
            result = conn.execute(
                "SELECT phase_index FROM agents WHERE agent_id = ?",
                (agent_id,)
            ).fetchone()
            phase_index = result["phase_index"] if result else 0

        cursor = conn.execute(
            """
            INSERT INTO agent_findings(
                task_id, agent_id, phase_index, finding_type,
                severity, message, data, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                agent_id,
                phase_index,
                finding_type,
                severity,
                message,
                json.dumps(data) if data else None,
                now
            )
        )

        return cursor.lastrowid
    finally:
        conn.close()


def get_all_tasks(
    *,
    workspace_base: str,
    limit: int = 100,
    offset: int = 0,
    status_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get all tasks for dashboard listing."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        query = """
            SELECT
                t.task_id,
                t.description,
                t.status,
                t.priority,
                t.created_at,
                t.updated_at,
                t.current_phase_index,
                COUNT(DISTINCT a.agent_id) as total_agents,
                SUM(CASE WHEN a.status IN ('running', 'working', 'blocked', 'reviewing') THEN 1 ELSE 0 END) as active_agents,
                SUM(CASE WHEN a.status = 'completed' THEN 1 ELSE 0 END) as completed_agents,
                (SELECT name FROM phases WHERE task_id = t.task_id AND phase_index = t.current_phase_index) as current_phase_name,
                (SELECT status FROM phases WHERE task_id = t.task_id AND phase_index = t.current_phase_index) as current_phase_status
            FROM tasks t
            LEFT JOIN agents a ON t.task_id = a.task_id
        """

        params = []
        if status_filter:
            query += " WHERE t.status = ?"
            params.append(status_filter)

        query += """
            GROUP BY t.task_id
            ORDER BY t.updated_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()

        tasks = []
        for row in rows:
            task = dict(row)
            # Convert None values to 0 for counts
            task["total_agents"] = task["total_agents"] or 0
            task["active_agents"] = task["active_agents"] or 0
            task["completed_agents"] = task["completed_agents"] or 0
            tasks.append(task)

        return tasks
    finally:
        conn.close()


def get_active_counts(*, workspace_base: str) -> Dict[str, int]:
    """Get real-time counts for dashboard stats."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        # Count active tasks (status = ACTIVE or has active agents)
        active_tasks = conn.execute(
            """
            SELECT COUNT(DISTINCT t.task_id) as count
            FROM tasks t
            LEFT JOIN agents a ON t.task_id = a.task_id
            WHERE t.status = 'ACTIVE'
               OR a.status IN ('running', 'working', 'blocked', 'reviewing')
            """
        ).fetchone()["count"]

        # Count active agents
        active_agents = conn.execute(
            """
            SELECT COUNT(*) as count
            FROM agents
            WHERE status IN ('running', 'working', 'blocked', 'reviewing')
            """
        ).fetchone()["count"]

        # Count total tasks
        total_tasks = conn.execute(
            "SELECT COUNT(*) as count FROM tasks"
        ).fetchone()["count"]

        # Count completed tasks
        completed_tasks = conn.execute(
            "SELECT COUNT(*) as count FROM tasks WHERE status = 'COMPLETED'"
        ).fetchone()["count"]

        # Count failed tasks
        failed_tasks = conn.execute(
            "SELECT COUNT(*) as count FROM tasks WHERE status = 'FAILED'"
        ).fetchone()["count"]

        return {
            "active_tasks": active_tasks,
            "active_agents": active_agents,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks
        }
    finally:
        conn.close()


def cleanup_stale_agents(*, workspace_base: str, task_id: str, stale_threshold_minutes: int = 10) -> int:
    """Mark agents as failed if they haven't updated in threshold minutes."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now()
        threshold = now.timestamp() - (stale_threshold_minutes * 60)
        threshold_iso = datetime.fromtimestamp(threshold).isoformat()

        # Find and mark stale agents
        result = conn.execute(
            """
            UPDATE agents
            SET status = 'failed',
                completed_at = ?
            WHERE task_id = ?
              AND status IN ('running', 'working', 'blocked')
              AND last_update < ?
            """,
            (now.isoformat(), task_id, threshold_iso)
        )

        # Also update their progress entries
        conn.execute(
            """
            UPDATE agent_progress_latest
            SET status = 'failed'
            WHERE task_id = ?
              AND agent_id IN (
                SELECT agent_id FROM agents
                WHERE task_id = ? AND status = 'failed' AND completed_at = ?
              )
            """,
            (task_id, task_id, now.isoformat())
        )

        return result.rowcount
    finally:
        conn.close()


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

        # Update task status based on agent activity
        # If any agent is active, task should be ACTIVE
        active_count = conn.execute(
            """
            SELECT COUNT(*) as count FROM agents
            WHERE task_id = ? AND status IN ('running', 'working', 'blocked', 'reviewing')
            """,
            (task_id,)
        ).fetchone()["count"]

        if active_count > 0:
            conn.execute(
                "UPDATE tasks SET status = 'ACTIVE', updated_at = ? WHERE task_id = ? AND status = 'INITIALIZED'",
                (ts, task_id)
            )
        else:
            # Check if all agents are completed
            total_agents = conn.execute(
                "SELECT COUNT(*) as count FROM agents WHERE task_id = ?",
                (task_id,)
            ).fetchone()["count"]

            completed_agents = conn.execute(
                "SELECT COUNT(*) as count FROM agents WHERE task_id = ? AND status = 'completed'",
                (task_id,)
            ).fetchone()["count"]

            if total_agents > 0 and total_agents == completed_agents:
                conn.execute(
                    "UPDATE tasks SET status = 'COMPLETED', updated_at = ? WHERE task_id = ?",
                    (ts, task_id)
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

        # Determine task status based on agent activity
        agents_data = registry.get("agents") or []
        has_active = any(
            agent.get("status") in AGENT_ACTIVE_STATUSES
            for agent in agents_data
        )
        task_status = "ACTIVE" if has_active else registry.get("status", "INITIALIZED")

        conn.execute(
            """
            INSERT INTO tasks(task_id, workspace, workspace_base, description, status, priority, client_cwd,
                              created_at, updated_at, current_phase_index)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(task_id) DO UPDATE SET
              workspace=excluded.workspace,
              workspace_base=excluded.workspace_base,
              description=COALESCE(excluded.description, tasks.description),
              status=excluded.status,
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
                task_status,
                registry.get("priority") or "P2",
                registry.get("client_cwd") or "",
                created_at,
                updated_at,
                int(registry.get("current_phase_index") or 0),
            ),
        )

        # Phases (metadata with deliverables and success criteria)
        phases = registry.get("phases") or []
        for idx, phase in enumerate(phases):
            # Serialize deliverables and success_criteria as JSON if they exist
            deliverables = phase.get("deliverables")
            success_criteria = phase.get("success_criteria")
            deliverables_json = json.dumps(deliverables) if deliverables else None
            success_criteria_json = json.dumps(success_criteria) if success_criteria else None

            conn.execute(
                """
                INSERT INTO phases(task_id, phase_index, phase_id, name, description, deliverables, success_criteria, status, created_at, started_at, completed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id, phase_index) DO UPDATE SET
                  phase_id=excluded.phase_id,
                  name=excluded.name,
                  description=excluded.description,
                  deliverables=excluded.deliverables,
                  success_criteria=excluded.success_criteria,
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
                    phase.get("description"),
                    deliverables_json,
                    success_criteria_json,
                    phase.get("status"),
                    _parse_dt(phase.get("created_at")),
                    _parse_dt(phase.get("started_at")),
                    _parse_dt(phase.get("completed_at")),
                ),
            )

        # Agents: registry metadata + JSONL-derived latest status/progress.
        for agent in agents_data:
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

            # Extract model and PIDs if available
            model = agent.get("model") or "sonnet"
            claude_pid = agent.get("claude_pid")
            cursor_pid = agent.get("cursor_pid")
            tracked_files_json = json.dumps(tracked) if tracked else None

            conn.execute(
                """
                INSERT INTO agents(agent_id, task_id, type, model, tmux_session, parent, depth, phase_index,
                                   claude_pid, cursor_pid, tracked_files,
                                   started_at, completed_at, status, progress, last_update, prompt_preview)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(agent_id) DO UPDATE SET
                  task_id=excluded.task_id,
                  type=excluded.type,
                  model=excluded.model,
                  tmux_session=excluded.tmux_session,
                  parent=excluded.parent,
                  depth=excluded.depth,
                  phase_index=excluded.phase_index,
                  claude_pid=excluded.claude_pid,
                  cursor_pid=excluded.cursor_pid,
                  tracked_files=excluded.tracked_files,
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
                    model,
                    agent.get("tmux_session") or "",
                    agent.get("parent") or "orchestrator",
                    int(agent.get("depth") or 1),
                    int(agent.get("phase_index") or 0),
                    claude_pid,
                    cursor_pid,
                    tracked_files_json,
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


# Additional helper functions for reviews, findings, and handovers

def create_review(
    *,
    workspace_base: str,
    task_id: str,
    phase_index: int,
    review_id: str
) -> bool:
    """Create a new review record."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO reviews(review_id, task_id, phase_index, status, created_at)
            VALUES (?, ?, ?, 'in_progress', ?)
            """,
            (review_id, task_id, phase_index, now)
        )
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def update_review(
    *,
    workspace_base: str,
    review_id: str,
    status: Optional[str] = None,
    verdict: Optional[str] = None,
    reviewer_notes: Optional[str] = None
) -> bool:
    """Update review status and verdict."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        updates = []
        params = []

        if status:
            updates.append("status = ?")
            params.append(status)

        if verdict:
            updates.append("verdict = ?")
            params.append(verdict)

        if reviewer_notes:
            updates.append("reviewer_notes = ?")
            params.append(reviewer_notes)

        if status in ("completed", "aborted"):
            updates.append("completed_at = ?")
            params.append(datetime.now().isoformat())

        if not updates:
            return False

        params.append(review_id)
        result = conn.execute(
            f"UPDATE reviews SET {', '.join(updates)} WHERE review_id = ?",
            params
        )

        return result.rowcount > 0
    finally:
        conn.close()


def abort_review(
    *,
    workspace_base: str,
    review_id: str,
    reason: str = "Review aborted"
) -> bool:
    """Abort a review and record the reason.

    Sets status to 'aborted', records completion time, and stores reason in reviewer_notes.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()
        result = conn.execute(
            """
            UPDATE reviews
            SET status = 'aborted',
                completed_at = ?,
                reviewer_notes = COALESCE(reviewer_notes || ' | ', '') || ?
            WHERE review_id = ?
            """,
            (now, f"ABORTED: {reason}", review_id)
        )
        return result.rowcount > 0
    finally:
        conn.close()


def get_agent_findings(
    *,
    workspace_base: str,
    task_id: str,
    agent_id: Optional[str] = None,
    finding_type: Optional[str] = None,
    severity: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 50
) -> List[Dict[str, Any]]:
    """Get agent findings with optional filters."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        query = "SELECT * FROM agent_findings WHERE task_id = ?"
        params = [task_id]

        if agent_id:
            query += " AND agent_id = ?"
            params.append(agent_id)

        if finding_type:
            query += " AND finding_type = ?"
            params.append(finding_type)

        if severity:
            query += " AND severity = ?"
            params.append(severity)

        if since:
            query += " AND created_at > ?"
            params.append(since)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()

        findings = []
        for row in rows:
            finding = dict(row)
            # Parse JSON data field
            if finding.get("data"):
                try:
                    finding["data"] = json.loads(finding["data"])
                except Exception:
                    pass
            findings.append(finding)

        return findings
    finally:
        conn.close()


def create_handover(
    *,
    workspace_base: str,
    task_id: str,
    from_phase_index: int,
    to_phase_index: int,
    summary: str,
    key_findings: Optional[List[str]] = None,
    blockers: Optional[List[str]] = None,
    recommendations: Optional[List[str]] = None
) -> int:
    """Create a handover document for phase transition."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()

        cursor = conn.execute(
            """
            INSERT INTO handovers(
                task_id, from_phase_index, to_phase_index, summary,
                key_findings, blockers, recommendations, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                from_phase_index,
                to_phase_index,
                summary,
                json.dumps(key_findings) if key_findings else None,
                json.dumps(blockers) if blockers else None,
                json.dumps(recommendations) if recommendations else None,
                now
            )
        )

        return cursor.lastrowid
    finally:
        conn.close()


def get_latest_handover(
    *,
    workspace_base: str,
    task_id: str,
    to_phase_index: int
) -> Optional[Dict[str, Any]]:
    """Get the latest handover document for a phase."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT * FROM handovers
            WHERE task_id = ? AND to_phase_index = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (task_id, to_phase_index)
        ).fetchone()

        if not row:
            return None

        handover = dict(row)

        # Parse JSON fields
        for field in ("key_findings", "blockers", "recommendations"):
            if handover.get(field):
                try:
                    handover[field] = json.loads(handover[field])
                except Exception:
                    handover[field] = []

        return handover
    finally:
        conn.close()


# ============================================================================
# BACKWARD COMPATIBILITY FUNCTIONS FROM ORIGINAL state_db.py
# ============================================================================

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


# Debug/inspection utilities

def inspect_database(workspace_base: str) -> Dict[str, Any]:
    """Inspect database state for debugging."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        tables = {}

        # Get all table names
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        table_names = [row[0] for row in cursor.fetchall()]

        for table_name in table_names:
            # Get row count
            count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

            # Get columns
            cursor = conn.execute(f"PRAGMA table_info({table_name})")
            columns = [row[1] for row in cursor.fetchall()]

            tables[table_name] = {
                "count": count,
                "columns": columns
            }

        # Get active counts
        counts = get_active_counts(workspace_base=workspace_base)

        return {
            "database": db_path,
            "tables": tables,
            "active_counts": counts
        }
    finally:
        conn.close()


# ============================================================================
# DASHBOARD API WRAPPER FUNCTIONS
# ============================================================================

def get_all_tasks_for_dashboard(*, workspace_base: str) -> List[Dict]:
    """Wrapper for dashboard API - returns all tasks with agent counts."""
    return get_all_tasks(workspace_base=workspace_base)


def get_task_by_id_for_dashboard(*, workspace_base: str, task_id: str) -> Optional[Dict]:
    """Get single task by ID for dashboard."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def get_agents_for_task(*, workspace_base: str, task_id: str) -> List[Dict]:
    """Get all agents for a specific task."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM agents WHERE task_id=? ORDER BY started_at DESC",
            (task_id,)
        ).fetchall()
        result = []
        for row in rows:
            agent = dict(row)
            # Parse tracked_files JSON field
            if agent.get('tracked_files'):
                try:
                    agent['tracked_files'] = json.loads(agent['tracked_files'])
                except Exception:
                    agent['tracked_files'] = {}
            result.append(agent)
        return result
    finally:
        conn.close()


def get_agent_by_id(*, workspace_base: str, task_id: str, agent_id: str) -> Optional[Dict[str, Any]]:
    """Get a single agent by ID with all fields including tracked_files JSON."""
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            'SELECT * FROM agents WHERE task_id=? AND agent_id=?',
            (task_id, agent_id)
        ).fetchone()
        if not row:
            return None
        agent = dict(row)
        # Parse tracked_files JSON field
        if agent.get('tracked_files'):
            try:
                agent['tracked_files'] = json.loads(agent['tracked_files'])
            except Exception:
                agent['tracked_files'] = {}
        return agent
    finally:
        conn.close()


# ============================================================================
# FULL SQLITE MIGRATION - ATOMIC OPERATIONS (Jan 2026)
# These functions replace LockedRegistryFile JSON operations with SQLite
# ============================================================================


def check_can_spawn_agent(
    *,
    workspace_base: str,
    task_id: str,
    agent_type: str,
    max_concurrent: int = 20,
    max_agents: int = 50
) -> Tuple[bool, Optional[str], Optional[Dict]]:
    """
    Check if a new agent can be spawned (atomic check without lock contention).

    Returns:
        Tuple of (can_spawn, error_message, existing_agent_if_duplicate)
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        # Check active count
        active_count = conn.execute(
            "SELECT COUNT(*) FROM agents WHERE task_id=? AND status IN ('running', 'working', 'blocked', 'reviewing')",
            (task_id,)
        ).fetchone()[0]

        if active_count >= max_concurrent:
            return False, f"Too many active agents ({active_count}/{max_concurrent})", None

        # Check total agents
        total_count = conn.execute(
            "SELECT COUNT(*) FROM agents WHERE task_id=?",
            (task_id,)
        ).fetchone()[0]

        if total_count >= max_agents:
            return False, f"Max agents reached ({total_count}/{max_agents})", None

        # Check for duplicate agent type (deduplication)
        existing = conn.execute(
            "SELECT agent_id, status FROM agents WHERE task_id=? AND type=? AND status IN ('running', 'working', 'blocked', 'reviewing')",
            (task_id, agent_type)
        ).fetchone()

        if existing:
            return False, f"Agent of type '{agent_type}' already running", {
                "agent_id": existing[0],
                "status": existing[1]
            }

        return True, None, None
    finally:
        conn.close()


def deploy_agent_atomic(
    *,
    workspace_base: str,
    task_id: str,
    agent_id: str,
    agent_type: str,
    model: str,
    parent: str,
    depth: int,
    phase_index: int,
    tmux_session: str,
    prompt_preview: str = ""
) -> Dict[str, Any]:
    """
    Atomically deploy an agent to SQLite (replaces nested LockedRegistryFile pattern).

    This function:
    1. Inserts agent record
    2. Records hierarchy (if parent is not orchestrator)
    3. Updates task timestamp
    4. All in a single transaction

    Returns:
        Dict with success status and any error
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()

        # Use BEGIN IMMEDIATE for exclusive write lock from start
        conn.execute("BEGIN IMMEDIATE")

        try:
            # Insert agent record
            conn.execute(
                """
                INSERT INTO agents (
                    agent_id, task_id, type, model, tmux_session, parent, depth,
                    phase_index, status, progress, started_at, last_update, prompt_preview
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'running', 0, ?, ?, ?)
                """,
                (agent_id, task_id, agent_type, model, tmux_session, parent, depth,
                 phase_index, now, now, prompt_preview[:200] if prompt_preview else "")
            )

            # Record hierarchy if has parent
            if parent and parent != "orchestrator":
                conn.execute(
                    """
                    INSERT OR IGNORE INTO agent_hierarchy (task_id, parent_agent_id, child_agent_id, spawned_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (task_id, parent, agent_id, now)
                )

            # Update task timestamp
            conn.execute(
                "UPDATE tasks SET updated_at=? WHERE task_id=?",
                (now, task_id)
            )

            conn.execute("COMMIT")

            return {"success": True, "agent_id": agent_id}

        except Exception as e:
            conn.execute("ROLLBACK")
            return {"success": False, "error": str(e)}

    finally:
        conn.close()


def get_task_config(*, workspace_base: str, task_id: str) -> Dict[str, Any]:
    """
    Get task configuration from SQLite.

    Returns config dict with defaults if not found.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM task_config WHERE task_id=?",
            (task_id,)
        ).fetchone()

        if row:
            config = dict(row)
            # Parse JSON fields
            for field in ['project_context', 'constraints', 'relevant_files',
                         'conversation_history', 'expected_deliverables', 'success_criteria']:
                if config.get(field):
                    try:
                        config[field] = json.loads(config[field])
                    except Exception:
                        pass
            return config

        # Return defaults
        return {
            "task_id": task_id,
            "max_agents": 50,
            "max_concurrent": 20,
            "max_depth": 5,
            "project_context": {},
            "constraints": [],
            "relevant_files": [],
            "conversation_history": [],
            "background_context": "",
            "expected_deliverables": [],
            "success_criteria": []
        }
    finally:
        conn.close()


def save_task_config(
    *,
    workspace_base: str,
    task_id: str,
    max_agents: int = 50,
    max_concurrent: int = 20,
    max_depth: int = 5,
    project_context: Optional[Dict] = None,
    constraints: Optional[List] = None,
    relevant_files: Optional[List] = None,
    conversation_history: Optional[List] = None,
    background_context: Optional[str] = None,
    expected_deliverables: Optional[List] = None,
    success_criteria: Optional[List] = None
) -> bool:
    """
    Save task configuration to SQLite.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO task_config (
                task_id, max_agents, max_concurrent, max_depth,
                project_context, constraints, relevant_files,
                conversation_history, background_context,
                expected_deliverables, success_criteria
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id, max_agents, max_concurrent, max_depth,
                json.dumps(project_context) if project_context else None,
                json.dumps(constraints) if constraints else None,
                json.dumps(relevant_files) if relevant_files else None,
                json.dumps(conversation_history) if conversation_history else None,
                background_context,
                json.dumps(expected_deliverables) if expected_deliverables else None,
                json.dumps(success_criteria) if success_criteria else None
            )
        )
        return True
    except Exception:
        return False
    finally:
        conn.close()


def record_review_verdict(
    *,
    workspace_base: str,
    review_id: str,
    task_id: str,
    reviewer_agent_id: str,
    verdict: str,
    findings: List[Dict],
    reviewer_notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Record a reviewer's verdict in SQLite.

    Returns dict with verdict_id and whether all reviewers have submitted.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()

        conn.execute("BEGIN IMMEDIATE")

        try:
            # Insert verdict
            cursor = conn.execute(
                """
                INSERT INTO review_verdicts (
                    review_id, task_id, reviewer_agent_id, verdict,
                    findings, reviewer_notes, submitted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (review_id, task_id, reviewer_agent_id, verdict,
                 json.dumps(findings), reviewer_notes, now)
            )
            verdict_id = cursor.lastrowid

            # Mark reviewer agent as completed
            conn.execute(
                """
                UPDATE agents SET status='completed', completed_at=?, final_verdict=?
                WHERE agent_id=? AND task_id=?
                """,
                (now, verdict, reviewer_agent_id, task_id)
            )

            conn.execute("COMMIT")

            return {
                "success": True,
                "verdict_id": verdict_id,
                "submitted_at": now
            }

        except Exception as e:
            conn.execute("ROLLBACK")
            return {"success": False, "error": str(e)}

    finally:
        conn.close()


def check_review_complete(
    *,
    workspace_base: str,
    review_id: str
) -> Tuple[bool, Optional[str], List[Dict]]:
    """
    Check if all reviewers have submitted verdicts and determine final verdict.

    Returns:
        Tuple of (is_complete, final_verdict, all_verdicts)
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        # Get expected reviewer count
        review_row = conn.execute(
            "SELECT num_reviewers FROM reviews WHERE review_id=?",
            (review_id,)
        ).fetchone()

        if not review_row:
            return False, None, []

        num_expected = review_row[0] or 2  # Default to 2 reviewers

        # Get all submitted verdicts
        verdicts = conn.execute(
            "SELECT verdict, reviewer_agent_id, findings, reviewer_notes, submitted_at FROM review_verdicts WHERE review_id=?",
            (review_id,)
        ).fetchall()

        verdict_list = [dict(v) for v in verdicts]

        if len(verdicts) < num_expected:
            return False, None, verdict_list

        # Aggregate verdicts
        approve_count = sum(1 for v in verdicts if v[0] == 'approved')
        reject_count = sum(1 for v in verdicts if v[0] == 'rejected')

        # Majority wins, ties go to approved
        if approve_count >= reject_count:
            final_verdict = 'approved'
        else:
            final_verdict = 'rejected'

        return True, final_verdict, verdict_list

    finally:
        conn.close()


def finalize_review(
    *,
    workspace_base: str,
    task_id: str,
    review_id: str,
    phase_index: int,
    final_verdict: str,
    reviewer_notes: Optional[str] = None
) -> bool:
    """
    Finalize a review and update phase status accordingly.

    This is called after all reviewers have submitted verdicts.

    RACE CONDITION FIX: Uses atomic check-and-update to prevent double-finalization.
    Only updates if review is not already completed.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()

        conn.execute("BEGIN IMMEDIATE")

        try:
            # RACE CONDITION FIX: Check if already finalized before updating
            existing = conn.execute(
                "SELECT status FROM reviews WHERE review_id=?",
                (review_id,)
            ).fetchone()

            if existing and existing[0] == 'completed':
                # Already finalized by another concurrent call - not an error, just skip
                conn.execute("ROLLBACK")
                return True  # Still return True since finalization is done

            # Update review record (only if not already completed)
            result = conn.execute(
                """
                UPDATE reviews SET status='completed', verdict=?, completed_at=?, reviewer_notes=?
                WHERE review_id=? AND status != 'completed'
                """,
                (final_verdict, now, reviewer_notes, review_id)
            )

            # If no rows updated, another call already finalized
            if result.rowcount == 0:
                conn.execute("ROLLBACK")
                return True  # Still return True since finalization is done

            # Update phase status based on verdict
            new_phase_status = 'APPROVED' if final_verdict == 'approved' else 'REVISING'
            conn.execute(
                """
                UPDATE phases SET status=?, completed_at=?
                WHERE task_id=? AND phase_index=?
                """,
                (new_phase_status, now if final_verdict == 'approved' else None, task_id, phase_index)
            )

            # If approved and there's a next phase, activate it
            if final_verdict == 'approved':
                conn.execute(
                    """
                    UPDATE phases SET status='ACTIVE', started_at=?
                    WHERE task_id=? AND phase_index=? AND status='PENDING'
                    """,
                    (now, task_id, phase_index + 1)
                )

                # Update task's current phase index
                conn.execute(
                    """
                    UPDATE tasks SET current_phase_index=?, updated_at=?
                    WHERE task_id=?
                    """,
                    (phase_index + 1, now, task_id)
                )

            conn.execute("COMMIT")
            return True

        except Exception:
            conn.execute("ROLLBACK")
            return False

    finally:
        conn.close()


def record_critique(
    *,
    workspace_base: str,
    review_id: str,
    task_id: str,
    critique_agent_id: str,
    observations: List[Dict],
    summary: str,
    recommendations: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Record a critique submission in SQLite.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()

        cursor = conn.execute(
            """
            INSERT INTO critique_submissions (
                review_id, task_id, critique_agent_id,
                observations, summary, recommendations, submitted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (review_id, task_id, critique_agent_id,
             json.dumps(observations), summary,
             json.dumps(recommendations) if recommendations else None, now)
        )

        # Mark critique agent as completed
        conn.execute(
            """
            UPDATE agents SET status='completed', completed_at=?
            WHERE agent_id=? AND task_id=?
            """,
            (now, critique_agent_id, task_id)
        )

        return {
            "success": True,
            "critique_id": cursor.lastrowid,
            "submitted_at": now
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def get_review_verdicts(*, workspace_base: str, review_id: str) -> List[Dict]:
    """
    Get all verdicts for a review.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT verdict_id, reviewer_agent_id, verdict, findings, reviewer_notes, submitted_at
            FROM review_verdicts WHERE review_id=?
            ORDER BY submitted_at
            """,
            (review_id,)
        ).fetchall()

        result = []
        for row in rows:
            v = dict(row)
            if v.get('findings'):
                try:
                    v['findings'] = json.loads(v['findings'])
                except Exception:
                    pass
            result.append(v)
        return result
    finally:
        conn.close()


def get_reviews_for_task(*, workspace_base: str, task_id: str) -> List[Dict]:
    """
    Get all reviews for a task.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT review_id, task_id, phase_index, status, verdict, created_at,
                   completed_at, reviewer_notes, num_reviewers, reviewer_agent_ids,
                   critique_agent_id, phase_name
            FROM reviews WHERE task_id=?
            ORDER BY created_at DESC
            """,
            (task_id,)
        ).fetchall()

        result = []
        for row in rows:
            r = dict(row)
            # Parse JSON fields
            if r.get('reviewer_agent_ids'):
                try:
                    r['reviewer_agent_ids'] = json.loads(r['reviewer_agent_ids'])
                except Exception:
                    pass
            result.append(r)
        return result
    finally:
        conn.close()


def get_critique(*, workspace_base: str, review_id: str) -> Optional[Dict]:
    """
    Get critique submission for a review.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT * FROM critique_submissions WHERE review_id=?
            """,
            (review_id,)
        ).fetchone()

        if not row:
            return None

        result = dict(row)
        for field in ['observations', 'recommendations']:
            if result.get(field):
                try:
                    result[field] = json.loads(result[field])
                except Exception:
                    pass
        return result
    finally:
        conn.close()


def create_review_for_phase(
    *,
    workspace_base: str,
    task_id: str,
    review_id: str,
    phase_index: int,
    phase_name: str,
    num_reviewers: int = 2,
    auto_spawned: bool = True
) -> bool:
    """
    Create a review record for a phase (called when spawning reviewers).
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()

        conn.execute(
            """
            INSERT INTO reviews (
                review_id, task_id, phase_index, phase_name,
                status, num_reviewers, auto_spawned, created_at
            ) VALUES (?, ?, ?, ?, 'in_progress', ?, ?, ?)
            """,
            (review_id, task_id, phase_index, phase_name, num_reviewers, 1 if auto_spawned else 0, now)
        )

        # Update phase status to UNDER_REVIEW
        conn.execute(
            """
            UPDATE phases SET status='UNDER_REVIEW'
            WHERE task_id=? AND phase_index=?
            """,
            (task_id, phase_index)
        )

        return True
    except Exception:
        return False
    finally:
        conn.close()


def get_existing_agent_by_type(
    *,
    workspace_base: str,
    task_id: str,
    agent_type: str
) -> Optional[Dict]:
    """
    Find an existing agent of a given type that is still active.
    Used for deduplication checks.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT agent_id, type, status, started_at
            FROM agents
            WHERE task_id=? AND type=? AND status IN ('running', 'working', 'blocked', 'reviewing')
            LIMIT 1
            """,
            (task_id, agent_type)
        ).fetchone()

        return dict(row) if row else None
    finally:
        conn.close()


def get_review(
    *,
    workspace_base: str,
    review_id: str
) -> Optional[Dict]:
    """
    Get a review record by review_id.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT review_id, task_id, phase_index, status, verdict,
                   reviewer_agent_ids, critique_agent_id, reviewer_notes,
                   created_at, completed_at
            FROM reviews
            WHERE review_id=?
            """,
            (review_id,)
        ).fetchone()

        if not row:
            return None

        result = dict(row)
        # Parse JSON fields
        if result.get('reviewer_agent_ids'):
            try:
                result['reviewer_agent_ids'] = json.loads(result['reviewer_agent_ids'])
            except:
                result['reviewer_agent_ids'] = []

        return result
    finally:
        conn.close()


def update_agent_status(
    *,
    workspace_base: str,
    task_id: str,
    agent_id: str,
    new_status: str
) -> bool:
    """
    Update an agent's status. Used to mark agents as completed, failed, etc.
    Also updates counts atomically.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()

        # Get current status first
        row = conn.execute(
            "SELECT status FROM agents WHERE task_id=? AND agent_id=?",
            (task_id, agent_id)
        ).fetchone()

        if not row:
            return False

        old_status = row['status']

        # Only update if status is actually changing
        if old_status == new_status:
            return True

        # Determine if this is a terminal status
        terminal_statuses = {'completed', 'failed', 'error', 'terminated', 'killed'}
        active_statuses = {'running', 'working', 'blocked', 'reviewing'}

        # Update the agent
        if new_status in terminal_statuses:
            conn.execute(
                """
                UPDATE agents
                SET status=?, completed_at=?
                WHERE task_id=? AND agent_id=?
                """,
                (new_status, now, task_id, agent_id)
            )

            # Update task counts if transitioning from active to terminal
            if old_status in active_statuses:
                conn.execute(
                    """
                    UPDATE tasks
                    SET active_count = MAX(0, active_count - 1),
                        completed_count = completed_count + 1
                    WHERE task_id=?
                    """,
                    (task_id,)
                )
        else:
            conn.execute(
                """
                UPDATE agents
                SET status=?
                WHERE task_id=? AND agent_id=?
                """,
                (new_status, task_id, agent_id)
            )

        conn.commit()
        return True
    except Exception as e:
        logger.error(f"update_agent_status error: {e}")
        return False
    finally:
        conn.close()


def claim_phase_for_review(
    *,
    workspace_base: str,
    task_id: str,
    phase_index: int
) -> bool:
    """
    ATOMIC: Claim a phase for review by transitioning AWAITING_REVIEW -> UNDER_REVIEW.

    This prevents race conditions where multiple threads try to spawn reviewers.
    Returns True ONLY if this call successfully transitioned the phase.
    Returns False if phase was already claimed or not in AWAITING_REVIEW.

    MUST be called before create_review_record to prevent duplicate reviews.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()

        # Atomic check-and-update: only succeeds if status is AWAITING_REVIEW
        result = conn.execute(
            """
            UPDATE phases
            SET status = 'UNDER_REVIEW', started_at = ?
            WHERE task_id = ? AND phase_index = ? AND status = 'AWAITING_REVIEW'
            """,
            (now, task_id, phase_index)
        )
        conn.commit()

        # rowcount > 0 means WE claimed it, rowcount = 0 means someone else did
        claimed = result.rowcount > 0
        if claimed:
            logger.info(f"[CLAIM-PHASE] Successfully claimed phase {phase_index} for review (task={task_id})")
        else:
            logger.info(f"[CLAIM-PHASE] Phase {phase_index} already claimed or not awaiting review (task={task_id})")

        return claimed
    except Exception as e:
        logger.error(f"claim_phase_for_review error: {e}")
        return False
    finally:
        conn.close()


def create_review_record(
    *,
    workspace_base: str,
    task_id: str,
    review_id: str,
    phase_index: int,
    num_reviewers: int = 2,
    reviewer_agent_ids: Optional[List[str]] = None
) -> Dict:
    """
    Create a new review record in SQLite.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()
        reviewer_ids_json = json.dumps(reviewer_agent_ids or [])

        conn.execute(
            """
            INSERT INTO reviews (review_id, task_id, phase_index, status, num_reviewers, reviewer_agent_ids, created_at)
            VALUES (?, ?, ?, 'in_progress', ?, ?, ?)
            """,
            (review_id, task_id, phase_index, num_reviewers, reviewer_ids_json, now)
        )
        conn.commit()

        return {"success": True, "review_id": review_id}
    except Exception as e:
        logger.error(f"create_review_record error: {e}")
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def add_reviewer_to_review(
    *,
    workspace_base: str,
    review_id: str,
    agent_id: str
) -> bool:
    """
    Add a reviewer agent ID to an existing review.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        # Get current reviewer list
        row = conn.execute(
            "SELECT reviewer_agent_ids FROM reviews WHERE review_id=?",
            (review_id,)
        ).fetchone()

        if not row:
            return False

        current_ids = []
        if row['reviewer_agent_ids']:
            try:
                current_ids = json.loads(row['reviewer_agent_ids'])
            except:
                current_ids = []

        if agent_id not in current_ids:
            current_ids.append(agent_id)
            conn.execute(
                "UPDATE reviews SET reviewer_agent_ids=? WHERE review_id=?",
                (json.dumps(current_ids), review_id)
            )
            conn.commit()

        return True
    except Exception as e:
        logger.error(f"add_reviewer_to_review error: {e}")
        return False
    finally:
        conn.close()


def get_agent(
    *,
    workspace_base: str,
    task_id: str,
    agent_id: str
) -> Optional[Dict]:
    """
    Get a single agent's data from SQLite.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT agent_id, task_id, type, model, status, phase_index,
                   parent, depth, tmux_session, started_at, completed_at, progress
            FROM agents
            WHERE task_id=? AND agent_id=?
            """,
            (task_id, agent_id)
        ).fetchone()

        if not row:
            return None

        result = dict(row)
        # Normalize field names
        result['id'] = result.pop('agent_id', None)
        return result
    finally:
        conn.close()


def get_phase(
    *,
    workspace_base: str,
    task_id: str,
    phase_index: int
) -> Optional[Dict]:
    """
    Get a single phase's data from SQLite.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT phase_index, name, description, status, deliverables,
                   success_criteria, started_at, completed_at
            FROM phases
            WHERE task_id=? AND phase_index=?
            """,
            (task_id, phase_index)
        ).fetchone()

        if not row:
            return None

        result = dict(row)
        # Parse JSON fields
        for json_field in ['deliverables', 'success_criteria']:
            if result.get(json_field):
                try:
                    result[json_field] = json.loads(result[json_field])
                except:
                    result[json_field] = []

        return result
    finally:
        conn.close()


def get_active_agent_count(
    *,
    workspace_base: str,
    task_id: str
) -> int:
    """
    Get the count of active agents for a task.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) as count
            FROM agents
            WHERE task_id=? AND status IN ('running', 'working', 'blocked', 'reviewing')
            """,
            (task_id,)
        ).fetchone()

        return row['count'] if row else 0
    finally:
        conn.close()


def get_total_agent_count(
    *,
    workspace_base: str,
    task_id: str
) -> int:
    """
    Get the total count of agents for a task.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) as count FROM agents WHERE task_id=?",
            (task_id,)
        ).fetchone()

        return row['count'] if row else 0
    finally:
        conn.close()


def get_all_active_agents(
    *,
    workspace_base: str
) -> List[Dict]:
    """
    Get all agents across all tasks that are in active status.
    Used by global cleanup to find dead tmux sessions.

    Returns:
        List of agent dicts with agent_id, task_id, status, tmux_session
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        active_statuses = ('running', 'working', 'blocked', 'reviewing')
        rows = conn.execute(
            """
            SELECT agent_id, task_id, status, tmux_session, type
            FROM agents
            WHERE status IN (?, ?, ?, ?)
            """,
            active_statuses
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        conn.close()


def mark_agents_as_failed_batch(
    *,
    workspace_base: str,
    agent_ids: List[str],
    reason: str
) -> int:
    """
    Mark multiple agents as failed in a single transaction.
    Used by global cleanup for dead tmux sessions.

    Returns:
        Number of agents updated
    """
    if not agent_ids:
        return 0

    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        now = datetime.now().isoformat()
        placeholders = ','.join('?' * len(agent_ids))
        result = conn.execute(
            f"""
            UPDATE agents
            SET status = 'failed',
                completed_at = ?,
                last_update = ?
            WHERE agent_id IN ({placeholders})
            """,
            (now, now, *agent_ids)
        )
        return result.rowcount
    finally:
        conn.close()


def set_critique_agent_for_review(
    *,
    workspace_base: str,
    review_id: str,
    critique_agent_id: str
) -> bool:
    """
    Set the critique agent ID for a review.
    """
    db_path = ensure_db(workspace_base)
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE reviews SET critique_agent_id=? WHERE review_id=?",
            (critique_agent_id, review_id)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"set_critique_agent_for_review error: {e}")
        return False
    finally:
        conn.close()