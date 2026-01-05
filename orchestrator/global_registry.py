"""
Global SQLite Registry for Claude Orchestrator.

Tracks all known project workspaces across the system in a single location:
~/.claude-orchestrator/global_registry.sqlite3

This solves the cross-project discovery problem:
- When MCP server runs from any project, it registers that project's workspace
- Dashboard queries this global registry to find ALL workspaces
- Then queries each workspace's local state.sqlite3 for task/agent data

Benefits over JSON:
- WAL mode handles concurrent writes from multiple Claude instances
- No file locking bugs
- ACID transactions
- Fast reads even with many projects
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)

# Global registry location - always in user's home directory
GLOBAL_REGISTRY_DIR = os.path.expanduser("~/.claude-orchestrator")
GLOBAL_REGISTRY_PATH = os.path.join(GLOBAL_REGISTRY_DIR, "global_registry.sqlite3")


def _ensure_global_registry_dir():
    """Ensure the global registry directory exists."""
    os.makedirs(GLOBAL_REGISTRY_DIR, exist_ok=True)


def _connect() -> sqlite3.Connection:
    """Connect to the global registry database."""
    _ensure_global_registry_dir()
    conn = sqlite3.connect(GLOBAL_REGISTRY_PATH, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    """Initialize the global registry schema."""
    conn.executescript("""
        -- Known project workspaces
        CREATE TABLE IF NOT EXISTS known_workspaces (
            workspace_base TEXT PRIMARY KEY,
            project_name TEXT,
            client_cwd TEXT,
            first_seen TEXT,
            last_accessed TEXT,
            task_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_workspaces_last_accessed
            ON known_workspaces(last_accessed DESC);
        CREATE INDEX IF NOT EXISTS idx_workspaces_active
            ON known_workspaces(is_active);

        -- Global task index (lightweight reference, details in local state.sqlite3)
        CREATE TABLE IF NOT EXISTS task_index (
            task_id TEXT PRIMARY KEY,
            workspace_base TEXT NOT NULL,
            description TEXT,
            status TEXT,
            priority TEXT,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (workspace_base) REFERENCES known_workspaces(workspace_base)
        );

        CREATE INDEX IF NOT EXISTS idx_task_workspace ON task_index(workspace_base);
        CREATE INDEX IF NOT EXISTS idx_task_status ON task_index(status);
        CREATE INDEX IF NOT EXISTS idx_task_created ON task_index(created_at DESC);

        -- Global agent counts (denormalized for fast dashboard queries)
        CREATE TABLE IF NOT EXISTS global_counts (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            total_tasks INTEGER DEFAULT 0,
            active_tasks INTEGER DEFAULT 0,
            total_agents INTEGER DEFAULT 0,
            active_agents INTEGER DEFAULT 0,
            last_updated TEXT
        );

        -- Initialize global counts if not exists
        INSERT OR IGNORE INTO global_counts (id, total_tasks, active_tasks, total_agents, active_agents, last_updated)
        VALUES (1, 0, 0, 0, 0, datetime('now'));
    """)


def ensure_global_registry() -> str:
    """Ensure the global registry exists and is initialized."""
    conn = _connect()
    try:
        _init_db(conn)
        return GLOBAL_REGISTRY_PATH
    finally:
        conn.close()


# ============================================================================
# WORKSPACE REGISTRATION
# ============================================================================

def register_workspace(
    workspace_base: str,
    client_cwd: Optional[str] = None,
    project_name: Optional[str] = None
) -> bool:
    """
    Register a project workspace in the global registry.

    Called by the MCP server when:
    - A task is created with client_cwd
    - The server starts in a new project directory

    Args:
        workspace_base: The .agent-workspace directory path
        client_cwd: The client's working directory (project root)
        project_name: Optional friendly name for the project

    Returns:
        True if registration succeeded
    """
    conn = _connect()
    try:
        _init_db(conn)

        now = datetime.now().isoformat()
        workspace_base = os.path.abspath(workspace_base)

        # Derive project name from client_cwd if not provided
        if not project_name and client_cwd:
            project_name = os.path.basename(client_cwd)
        elif not project_name:
            project_name = os.path.basename(os.path.dirname(workspace_base))

        conn.execute("""
            INSERT INTO known_workspaces (workspace_base, project_name, client_cwd, first_seen, last_accessed, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(workspace_base) DO UPDATE SET
                project_name = COALESCE(excluded.project_name, known_workspaces.project_name),
                client_cwd = COALESCE(excluded.client_cwd, known_workspaces.client_cwd),
                last_accessed = excluded.last_accessed,
                is_active = 1
        """, (workspace_base, project_name, client_cwd, now, now))

        logger.info(f"[GLOBAL_REGISTRY] Registered workspace: {workspace_base} (project: {project_name})")
        return True
    except Exception as e:
        logger.error(f"[GLOBAL_REGISTRY] Failed to register workspace: {e}")
        return False
    finally:
        conn.close()


def get_all_workspaces(include_inactive: bool = False) -> List[Dict[str, Any]]:
    """
    Get all known workspace bases.

    Returns list of workspace info dicts with:
    - workspace_base: Path to .agent-workspace
    - project_name: Friendly project name
    - client_cwd: Original client working directory
    - first_seen: When first registered
    - last_accessed: When last used
    - task_count: Number of tasks in this workspace
    - is_active: Whether workspace still exists
    """
    conn = _connect()
    try:
        _init_db(conn)

        query = "SELECT * FROM known_workspaces"
        if not include_inactive:
            query += " WHERE is_active = 1"
        query += " ORDER BY last_accessed DESC"

        rows = conn.execute(query).fetchall()

        workspaces = []
        for row in rows:
            ws = dict(row)
            # Verify workspace still exists
            if os.path.isdir(ws["workspace_base"]):
                workspaces.append(ws)
            elif not include_inactive:
                # Mark as inactive if directory doesn't exist
                conn.execute(
                    "UPDATE known_workspaces SET is_active = 0 WHERE workspace_base = ?",
                    (ws["workspace_base"],)
                )

        return workspaces
    finally:
        conn.close()


def get_workspace_bases() -> List[str]:
    """Get list of all active workspace base paths (for iteration)."""
    workspaces = get_all_workspaces(include_inactive=False)
    return [ws["workspace_base"] for ws in workspaces]


# ============================================================================
# TASK INDEX OPERATIONS
# ============================================================================

def register_task(
    task_id: str,
    workspace_base: str,
    description: str = "",
    status: str = "INITIALIZED",
    priority: str = "P2",
    created_at: Optional[str] = None
) -> bool:
    """
    Register a task in the global index.

    This creates a lightweight reference - full task data lives in local state.sqlite3.
    """
    conn = _connect()
    try:
        _init_db(conn)

        now = datetime.now().isoformat()
        workspace_base = os.path.abspath(workspace_base)

        # Use provided created_at or default to now
        task_created_at = created_at or now

        # Ensure workspace is registered
        register_workspace(workspace_base)

        conn.execute("""
            INSERT INTO task_index (task_id, workspace_base, description, status, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                description = COALESCE(excluded.description, task_index.description),
                status = excluded.status,
                priority = excluded.priority,
                updated_at = excluded.updated_at,
                created_at = COALESCE(task_index.created_at, excluded.created_at)
        """, (task_id, workspace_base, description, status, priority, task_created_at, now))

        # Update workspace task count
        conn.execute("""
            UPDATE known_workspaces
            SET task_count = (SELECT COUNT(*) FROM task_index WHERE workspace_base = ?),
                last_accessed = ?
            WHERE workspace_base = ?
        """, (workspace_base, now, workspace_base))

        logger.info(f"[GLOBAL_REGISTRY] Registered task: {task_id} in {workspace_base}")
        return True
    except Exception as e:
        logger.error(f"[GLOBAL_REGISTRY] Failed to register task: {e}")
        return False
    finally:
        conn.close()


def update_task_status(task_id: str, status: str) -> bool:
    """Update task status in global index."""
    conn = _connect()
    try:
        _init_db(conn)

        now = datetime.now().isoformat()
        result = conn.execute("""
            UPDATE task_index
            SET status = ?, updated_at = ?
            WHERE task_id = ?
        """, (status, now, task_id))

        return result.rowcount > 0
    finally:
        conn.close()


def find_task_workspace(task_id: str) -> Optional[str]:
    """
    Find the workspace base for a given task ID.

    Returns the workspace_base path or None if not found.
    """
    conn = _connect()
    try:
        _init_db(conn)

        row = conn.execute(
            "SELECT workspace_base FROM task_index WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        if row:
            workspace_base = row["workspace_base"]
            # Return full task workspace path
            task_workspace = os.path.join(workspace_base, task_id)
            if os.path.isdir(task_workspace):
                return task_workspace
            # Fallback: maybe task is directly in workspace_base
            if os.path.isdir(workspace_base):
                return workspace_base

        return None
    finally:
        conn.close()


def get_all_tasks(
    limit: int = 100,
    offset: int = 0,
    status_filter: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    project_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get all tasks from global index with optional filters.

    Args:
        limit: Max number of tasks to return
        offset: Pagination offset
        status_filter: Filter by exact status match
        since: Filter tasks created on or after this date (ISO format)
        until: Filter tasks created on or before this date (ISO format)
        project_filter: Filter by project name (partial match, case-insensitive)

    Returns lightweight task references. For full details, query local state.sqlite3.
    """
    conn = _connect()
    try:
        _init_db(conn)

        query = """
            SELECT t.*, w.project_name, w.client_cwd
            FROM task_index t
            JOIN known_workspaces w ON t.workspace_base = w.workspace_base
            WHERE w.is_active = 1
        """
        params = []

        if status_filter:
            query += " AND t.status = ?"
            params.append(status_filter)

        if since:
            # Normalize date to start of day if only date provided
            since_normalized = since if 'T' in since else f"{since}T00:00:00"
            query += " AND t.created_at >= ?"
            params.append(since_normalized)

        if until:
            # Normalize date to end of day if only date provided
            until_normalized = until if 'T' in until else f"{until}T23:59:59"
            query += " AND t.created_at <= ?"
            params.append(until_normalized)

        if project_filter:
            query += " AND LOWER(w.project_name) LIKE LOWER(?)"
            params.append(f"%{project_filter}%")

        query += " ORDER BY t.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


# ============================================================================
# GLOBAL COUNTS (for fast dashboard stats)
# ============================================================================

def update_global_counts(
    total_tasks: int,
    active_tasks: int,
    total_agents: int,
    active_agents: int
) -> None:
    """Update global counts (called periodically or on significant changes)."""
    conn = _connect()
    try:
        _init_db(conn)

        now = datetime.now().isoformat()
        conn.execute("""
            UPDATE global_counts
            SET total_tasks = ?,
                active_tasks = ?,
                total_agents = ?,
                active_agents = ?,
                last_updated = ?
            WHERE id = 1
        """, (total_tasks, active_tasks, total_agents, active_agents, now))
    finally:
        conn.close()


def get_global_counts() -> Dict[str, int]:
    """Get cached global counts."""
    conn = _connect()
    try:
        _init_db(conn)

        row = conn.execute("SELECT * FROM global_counts WHERE id = 1").fetchone()
        if row:
            return {
                "total_tasks": row["total_tasks"],
                "active_tasks": row["active_tasks"],
                "total_agents": row["total_agents"],
                "active_agents": row["active_agents"],
                "last_updated": row["last_updated"]
            }
        return {
            "total_tasks": 0,
            "active_tasks": 0,
            "total_agents": 0,
            "active_agents": 0,
            "last_updated": None
        }
    finally:
        conn.close()


def recompute_global_counts() -> Dict[str, int]:
    """
    Recompute global counts by aggregating from all workspace state.sqlite3 DBs.

    This is more accurate but slower - use sparingly.
    """
    from . import state_db

    total_tasks = 0
    active_tasks = 0
    total_agents = 0
    active_agents = 0

    for workspace_base in get_workspace_bases():
        try:
            counts = state_db.get_global_counts(workspace_base=workspace_base)
            total_tasks += counts.get("total_tasks", 0)
            active_tasks += counts.get("active_tasks", 0)
            total_agents += counts.get("total_agents", 0)
            active_agents += counts.get("active_agents", 0)
        except Exception as e:
            logger.warning(f"[GLOBAL_REGISTRY] Failed to get counts from {workspace_base}: {e}")
            continue

    # Update cached counts
    update_global_counts(total_tasks, active_tasks, total_agents, active_agents)

    return {
        "total_tasks": total_tasks,
        "active_tasks": active_tasks,
        "total_agents": total_agents,
        "active_agents": active_agents
    }


# ============================================================================
# DISCOVERY & MIGRATION
# ============================================================================

def discover_existing_workspaces() -> int:
    """
    Scan common locations for existing .agent-workspace directories and register them.

    Useful for initial migration or recovering from registry loss.

    Returns number of workspaces discovered and registered.
    """
    discovered = 0

    # Common locations to scan
    scan_paths = [
        os.path.expanduser("~/.agent-workspace"),
        os.path.expanduser("~/.claude-orchestrator/workspaces"),
    ]

    # Also scan ~/Developer/Projects if it exists (common project root)
    projects_dir = os.path.expanduser("~/Developer/Projects")
    if os.path.isdir(projects_dir):
        try:
            for entry in os.listdir(projects_dir):
                project_path = os.path.join(projects_dir, entry)
                if os.path.isdir(project_path):
                    agent_workspace = os.path.join(project_path, ".agent-workspace")
                    if os.path.isdir(agent_workspace):
                        scan_paths.append(agent_workspace)
        except Exception as e:
            logger.warning(f"[GLOBAL_REGISTRY] Error scanning {projects_dir}: {e}")

    for workspace_path in scan_paths:
        if os.path.isdir(workspace_path):
            if register_workspace(workspace_path):
                discovered += 1

                # Also register any tasks found in this workspace
                try:
                    for entry in os.listdir(workspace_path):
                        if entry.startswith("TASK-"):
                            task_dir = os.path.join(workspace_path, entry)
                            if os.path.isdir(task_dir):
                                # Try to read task info from AGENT_REGISTRY.json
                                registry_path = os.path.join(task_dir, "AGENT_REGISTRY.json")
                                if os.path.exists(registry_path):
                                    try:
                                        with open(registry_path, 'r') as f:
                                            registry = json.load(f)
                                        register_task(
                                            task_id=entry,
                                            workspace_base=workspace_path,
                                            description=registry.get("task_description", ""),
                                            status=registry.get("status", "INITIALIZED"),
                                            priority=registry.get("priority", "P2"),
                                            created_at=registry.get("created_at")  # Preserve original timestamp
                                        )
                                    except Exception:
                                        # Register with minimal info - try to extract date from task_id
                                        # Task IDs are like: TASK-20260105-123456-abc123
                                        task_created_at = None
                                        try:
                                            parts = entry.split("-")
                                            if len(parts) >= 3:
                                                date_str = parts[1]  # e.g., "20260105"
                                                time_str = parts[2]  # e.g., "123456"
                                                if len(date_str) == 8 and len(time_str) == 6:
                                                    task_created_at = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}T{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
                                        except Exception:
                                            pass
                                        register_task(
                                            task_id=entry,
                                            workspace_base=workspace_path,
                                            created_at=task_created_at
                                        )
                except Exception as e:
                    logger.warning(f"[GLOBAL_REGISTRY] Error scanning tasks in {workspace_path}: {e}")

    logger.info(f"[GLOBAL_REGISTRY] Discovered {discovered} workspaces")
    return discovered


def get_dashboard_data() -> Dict[str, Any]:
    """
    Get comprehensive data for dashboard display.

    Aggregates data from all known workspaces.
    """
    from . import state_db

    all_tasks = []
    all_active_agents = []
    global_counts = {
        "total_tasks": 0,
        "active_tasks": 0,
        "completed_tasks": 0,
        "failed_tasks": 0,
        "total_agents": 0,
        "active_agents": 0,
        "completed_agents": 0,
        "failed_agents": 0,
    }
    task_status_dist = {}

    for workspace_info in get_all_workspaces():
        workspace_base = workspace_info["workspace_base"]
        project_name = workspace_info.get("project_name", "Unknown")

        try:
            # Get summary from this workspace's state.sqlite3
            summary = state_db.get_dashboard_summary(workspace_base=workspace_base, limit=50)

            # Add project context to tasks
            for task in summary.get("recent_tasks", []):
                task["project_name"] = project_name
                task["workspace_base"] = workspace_base
                all_tasks.append(task)

            # Add project context to agents
            for agent in summary.get("active_agents", []):
                agent["project_name"] = project_name
                agent["workspace_base"] = workspace_base
                all_active_agents.append(agent)

            # Aggregate counts
            ws_counts = summary.get("global_counts", {})
            for key in global_counts:
                global_counts[key] += ws_counts.get(key, 0)

            # Aggregate status distribution
            for status, count in summary.get("task_status_distribution", {}).items():
                task_status_dist[status] = task_status_dist.get(status, 0) + count

        except Exception as e:
            logger.warning(f"[GLOBAL_REGISTRY] Failed to get data from {workspace_base}: {e}")
            continue

    # Sort by created_at descending
    all_tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    all_active_agents.sort(key=lambda a: a.get("last_update", ""), reverse=True)

    return {
        "global_counts": global_counts,
        "recent_tasks": all_tasks[:50],
        "active_agents": all_active_agents[:100],
        "task_status_distribution": task_status_dist,
        "workspace_count": len(get_all_workspaces())
    }


# ============================================================================
# CLEANUP
# ============================================================================

def cleanup_stale_workspaces() -> int:
    """
    Mark workspaces as inactive if their directories no longer exist.

    Returns number of workspaces marked inactive.
    """
    conn = _connect()
    try:
        _init_db(conn)

        rows = conn.execute(
            "SELECT workspace_base FROM known_workspaces WHERE is_active = 1"
        ).fetchall()

        deactivated = 0
        for row in rows:
            workspace_base = row["workspace_base"]
            if not os.path.isdir(workspace_base):
                conn.execute(
                    "UPDATE known_workspaces SET is_active = 0 WHERE workspace_base = ?",
                    (workspace_base,)
                )
                deactivated += 1
                logger.info(f"[GLOBAL_REGISTRY] Marked workspace as inactive: {workspace_base}")

        return deactivated
    finally:
        conn.close()
