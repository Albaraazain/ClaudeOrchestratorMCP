"""Standalone registry reader for desktop sidecar.

This module reads task data directly from SQLite databases without
depending on the orchestrator module imports. It's used when the
dashboard-api runs as a standalone PyInstaller binary.
"""

import sqlite3
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

# Known locations for global registry
GLOBAL_REGISTRY_PATHS = [
    Path.home() / ".agent-workspace" / "registry" / "state.sqlite3",
    Path.home() / ".agent-workspace" / "registry" / "global_registry.sqlite",
]

# Known locations for workspace bases
WORKSPACE_SEARCH_PATHS = [
    Path.home() / ".agent-workspace",
    Path.home() / "Developer" / "Projects",  # Common project location
]


def _find_global_registry_db() -> Optional[Path]:
    """Find the global registry SQLite database."""
    for path in GLOBAL_REGISTRY_PATHS:
        if path.exists():
            return path
    return None


def _discover_workspace_bases() -> List[Path]:
    """Discover all workspace bases from global registry or filesystem."""
    bases = []

    # Try global registry SQLite first
    db_path = _find_global_registry_db()
    if db_path:
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT workspace_base FROM workspace_bases")
            for row in cursor.fetchall():
                base = Path(row[0])
                if base.exists():
                    bases.append(base)
            conn.close()
            if bases:
                print(f"[Standalone Registry] Found {len(bases)} workspace bases from SQLite")
                return bases
        except Exception as e:
            print(f"[Standalone Registry] SQLite read failed: {e}")

    # Fallback: search filesystem for .agent-workspace directories
    for search_path in WORKSPACE_SEARCH_PATHS:
        if not search_path.exists():
            continue

        # Direct .agent-workspace
        if (search_path / "TASK-").parent.name == ".agent-workspace":
            bases.append(search_path)

        # Search for .agent-workspace in subdirectories
        try:
            for item in search_path.iterdir():
                if item.is_dir():
                    agent_ws = item / ".agent-workspace"
                    if agent_ws.exists() and any(agent_ws.glob("TASK-*")):
                        bases.append(agent_ws)
        except PermissionError:
            continue

    # Always include the global workspace
    global_ws = Path.home() / ".agent-workspace"
    if global_ws.exists() and global_ws not in bases:
        bases.insert(0, global_ws)

    print(f"[Standalone Registry] Discovered {len(bases)} workspace bases via filesystem")
    return bases


