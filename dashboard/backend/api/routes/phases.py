"""Phases API routes."""

from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, HTTPException

router = APIRouter()


# Add orchestrator to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

try:
    from orchestrator import state_db
    from orchestrator.registry import read_registry_with_lock
    from orchestrator.workspace import find_task_workspace
except ImportError:
    # Fallback implementations
    import json

    # Mock state_db if not available
    class MockStateDB:
        @staticmethod
        def load_task_snapshot(*, workspace_base: str, task_id: str):
            return None

        @staticmethod
        def get_phase_agent_counts(*, workspace_base: str, task_id: str, phase_index: int):
            return {"total": 0, "active": 0, "completed": 0, "failed": 0, "pending": 0}

    state_db = MockStateDB()

    def find_task_workspace(task_id: str):
        base = Path.home() / ".agent-workspace" / task_id
        if base.exists():
            return str(base)
        # Check current project
        project_base = Path(__file__).parent.parent.parent.parent.parent / ".agent-workspace" / task_id
        if project_base.exists():
            return str(project_base)
        return None

    def read_registry_with_lock(path: str):
        try:
            with open(path) as f:
                return json.load(f)
        except:
            return None


@router.get("/{task_id}")
async def get_phases(task_id: str) -> List[Dict[str, Any]]:
    """Get all phases for a task."""
    workspace = find_task_workspace(task_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Get base path (parent of task workspace)
    base_path = Path(workspace).parent

    # Try SQLite first
    task_snapshot = state_db.load_task_snapshot(
        workspace_base=str(base_path),
        task_id=task_id
    )

    if task_snapshot:
        return task_snapshot.get('phases', [])
    else:
        # Fallback to JSON only if SQLite unavailable
        registry_path = Path(workspace) / "AGENT_REGISTRY.json"
        registry = read_registry_with_lock(str(registry_path))
        if not registry:
            raise HTTPException(status_code=404, detail="Registry not found")
        return registry.get("phases", [])


@router.get("/{task_id}/current")
async def get_current_phase(task_id: str) -> Dict[str, Any]:
    """Get current phase status for a task."""
    workspace = find_task_workspace(task_id)
    if not workspace:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Get base path (parent of task workspace)
    base_path = Path(workspace).parent

    # Try SQLite first
    task_snapshot = state_db.load_task_snapshot(
        workspace_base=str(base_path),
        task_id=task_id
    )

    if task_snapshot:
        current_index = task_snapshot.get("current_phase_index", 0)
        phases = task_snapshot.get("phases", [])

        if not phases or current_index >= len(phases):
            raise HTTPException(status_code=404, detail="No phases found")

        current_phase = phases[current_index]

        # Get agent counts from state_db
        agent_counts = state_db.get_phase_agent_counts(
            workspace_base=str(base_path),
            task_id=task_id,
            phase_index=current_index
        )

        return {
            "phase_index": current_index,
            "phase_name": current_phase.get("name", ""),
            "status": current_phase.get("status", "PENDING"),
            "total_phases": len(phases),
            "agent_stats": {
                "total": agent_counts.get("total", 0),
                "completed": agent_counts.get("completed", 0),
                "working": agent_counts.get("active", 0),
                "failed": agent_counts.get("failed", 0)
            },
            "is_final_phase": current_index == len(phases) - 1
        }
    else:
        # Fallback to JSON only if SQLite unavailable
        registry_path = Path(workspace) / "AGENT_REGISTRY.json"
        registry = read_registry_with_lock(str(registry_path))

        if not registry:
            raise HTTPException(status_code=404, detail="Registry not found")

        current_index = registry.get("current_phase_index", 0)
        phases = registry.get("phases", [])

        if not phases or current_index >= len(phases):
            raise HTTPException(status_code=404, detail="No phases found")

        current_phase = phases[current_index]

        # Count agents per phase
        agents = registry.get("agents", [])
        phase_agents = [a for a in agents if a.get("phase_index") == current_index]
        completed = sum(1 for a in phase_agents if a.get("status") == "completed")
        failed = sum(1 for a in phase_agents if a.get("status") in ["failed", "error"])
        working = len(phase_agents) - completed - failed

        return {
            "phase_index": current_index,
            "phase_name": current_phase["name"],
            "status": current_phase["status"],
            "total_phases": len(phases),
            "agent_stats": {
                "total": len(phase_agents),
                "completed": completed,
                "working": working,
                "failed": failed
            },
            "is_final_phase": current_index == len(phases) - 1
        }
