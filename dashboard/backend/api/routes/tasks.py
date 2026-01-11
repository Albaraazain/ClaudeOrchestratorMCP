"""Tasks API routes."""

import json
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query

# Add orchestrator to path
orchestrator_path = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(orchestrator_path))

# Try orchestrator imports with fallback to standalone registry
try:
    from orchestrator.registry import read_registry_with_lock
    from orchestrator.workspace import find_task_workspace
    # Import state_db for SQLite-based counts
    from orchestrator import state_db
    HAS_STATE_DB = True
    HAS_STANDALONE = False
    print("[API] Using orchestrator modules (full integration)")
except ImportError:
    HAS_STATE_DB = False
    # Try standalone registry for PyInstaller bundle
    try:
        from services.standalone_registry import (
            get_all_tasks as standalone_get_all_tasks,
            find_task_workspace as standalone_find_task_workspace,
            get_dashboard_data as standalone_get_dashboard_data,
        )
        HAS_STANDALONE = True
        print("[API] Using standalone registry (desktop mode)")
    except ImportError:
        HAS_STANDALONE = False
        print("[API] WARNING: No registry backend available!")

    # Fallback implementations
    def read_registry_with_lock(path: str) -> Optional[Dict[str, Any]]:
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            return None

    def find_task_workspace(task_id: str) -> Optional[str]:
        # Use standalone if available
        if HAS_STANDALONE:
            return standalone_find_task_workspace(task_id)
        # Check common locations
        bases = [
            Path.home() / ".agent-workspace",
            Path(__file__).parent.parent.parent.parent.parent / ".agent-workspace"
        ]
        for base in bases:
            task_dir = base / task_id
            if task_dir.exists():
                return str(task_dir)
        return None

# Import models
from models.schemas import TaskSummary, TaskDetail, PhaseData, AgentData, TrackedFiles, TaskContext, ReviewData

router = APIRouter()

# Base workspace path
WORKSPACE_BASE = Path.home() / ".agent-workspace"
LOCAL_WORKSPACE_BASE = orchestrator_path / ".agent-workspace"

ALLOWED_AGENT_STATUSES = {
    "running",
    "working",
    "blocked",
    "completed",
    "failed",
    "error",
    "terminated",
    "reviewing",
}


def _to_naive_datetime(dt: datetime) -> datetime:
    """Convert any datetime to naive (timezone-unaware) for consistent comparisons."""
    if dt.tzinfo is not None:
        # Convert to UTC then strip timezone
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_datetime_naive(value: Any) -> Optional[datetime]:
    """Parse an ISO datetime string and return a naive datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
        return _to_naive_datetime(dt)
    except Exception:
        return None


def _normalize_agent_status(status: Any, progress: Any = None) -> str:
    """Normalize arbitrary status strings into the API's allowed status set."""
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


def _iter_workspace_bases() -> List[Path]:
    """Return workspace bases to search (global registry + fallbacks)."""
    # Try global SQLite registry first (cross-project discovery)
    try:
        from orchestrator import global_registry
        global_registry.ensure_global_registry()
        # Also discover any existing workspaces that aren't registered yet
        global_registry.discover_existing_workspaces()
        registered_bases = global_registry.get_workspace_bases()
        if registered_bases:
            print(f"[API] Found {len(registered_bases)} workspace(s) in global registry")
            return [Path(b) for b in registered_bases]
    except Exception as e:
        print(f"[API] Global registry lookup failed, using fallback: {e}")

    # Fallback to hardcoded locations
    bases = [WORKSPACE_BASE, LOCAL_WORKSPACE_BASE]
    seen = set()
    unique: List[Path] = []
    for base in bases:
        resolved = base.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(base)
    return unique


