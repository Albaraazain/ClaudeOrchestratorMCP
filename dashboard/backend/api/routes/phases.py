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
    from orchestrator.registry import read_registry_with_lock
    from orchestrator.workspace import find_task_workspace
except ImportError:
    # Fallback implementations
    import json
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