def get_all_tasks(
    limit: int = 200,
    offset: int = 0,
    status_filter: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    project_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get all tasks from all known workspace bases."""
    tasks = []
    seen_task_ids = set()

    # Try global registry SQLite first (has cross-project data)
    db_path = _find_global_registry_db()
    if db_path:
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Build query with filters
            query = "SELECT * FROM tasks WHERE 1=1"
            params = []

            if status_filter:
                query += " AND status = ?"
                params.append(status_filter)

            if since:
                query += " AND created_at >= ?"
                params.append(since)

            if until:
                query += " AND created_at <= ?"
                params.append(until)

            if project_filter:
                query += " AND (workspace_base LIKE ? OR client_cwd LIKE ?)"
                pattern = f"%{project_filter}%"
                params.extend([pattern, pattern])

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cursor.execute(query, params)

            for row in cursor.fetchall():
                task_id = row["task_id"]
                if task_id in seen_task_ids:
                    continue
                seen_task_ids.add(task_id)

                tasks.append({
                    "task_id": task_id,
                    "description": row["description"] or "",
                    "created_at": row["created_at"],
                    "status": row["status"] or "INITIALIZED",
                    "workspace_base": row["workspace_base"],
                    "client_cwd": row["client_cwd"],
                })

            conn.close()

            if tasks:
                print(f"[Standalone Registry] Loaded {len(tasks)} tasks from global SQLite")
                return tasks

        except Exception as e:
            print(f"[Standalone Registry] Global SQLite query failed: {e}")

    # Fallback: iterate workspace bases and read JSON registries
    for base in _discover_workspace_bases():
        # Check for GLOBAL_REGISTRY.json
        global_json = base / "registry" / "GLOBAL_REGISTRY.json"
        if global_json.exists():
            try:
                with open(global_json, "r") as f:
                    data = json.load(f)
                for task_id, task_info in (data.get("tasks", {}) or {}).items():
                    if task_id in seen_task_ids:
                        continue

                    # Apply filters
                    if status_filter and task_info.get("status") != status_filter:
                        continue

                    created_at = task_info.get("created_at", "")
                    if since and created_at < since:
                        continue
                    if until and created_at > until:
                        continue

                    seen_task_ids.add(task_id)
                    tasks.append({
                        "task_id": task_id,
                        "description": task_info.get("description", ""),
                        "created_at": created_at,
                        "status": task_info.get("status", "INITIALIZED"),
                        "workspace_base": str(base),
                        "client_cwd": "",
                    })
            except Exception as e:
                print(f"[Standalone Registry] Error reading {global_json}: {e}")

        # Also scan for TASK-* directories with AGENT_REGISTRY.json
        try:
            for task_dir in base.glob("TASK-*"):
                task_id = task_dir.name
                if task_id in seen_task_ids:
                    continue

                registry_path = task_dir / "AGENT_REGISTRY.json"
                if registry_path.exists():
                    try:
                        with open(registry_path, "r") as f:
                            registry = json.load(f)

                        # Apply filters
                        task_status = registry.get("status", "INITIALIZED")
                        if status_filter and task_status != status_filter:
                            continue

                        created_at = registry.get("created_at", "")
                        if since and created_at < since:
                            continue
                        if until and created_at > until:
                            continue

                        seen_task_ids.add(task_id)
                        tasks.append({
                            "task_id": task_id,
                            "description": registry.get("task_description", ""),
                            "created_at": created_at,
                            "status": task_status,
                            "workspace_base": str(base),
                            "client_cwd": registry.get("client_cwd", ""),
                        })
                    except Exception as e:
                        print(f"[Standalone Registry] Error reading {registry_path}: {e}")
        except Exception as e:
            print(f"[Standalone Registry] Error scanning {base}: {e}")

    # Sort by created_at descending
    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)

    print(f"[Standalone Registry] Total tasks found: {len(tasks)}")
    return tasks[offset:offset + limit]


def find_task_workspace(task_id: str) -> Optional[str]:
    """Find the workspace directory for a task."""
    # Try global registry SQLite first
    db_path = _find_global_registry_db()
    if db_path:
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute(
                "SELECT workspace_base FROM tasks WHERE task_id = ?",
                (task_id,)
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                workspace = Path(row[0]) / task_id
                if workspace.exists():
                    return str(workspace)
        except Exception:
            pass

    # Fallback: search filesystem
    for base in _discover_workspace_bases():
        task_dir = base / task_id
        if task_dir.exists():
            return str(task_dir)

    return None


def get_dashboard_data() -> Dict[str, Any]:
    """Get dashboard summary data."""
    tasks = get_all_tasks(limit=1000, since=None)  # Get all tasks

    # Calculate counts
    total_tasks = len(tasks)
    active_tasks = sum(1 for t in tasks if t["status"] in ("ACTIVE", "IN_PROGRESS", "RUNNING"))
    completed_tasks = sum(1 for t in tasks if t["status"] == "COMPLETED")
    failed_tasks = sum(1 for t in tasks if t["status"] in ("FAILED", "ERROR"))

    # Count agents from task registries
    total_agents = 0
    active_agents = 0
    completed_agents = 0
    failed_agents = 0

    for task in tasks[:50]:  # Limit to recent tasks for performance
        workspace = find_task_workspace(task["task_id"])
        if workspace:
            registry_path = Path(workspace) / "AGENT_REGISTRY.json"
            if registry_path.exists():
                try:
                    with open(registry_path, "r") as f:
                        registry = json.load(f)
                    agents = registry.get("agents", [])
                    total_agents += len(agents)
                    for a in agents:
                        status = a.get("status", "").lower()
                        if status in ("running", "working", "blocked"):
                            active_agents += 1
                        elif status == "completed":
                            completed_agents += 1
                        elif status in ("failed", "error"):
                            failed_agents += 1
                except Exception:
                    pass

    # Status distribution
    status_dist = {}
    for task in tasks:
        status = task["status"]
        status_dist[status] = status_dist.get(status, 0) + 1

    return {
        "global_counts": {
            "total_tasks": total_tasks,
            "active_tasks": active_tasks,
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "total_agents": total_agents,
            "active_agents": active_agents,
            "completed_agents": completed_agents,
            "failed_agents": failed_agents,
        },
        "recent_tasks": tasks[:20],
        "active_agents": [],
        "task_status_distribution": status_dist,
        "workspace_count": len(_discover_workspace_bases()),
    }