def _load_global_registries() -> Dict[str, Dict[str, Any]]:
    """
    Load and merge tasks from any available GLOBAL_REGISTRY.json files.

    Returns:
        Mapping of task_id -> task_info
    """
    merged: Dict[str, Dict[str, Any]] = {}
    for base in _iter_workspace_bases():
        registry_path = base / "registry" / "GLOBAL_REGISTRY.json"
        if not registry_path.exists():
            continue
        try:
            with open(registry_path, "r") as f:
                global_registry = json.load(f)
            for task_id, task_info in (global_registry.get("tasks", {}) or {}).items():
                if task_id not in merged:
                    merged[task_id] = dict(task_info)
                    continue

                existing = merged[task_id]
                # Prefer non-empty description/status if present.
                if task_info.get("description") and not existing.get("description"):
                    existing["description"] = task_info["description"]
                if task_info.get("status") and existing.get("status") in (None, "INITIALIZED"):
                    existing["status"] = task_info["status"]
                if task_info.get("created_at") and not existing.get("created_at"):
                    existing["created_at"] = task_info["created_at"]
        except Exception:
            continue

    return merged


def _iter_task_ids_from_registries() -> List[str]:
    """Return task IDs discovered from existing AGENT_REGISTRY.json files."""
    task_ids: set[str] = set()
    for base in _iter_workspace_bases():
        if not base.exists():
            continue
        try:
            for registry_path in base.glob("TASK-*/AGENT_REGISTRY.json"):
                task_id = registry_path.parent.name
                if task_id.startswith("TASK-"):
                    task_ids.add(task_id)
        except Exception:
            continue
    return sorted(task_ids)


