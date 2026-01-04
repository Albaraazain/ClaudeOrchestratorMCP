"""Tasks API routes."""

import json
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

# Add orchestrator to path
orchestrator_path = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(orchestrator_path))

# Try orchestrator imports with fallback
try:
    from orchestrator.registry import read_registry_with_lock
    from orchestrator.workspace import find_task_workspace
except ImportError:
    # Fallback implementations
    def read_registry_with_lock(path: str) -> Optional[Dict[str, Any]]:
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            return None

    def find_task_workspace(task_id: str) -> Optional[str]:
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
GLOBAL_REGISTRY_PATH = WORKSPACE_BASE / "registry" / "GLOBAL_REGISTRY.json"


def parse_task_registry(registry_data: dict) -> TaskDetail:
    """Parse task registry data into TaskDetail model."""
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
        tracked_files = TrackedFiles(
            prompt_file=agent.get("tracked_files", {}).get("prompt_file"),
            log_file=agent.get("tracked_files", {}).get("log_file"),
            progress_file=agent.get("tracked_files", {}).get("progress_file"),
            findings_file=agent.get("tracked_files", {}).get("findings_file"),
            deploy_log=agent.get("tracked_files", {}).get("deploy_log")
        )

        agents.append(AgentData(
            id=agent["id"],
            type=agent["type"],
            tmux_session=agent["tmux_session"],
            parent=agent.get("parent", "orchestrator"),
            depth=agent.get("depth", 1),
            phase_index=agent.get("phase_index", 0),
            status=agent.get("status", "running"),
            started_at=datetime.fromisoformat(agent["started_at"]),
            completed_at=datetime.fromisoformat(agent["completed_at"]) if agent.get("completed_at") else None,
            progress=agent.get("progress", 0),
            last_update=datetime.fromisoformat(agent["last_update"]),
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

    return TaskDetail(
        task_id=registry_data["task_id"],
        task_description=registry_data.get("task_description", ""),
        created_at=datetime.fromisoformat(registry_data["created_at"]),
        workspace=registry_data["workspace"],
        workspace_base=registry_data["workspace_base"],
        client_cwd=registry_data.get("client_cwd", ""),
        status=registry_data.get("status", "INITIALIZED"),
        priority=registry_data.get("priority", "P2"),
        phases=phases,
        current_phase_index=registry_data.get("current_phase_index", 0),
        agents=agents,
        agent_hierarchy=registry_data.get("agent_hierarchy", {}),
        max_agents=registry_data.get("max_agents", 45),
        max_depth=registry_data.get("max_depth", 5),
        max_concurrent=registry_data.get("max_concurrent", 20),
        total_spawned=registry_data.get("total_spawned", 0),
        active_count=registry_data.get("active_count", 0),
        completed_count=registry_data.get("completed_count", 0),
        reviews=reviews,
        task_context=task_context
    )


@router.get("", response_model=List[TaskSummary])
async def list_tasks(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    """List all tasks from the global registry."""
    try:
        # Read global registry
        if not GLOBAL_REGISTRY_PATH.exists():
            return []

        with open(GLOBAL_REGISTRY_PATH, 'r') as f:
            global_registry = json.load(f)

        tasks = []
        task_items = list(global_registry.get("tasks", {}).items())

        # Apply offset and limit
        task_items = task_items[offset:offset + limit]

        for task_id, task_info in task_items:
            # Filter by status if specified
            if status and task_info.get("status") != status:
                continue

            # Try to get more details from task registry
            task_workspace = find_task_workspace(task_id)
            current_phase = None
            agent_count = 0
            active_agents = 0
            progress = 0

            if task_workspace:
                task_registry_path = Path(task_workspace) / "AGENT_REGISTRY.json"
                if task_registry_path.exists():
                    try:
                        task_registry = read_registry_with_lock(str(task_registry_path))
                        if task_registry:
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

                            # Get agent counts
                            agents = task_registry.get("agents", [])
                            agent_count = len(agents)
                            active_agents = sum(1 for a in agents if a.get("status") in ["running", "working"])

                            # Calculate overall progress
                            if agents:
                                progress = sum(a.get("progress", 0) for a in agents) // len(agents)
                    except:
                        pass

            tasks.append(TaskSummary(
                task_id=task_id,
                description=task_info.get("description", ""),
                created_at=datetime.fromisoformat(task_info["created_at"]),
                status=task_info.get("status", "INITIALIZED"),
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
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        # Read task registry
        registry_path = Path(task_workspace) / "AGENT_REGISTRY.json"
        if not registry_path.exists():
            raise HTTPException(status_code=404, detail=f"Task registry not found")

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