def parse_task_registry(registry_data: dict) -> TaskDetail:
    """Parse task registry data into TaskDetail model."""
    workspace_path = registry_data.get("workspace") or ""

    def _parse_dt(value: Any, fallback: Optional[datetime]) -> Optional[datetime]:
        if not value:
            return fallback
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return fallback

    def _read_last_jsonl_entry(path: Path) -> Optional[Dict[str, Any]]:
        try:
            if not path.exists():
                return None
            # Keep only a small tail to avoid loading huge files.
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

    phases = []
    for phase in registry_data.get("phases", []):
        phases.append(PhaseData(
            id=phase["id"],
            order=phase["order"],
            name=phase["name"],
            description=phase.get("description"),
            status=phase["status"],
            created_at=datetime.fromisoformat(phase["created_at"]),
            started_at=datetime.fromisoformat(phase["started_at"]) if phase.get("started_at") else None,
            completed_at=datetime.fromisoformat(phase["completed_at"]) if phase.get("completed_at") else None
        ))

    agents = []
    for agent in registry_data.get("agents", []):
        # Normalize registry status first (registry can drift / contain non-schema statuses).
        agent = dict(agent)
        agent["status"] = _normalize_agent_status(agent.get("status"), agent.get("progress", 0))

        # JSONL is the source of truth for status/progress/last_update.
        agent_id = agent.get("id", "")
        if workspace_path and agent_id:
            tracked_progress = (agent.get("tracked_files") or {}).get("progress_file")
            progress_path = Path(tracked_progress) if tracked_progress else (
                Path(workspace_path) / "progress" / f"{agent_id}_progress.jsonl"
            )
            last_progress = _read_last_jsonl_entry(progress_path)
            if last_progress:
                if last_progress.get("status"):
                    agent["status"] = _normalize_agent_status(
                        last_progress["status"],
                        last_progress.get("progress", agent.get("progress", 0)),
                    )
                if "progress" in last_progress:
                    agent["progress"] = last_progress.get("progress", agent.get("progress", 0))
                if last_progress.get("timestamp"):
                    agent["last_update"] = last_progress["timestamp"]
                    if agent.get("status") == "completed":
                        agent.setdefault("completed_at", last_progress["timestamp"])

        tracked_files = TrackedFiles(
            prompt_file=agent.get("tracked_files", {}).get("prompt_file"),
            log_file=agent.get("tracked_files", {}).get("log_file"),
            progress_file=agent.get("tracked_files", {}).get("progress_file"),
            findings_file=agent.get("tracked_files", {}).get("findings_file"),
            deploy_log=agent.get("tracked_files", {}).get("deploy_log")
        )

        started_at_raw = agent.get("started_at") or agent.get("start_time") or registry_data.get("created_at")
        started_at_dt = _parse_dt(started_at_raw, datetime.fromtimestamp(0)) or datetime.fromtimestamp(0)
        completed_at_raw = agent.get("completed_at") or agent.get("end_time")
        completed_at_dt = _parse_dt(completed_at_raw, None) if completed_at_raw else None
        last_update_raw = agent.get("last_update") or agent.get("updated_at") or completed_at_raw or started_at_raw
        last_update_dt = _parse_dt(last_update_raw, started_at_dt) or started_at_dt

        agents.append(AgentData(
            id=agent["id"],
            type=agent.get("type") or agent.get("agent_type") or "unknown",
            tmux_session=agent.get("tmux_session", ""),
            parent=agent.get("parent", "orchestrator"),
            depth=agent.get("depth", 1),
            phase_index=agent.get("phase_index", 0),
            status=agent.get("status", "running"),
            started_at=started_at_dt,
            completed_at=completed_at_dt,
            progress=agent.get("progress", 0),
            last_update=last_update_dt,
            prompt=agent.get("prompt", "")[:200],
            claude_pid=agent.get("claude_pid"),
            cursor_pid=agent.get("cursor_pid"),
            tracked_files=tracked_files
        ))

    reviews = []
    for review in registry_data.get("reviews", []):
        try:
            reviews.append(ReviewData(
                review_id=review.get("review_id", ""),
                phase_index=review.get("phase_index", 0),
                status=review.get("status", "pending"),
                started_at=datetime.fromisoformat(review["started_at"]) if review.get("started_at") else datetime.now(),
                reviewer_count=review.get("reviewer_count", 0),
                verdicts_submitted=review.get("verdicts_submitted", len(review.get("verdicts", []))),
                final_verdict=review.get("final_verdict")
            ))
        except Exception as e:
            print(f"[API] Skipping malformed review: {e}")

    task_context = TaskContext(
        expected_deliverables=registry_data.get("task_context", {}).get("expected_deliverables", []),
        success_criteria=registry_data.get("task_context", {}).get("success_criteria", []),
        relevant_files=registry_data.get("task_context", {}).get("relevant_files", [])
    )

    # Recompute counts defensively from reconciled agent statuses.
    active_statuses = {"running", "working", "blocked", "reviewing"}
    active_count = sum(1 for a in agents if a.status in active_statuses)
    completed_count = sum(1 for a in agents if a.status == "completed")
    total_spawned = max(registry_data.get("total_spawned", 0), len(agents))

    return TaskDetail(
        task_id=registry_data["task_id"],
        task_description=registry_data.get("task_description", ""),
        created_at=datetime.fromisoformat(registry_data["created_at"]),
        workspace=str(registry_data.get("workspace") or workspace_path or ""),
        workspace_base=str(registry_data.get("workspace_base") or (str(Path(workspace_path).parent) if workspace_path else "")),
        client_cwd=str(registry_data.get("client_cwd") or ""),
        status=registry_data.get("status", "INITIALIZED"),
        priority=registry_data.get("priority", "P2"),
        phases=phases,
        current_phase_index=registry_data.get("current_phase_index", 0),
        agents=agents,
        agent_hierarchy=registry_data.get("agent_hierarchy", {}),
        max_agents=registry_data.get("max_agents", 45),
        max_depth=registry_data.get("max_depth", 5),
        max_concurrent=registry_data.get("max_concurrent", 20),
        total_spawned=total_spawned,
        active_count=active_count,
        completed_count=completed_count,
        reviews=reviews,
        task_context=task_context
    )


@router.get("", response_model=List[TaskSummary])
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    since: Optional[str] = Query("today", description="Filter tasks created since this date (ISO format: YYYY-MM-DD, or 'today', 'yesterday', 'week', 'all')"),
    until: Optional[str] = Query(None, description="Filter tasks created until this date (ISO format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)"),
    project: Optional[str] = Query(None, description="Filter by project name (partial match)"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0)
):
    """List tasks from SQLite database with optional filters. Default: today's tasks only."""
    # Handle convenience date shortcuts
    from datetime import timedelta
    today = datetime.now().date()

    if since == "today":
        since = today.isoformat()
    elif since == "yesterday":
        since = (today - timedelta(days=1)).isoformat()
    elif since == "week":
        since = (today - timedelta(days=7)).isoformat()
    elif since == "all":
        since = None  # No filter
    try:
        # Try standalone registry first (for PyInstaller bundle / desktop mode)
        if HAS_STANDALONE:
            try:
                standalone_tasks = standalone_get_all_tasks(
                    limit=limit,
                    offset=offset,
                    status_filter=status,
                    since=since,
                    until=until,
                    project_filter=project
                )
                if standalone_tasks:
                    filters_applied = []
                    if since: filters_applied.append(f"since={since}")
                    if until: filters_applied.append(f"until={until}")
                    if project: filters_applied.append(f"project={project}")
                    if status: filters_applied.append(f"status={status}")
                    filter_str = f" with filters: {', '.join(filters_applied)}" if filters_applied else ""
                    print(f"[API] list_tasks: Using standalone registry ({len(standalone_tasks)} tasks){filter_str}")

                    tasks: List[TaskSummary] = []
                    for task_data in standalone_tasks:
                        created_at = datetime.fromisoformat(task_data['created_at']) if task_data.get('created_at') else datetime.now()
                        tasks.append(TaskSummary(
                            task_id=task_data['task_id'],
                            description=task_data.get('description', ''),
                            created_at=created_at,
                            status=task_data.get('status', 'INITIALIZED'),
                            current_phase=None,
                            agent_count=0,
                            active_agents=0,
                            progress=0
                        ))
                    return tasks
            except Exception as e:
                print(f"[API] Standalone registry failed: {e}")

        # Try global registry next (supports cross-project filtering)
        try:
            from orchestrator import global_registry
            global_registry.ensure_global_registry()

            # Use global registry for filtered queries
            global_tasks = global_registry.get_all_tasks(
                limit=limit,
                offset=offset,
                status_filter=status,
                since=since,
                until=until,
                project_filter=project
            )

            if global_tasks:
                filters_applied = []
                if since: filters_applied.append(f"since={since}")
                if until: filters_applied.append(f"until={until}")
                if project: filters_applied.append(f"project={project}")
                if status: filters_applied.append(f"status={status}")
                filter_str = f" with filters: {', '.join(filters_applied)}" if filters_applied else ""
                print(f"[API] list_tasks: Using global registry ({len(global_tasks)} tasks){filter_str}")

                tasks: List[TaskSummary] = []
                for task_data in global_tasks:
                    # Convert global registry data to TaskSummary
                    created_at = datetime.fromisoformat(task_data['created_at']) if task_data.get('created_at') else datetime.now()

                    tasks.append(TaskSummary(
                        task_id=task_data['task_id'],
                        description=task_data.get('description', ''),
                        created_at=created_at,
                        status=task_data.get('status', 'INITIALIZED'),
                        current_phase=None,  # Global registry doesn't have phase details
                        agent_count=0,
                        active_agents=0,
                        progress=0
                    ))

                return tasks
        except Exception as e:
            print(f"[API] Global registry failed, falling back: {e}")

        # Fallback: iterate workspace bases
        if HAS_STATE_DB:
            print(f"[API] list_tasks: Using per-workspace SQLite (HAS_STATE_DB=True)")
            tasks: List[TaskSummary] = []

            for base in _iter_workspace_bases():
                if not base.exists():
                    continue

                try:
                    # Ensure any task workspaces are reconciled to SQLite first
                    for task_dir in base.glob("TASK-*"):
                        if (task_dir / "AGENT_REGISTRY.json").exists():
                            state_db.reconcile_task_workspace(str(task_dir))

                    # Get tasks from SQLite
                    task_list = state_db.get_all_tasks(
                        workspace_base=str(base),
                        limit=limit,
                        offset=offset,
                        status_filter=status
                    )

                    for task_data in task_list:
                        # Convert SQLite data to TaskSummary
                        current_phase = None
                        if task_data.get('current_phase_name'):
                            current_phase = PhaseData(
                                id=f"phase_{task_data.get('current_phase_index', 0)}",
                                order=task_data.get('current_phase_index', 0),
                                name=task_data['current_phase_name'],
                                description=None,
                                status=task_data.get('current_phase_status', 'PENDING'),
                                created_at=datetime.fromisoformat(task_data['created_at']),
                                started_at=None,
                                completed_at=None
                            )

                        # Calculate progress
                        total_agents = task_data.get('total_agents', 0)
                        completed_agents = task_data.get('completed_agents', 0)
                        progress = 0
                        if total_agents > 0:
                            progress = (completed_agents * 100) // total_agents

                        tasks.append(TaskSummary(
                            task_id=task_data['task_id'],
                            description=task_data.get('description', ''),
                            created_at=datetime.fromisoformat(task_data['created_at']),
                            status=task_data.get('status', 'INITIALIZED'),
                            current_phase=current_phase,
                            agent_count=total_agents,
                            active_agents=task_data.get('active_agents', 0),
                            progress=progress
                        ))
                except Exception as e:
                    print(f"[API] Error loading tasks from SQLite at {base}: {e}")
                    # Continue to next base or fallback

            if tasks:
                # Sort by created_at descending (normalize to naive for comparison)
                tasks.sort(key=lambda t: _to_naive_datetime(t.created_at), reverse=True)
                return tasks[:limit]  # Already limited by SQLite, but ensure max

        # FALLBACK: Only use JSON if state_db is not available
        print("[API] WARNING: Using JSON fallback for list_tasks (stale data!)")

        def _read_last_jsonl_entry(path: Path) -> Optional[Dict[str, Any]]:
            try:
                if not path.exists():
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

        global_tasks = _load_global_registries()
        discovered_task_ids = _iter_task_ids_from_registries()

        # Merge (prefer global registry description/status when present)
        all_task_ids = set(global_tasks.keys()) | set(discovered_task_ids)
        if not all_task_ids:
            return []

        def _created_at_key(tid: str) -> datetime:
            """Return a naive datetime for sorting. All datetimes are normalized to naive."""
            info = global_tasks.get(tid, {})
            created_at = info.get("created_at")
            if created_at:
                parsed = _parse_datetime_naive(created_at)
                if parsed:
                    return parsed

            # Try to read from the task's own registry for discovered tasks.
            task_workspace = find_task_workspace(tid)
            if task_workspace:
                task_registry_path = Path(task_workspace) / "AGENT_REGISTRY.json"
                if task_registry_path.exists():
                    try:
                        task_registry = read_registry_with_lock(str(task_registry_path))
                        if task_registry and task_registry.get("created_at"):
                            parsed = _parse_datetime_naive(task_registry["created_at"])
                            if parsed:
                                return parsed
                    except Exception:
                        pass

            # Fall back to parsing from the task ID (TASK-YYYYMMDD-HHMMSS-...).
            try:
                parts = tid.split("-")
                if len(parts) >= 3:
                    ymd = parts[1]
                    hm = parts[2]
                    return datetime.strptime(f"{ymd}{hm}", "%Y%m%d%H%M%S")
            except Exception:
                pass

            # Last resort: epoch start so unparseable items sort last.
            return datetime.fromtimestamp(0)

        sorted_task_ids = sorted(all_task_ids, key=_created_at_key, reverse=True)
        sliced_task_ids = sorted_task_ids[offset:offset + limit]

        tasks: List[TaskSummary] = []
        for task_id in sliced_task_ids:
            task_info = global_tasks.get(task_id, {})
            # Filter by status if specified
            if status and task_info.get("status") != status:
                continue

            # Try to get more details from task registry
            task_workspace = find_task_workspace(task_id)
            current_phase = None
            agent_count = 0
            active_agents = 0
            progress = 0
            created_at = task_info.get("created_at")
            description = task_info.get("description", "")
            task_status = task_info.get("status", "INITIALIZED")

            if task_workspace:
                task_registry_path = Path(task_workspace) / "AGENT_REGISTRY.json"
                if task_registry_path.exists():
                    try:
                        task_registry = read_registry_with_lock(str(task_registry_path))
                        if task_registry:
                            created_at = created_at or task_registry.get("created_at")
                            description = description or task_registry.get("task_description", "") or ""
                            task_status = task_registry.get("status", task_status)

                            # Get current phase
                            current_phase_index = task_registry.get("current_phase_index", 0)
                            phases = task_registry.get("phases", [])
                            if phases and current_phase_index < len(phases):
                                phase = phases[current_phase_index]
                                current_phase = PhaseData(
                                    id=phase["id"],
                                    order=phase["order"],
                                    name=phase["name"],
                                    description=phase.get("description"),
                                    status=phase["status"],
                                    created_at=datetime.fromisoformat(phase["created_at"]),
                                    started_at=datetime.fromisoformat(phase["started_at"]) if phase.get("started_at") else None,
                                    completed_at=datetime.fromisoformat(phase["completed_at"]) if phase.get("completed_at") else None
                                )

                            # Get agent counts - prefer SQLite if available
                            if HAS_STATE_DB and Path(task_workspace).parent.exists():
                                try:
                                    # Ensure task is reconciled to SQLite
                                    state_db.reconcile_task_workspace(task_workspace)
                                    # Get counts from SQLite
                                    task_counts = state_db.get_task_counts(
                                        workspace_base=str(Path(task_workspace).parent),
                                        task_id=task_id
                                    )
                                    agent_count = task_counts["total_agents"]
                                    active_agents = task_counts["active_agents"]
                                    completed_agents = task_counts["completed_agents"]
                                    # Calculate progress based on completion
                                    if agent_count > 0:
                                        progress = (completed_agents * 100) // agent_count
                                    else:
                                        progress = 0
                                except Exception as e:
                                    print(f"[API] Failed to get counts from SQLite for {task_id}: {e}")
                                    # Fall back to manual counting
                                    agents = task_registry.get("agents", [])
                                    agent_count = len(agents)
                                    active_statuses = {"running", "working", "blocked", "reviewing"}
                                    agent_progress_values: List[int] = []
                                    active_agents = 0

                                    for a in agents:
                                        aid = a.get("id", "")
                                        last = None
                                        if aid:
                                            last = _read_last_jsonl_entry(
                                                Path(task_workspace) / "progress" / f"{aid}_progress.jsonl"
                                            )

                                        a_status = (last.get("status") if last else None) or a.get("status")
                                        a_progress = (last.get("progress") if last else None)
                                        if a_progress is None:
                                            a_progress = a.get("progress", 0)
                                        a_status = _normalize_agent_status(a_status, a_progress)

                                        if a_status in active_statuses:
                                            active_agents += 1
                                        try:
                                            agent_progress_values.append(int(a_progress))
                                        except Exception:
                                            agent_progress_values.append(0)

                                    # Calculate overall progress
                                    if agent_progress_values:
                                        progress = sum(agent_progress_values) // len(agent_progress_values)
                            else:
                                # Original fallback logic
                                agents = task_registry.get("agents", [])
                                agent_count = len(agents)
                                active_statuses = {"running", "working", "blocked", "reviewing"}
                                agent_progress_values: List[int] = []
                                active_agents = 0

                                for a in agents:
                                    aid = a.get("id", "")
                                    last = None
                                    if aid:
                                        last = _read_last_jsonl_entry(
                                            Path(task_workspace) / "progress" / f"{aid}_progress.jsonl"
                                        )

                                    a_status = (last.get("status") if last else None) or a.get("status")
                                    a_progress = (last.get("progress") if last else None)
                                    if a_progress is None:
                                        a_progress = a.get("progress", 0)
                                    a_status = _normalize_agent_status(a_status, a_progress)

                                    if a_status in active_statuses:
                                        active_agents += 1
                                    try:
                                        agent_progress_values.append(int(a_progress))
                                    except Exception:
                                        agent_progress_values.append(0)

                                # Calculate overall progress
                                if agent_progress_values:
                                    progress = sum(agent_progress_values) // len(agent_progress_values)
                    except:
                        pass

            if not created_at:
                # As a last resort, synthesize from task ID prefix (TASK-YYYYMMDD-...)
                try:
                    parts = task_id.split("-")
                    if len(parts) >= 3:
                        ymd = parts[1]
                        hm = parts[2]
                        created_at = datetime.strptime(f"{ymd}{hm}", "%Y%m%d%H%M%S").isoformat()
                except Exception:
                    created_at = datetime.fromtimestamp(0).isoformat()

            tasks.append(TaskSummary(
                task_id=task_id,
                description=description,
                created_at=datetime.fromisoformat(created_at),
                status=task_status,
                current_phase=current_phase,
                agent_count=agent_count,
                active_agents=active_agents,
                progress=progress
            ))

        return tasks

    except Exception as e:
        print(f"[API] Error listing tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(task_id: str):
    """Get detailed information about a specific task."""
    try:
        # Find task workspace
        task_workspace = find_task_workspace(task_id)
        if not task_workspace:
            # Fallback: return a minimal TaskDetail if the task exists in any global registry.
            global_tasks = _load_global_registries()
            task_info = global_tasks.get(task_id)
            if not task_info:
                raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

            created_at = task_info.get("created_at") or datetime.fromtimestamp(0).isoformat()
            try:
                created_dt = datetime.fromisoformat(created_at)
            except Exception:
                created_dt = datetime.fromtimestamp(0)

            # Provide an expected workspace path even if it doesn't exist.
            expected_base = WORKSPACE_BASE
            expected_workspace = expected_base / task_id

            return TaskDetail(
                task_id=task_id,
                task_description=task_info.get("description", ""),
                created_at=created_dt,
                workspace=str(expected_workspace),
                workspace_base=str(expected_base),
                client_cwd="",
                status=task_info.get("status", "INITIALIZED"),
                priority="P2",
                phases=[],
                current_phase_index=0,
                agents=[],
                agent_hierarchy={},
                total_spawned=0,
                active_count=0,
                completed_count=0,
                reviews=[],
                task_context=TaskContext()
            )

        # Read task registry
        registry_path = Path(task_workspace) / "AGENT_REGISTRY.json"
        if not registry_path.exists():
            # Fallback: show minimal details rather than a hard 404.
            global_tasks = _load_global_registries()
            task_info = global_tasks.get(task_id, {})
            created_at = task_info.get("created_at") or datetime.fromtimestamp(0).isoformat()
            try:
                created_dt = datetime.fromisoformat(created_at)
            except Exception:
                created_dt = datetime.fromtimestamp(0)

            return TaskDetail(
                task_id=task_id,
                task_description=task_info.get("description", ""),
                created_at=created_dt,
                workspace=str(task_workspace),
                workspace_base=str(Path(task_workspace).parent),
                client_cwd="",
                status=task_info.get("status", "INITIALIZED"),
                priority="P2",
                phases=[],
                current_phase_index=0,
                agents=[],
                agent_hierarchy={},
                total_spawned=0,
                active_count=0,
                completed_count=0,
                reviews=[],
                task_context=TaskContext()
            )

        registry_data = read_registry_with_lock(str(registry_path))
        if not registry_data:
            raise HTTPException(status_code=500, detail="Failed to read task registry")

        # Parse and return task details
        return parse_task_registry(registry_data)

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error getting task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}/registry")
async def get_task_registry(task_id: str):
    """Get the raw registry data for a task."""
    try:
        # Find task workspace
        task_workspace = find_task_workspace(task_id)
        if not task_workspace:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        # Read task registry
        registry_path = Path(task_workspace) / "AGENT_REGISTRY.json"
        if not registry_path.exists():
            raise HTTPException(status_code=404, detail=f"Task registry not found")

        registry_data = read_registry_with_lock(str(registry_path))
        if not registry_data:
            raise HTTPException(status_code=500, detail="Failed to read task registry")

        return registry_data

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error getting task registry {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary/dashboard")
async def get_dashboard_summary():
    """Get dashboard summary with SQLite-derived counts from all projects."""
    try:
        # Try standalone registry first (for PyInstaller bundle / desktop mode)
        if HAS_STANDALONE:
            try:
                dashboard_data = standalone_get_dashboard_data()
                if dashboard_data and dashboard_data.get("global_counts", {}).get("total_tasks", 0) > 0:
                    print(f"[API] get_dashboard_summary: Using standalone registry ({dashboard_data.get('workspace_count', 0)} workspaces)")
                    return dashboard_data
            except Exception as e:
                print(f"[API] Standalone dashboard failed: {e}")

        # Try global registry next - it aggregates all projects
        try:
            from orchestrator import global_registry
            global_registry.ensure_global_registry()
            global_registry.discover_existing_workspaces()
            dashboard_data = global_registry.get_dashboard_data()
            if dashboard_data and dashboard_data.get("global_counts", {}).get("total_tasks", 0) > 0:
                print(f"[API] get_dashboard_summary: Using global SQLite registry ({dashboard_data['workspace_count']} workspaces)")
                return dashboard_data
        except Exception as e:
            print(f"[API] Global registry dashboard failed, falling back: {e}")

        # Fallback: iterate workspace bases and merge
        if HAS_STATE_DB:
            print(f"[API] get_dashboard_summary: Using per-workspace SQLite (HAS_STATE_DB=True)")
            summaries = []
            for base in _iter_workspace_bases():
                if base.exists():
                    try:
                        # Ensure any task workspaces are reconciled to SQLite
                        for task_dir in base.glob("TASK-*"):
                            if (task_dir / "AGENT_REGISTRY.json").exists():
                                state_db.reconcile_task_workspace(str(task_dir))

                        # Get dashboard summary from SQLite
                        summary = state_db.get_dashboard_summary(workspace_base=str(base), limit=20)
                        summaries.append(summary)
                    except Exception as e:
                        print(f"[API] Error getting summary from {base}: {e}")
                        continue

            # Merge summaries if multiple workspace bases
            if not summaries:
                # Return empty data if no summaries
                return {
                    "global_counts": {
                        "total_tasks": 0,
                        "active_tasks": 0,
                        "completed_tasks": 0,
                        "failed_tasks": 0,
                        "total_agents": 0,
                        "active_agents": 0,
                        "completed_agents": 0,
                        "failed_agents": 0,
                    },
                    "recent_tasks": [],
                    "active_agents": [],
                    "task_status_distribution": {}
                }

            if len(summaries) == 1:
                return summaries[0]

            # Merge multiple summaries
            merged_counts = {}
            for key in summaries[0]["global_counts"].keys():
                merged_counts[key] = sum(s["global_counts"].get(key, 0) for s in summaries)

            all_tasks = []
            for s in summaries:
                all_tasks.extend(s["recent_tasks"])
            all_tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)

            all_agents = []
            for s in summaries:
                all_agents.extend(s["active_agents"])
            all_agents.sort(key=lambda a: a.get("last_update", ""), reverse=True)

            merged_status_dist = {}
            for s in summaries:
                for status, count in s["task_status_distribution"].items():
                    merged_status_dist[status] = merged_status_dist.get(status, 0) + count

            return {
                "global_counts": merged_counts,
                "recent_tasks": all_tasks[:20],
                "active_agents": all_agents[:50],
                "task_status_distribution": merged_status_dist
            }

        else:
            # Fallback to old JSON behavior ONLY if state_db not available
            # This should rarely happen as state_db is part of the codebase
            print("[API] WARNING: state_db not available, falling back to JSON (stale data!)")
            global_registry_path = WORKSPACE_BASE / "registry" / "GLOBAL_REGISTRY.json"
            if global_registry_path.exists():
                with open(global_registry_path, 'r') as f:
                    global_data = json.load(f)
                    return {
                        "global_counts": {
                            "total_tasks": global_data.get("total_tasks", 0),
                            "active_tasks": global_data.get("active_tasks", 0),
                            "total_agents": global_data.get("total_agents_spawned", 0),
                            "active_agents": global_data.get("active_agents", 0),
                        },
                        "recent_tasks": [],
                        "active_agents": [],
                        "task_status_distribution": {}
                    }
            return {
                "global_counts": {
                    "total_tasks": 0,
                    "active_tasks": 0,
                    "total_agents": 0,
                    "active_agents": 0,
                },
                "recent_tasks": [],
                "active_agents": [],
                "task_status_distribution": {}
            }

    except Exception as e:
        print(f"[API] Error getting dashboard summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))
