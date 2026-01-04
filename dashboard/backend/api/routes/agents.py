"""Agents API routes."""

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
    from orchestrator.status import read_jsonl_lines
except ImportError:
    def read_registry_with_lock(path: str) -> Optional[Dict[str, Any]]:
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            return None

    def find_task_workspace(task_id: str) -> Optional[str]:
        bases = [
            Path.home() / ".agent-workspace",
            Path(__file__).parent.parent.parent.parent.parent / ".agent-workspace"
        ]
        for base in bases:
            task_dir = base / task_id
            if task_dir.exists():
                return str(task_dir)
        return None

    def read_jsonl_lines(path: str) -> List[str]:
        try:
            with open(path, 'r') as f:
                return f.readlines()
        except Exception:
            return []

# Import models
from models.schemas import AgentData, AgentProgress, AgentFinding, TrackedFiles, LogEntry

router = APIRouter()


def parse_agent_data(agent: dict) -> AgentData:
    """Parse agent dictionary into AgentData model."""
    tracked_files = TrackedFiles(
        prompt_file=agent.get("tracked_files", {}).get("prompt_file"),
        log_file=agent.get("tracked_files", {}).get("log_file"),
        progress_file=agent.get("tracked_files", {}).get("progress_file"),
        findings_file=agent.get("tracked_files", {}).get("findings_file"),
        deploy_log=agent.get("tracked_files", {}).get("deploy_log")
    )

    return AgentData(
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
    )


@router.get("/{task_id}", response_model=List[AgentData])
async def list_agents(
    task_id: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    phase_index: Optional[int] = Query(None, description="Filter by phase")
):
    """List all agents for a specific task."""
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

        # Parse agents
        agents = []
        for agent in registry_data.get("agents", []):
            # Apply filters
            if status and agent.get("status") != status:
                continue
            if phase_index is not None and agent.get("phase_index") != phase_index:
                continue

            agents.append(parse_agent_data(agent))

        return agents

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error listing agents for task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}/{agent_id}", response_model=AgentData)
async def get_agent(task_id: str, agent_id: str):
    """Get details for a specific agent."""
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

        # Find specific agent
        for agent in registry_data.get("agents", []):
            if agent["id"] == agent_id:
                return parse_agent_data(agent)

        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error getting agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}/{agent_id}/progress", response_model=List[AgentProgress])
async def get_agent_progress(
    task_id: str,
    agent_id: str,
    limit: int = Query(100, ge=1, le=1000)
):
    """Get progress updates for an agent."""
    try:
        # Find task workspace
        task_workspace = find_task_workspace(task_id)
        if not task_workspace:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        # Read progress file
        progress_file = Path(task_workspace) / "progress" / f"{agent_id}_progress.jsonl"
        if not progress_file.exists():
            return []

        # Read JSONL lines
        lines = read_jsonl_lines(str(progress_file), tail_lines=limit)

        progress_updates = []
        for line in lines:
            try:
                data = json.loads(line)
                progress_updates.append(AgentProgress(
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    agent_id=data["agent_id"],
                    status=data["status"],
                    message=data["message"],
                    progress=data.get("progress", 0)
                ))
            except:
                continue

        return progress_updates

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error getting progress for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}/{agent_id}/findings", response_model=List[AgentFinding])
async def get_agent_findings(
    task_id: str,
    agent_id: str,
    severity: Optional[str] = Query(None, description="Filter by severity"),
    finding_type: Optional[str] = Query(None, description="Filter by type"),
    limit: int = Query(100, ge=1, le=1000)
):
    """Get findings reported by an agent."""
    try:
        # Find task workspace
        task_workspace = find_task_workspace(task_id)
        if not task_workspace:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        # Read findings file
        findings_file = Path(task_workspace) / "findings" / f"{agent_id}_findings.jsonl"
        if not findings_file.exists():
            return []

        # Read JSONL lines
        lines = read_jsonl_lines(str(findings_file), tail_lines=limit)

        findings = []
        for line in lines:
            try:
                data = json.loads(line)

                # Apply filters
                if severity and data.get("severity") != severity:
                    continue
                if finding_type and data.get("finding_type") != finding_type:
                    continue

                findings.append(AgentFinding(
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                    agent_id=data["agent_id"],
                    finding_type=data["finding_type"],
                    severity=data["severity"],
                    message=data["message"],
                    data=data.get("data")
                ))
            except:
                continue

        return findings

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error getting findings for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}/{agent_id}/logs", response_model=List[LogEntry])
async def get_agent_logs(
    task_id: str,
    agent_id: str,
    log_type: Optional[str] = Query(None, description="Filter by log type"),
    limit: int = Query(100, ge=1, le=10000),
    offset: int = Query(0, ge=0)
):
    """Get log entries for an agent."""
    try:
        # Find task workspace
        task_workspace = find_task_workspace(task_id)
        if not task_workspace:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        # Read log file
        log_file = Path(task_workspace) / "logs" / f"{agent_id}_stream.jsonl"
        if not log_file.exists():
            return []

        # Read all lines (we'll implement pagination)
        with open(log_file, 'r') as f:
            lines = f.readlines()

        # Apply offset and limit
        lines = lines[offset:offset + limit]

        log_entries = []
        for line in lines:
            try:
                data = json.loads(line)

                # Apply type filter
                if log_type and data.get("type") != log_type:
                    continue

                log_entry = LogEntry(
                    timestamp=datetime.now(),  # Use current time if not in log
                    type=data.get("type", "unknown"),
                    content=data.get("content"),
                    subtype=data.get("subtype"),
                    tool_name=data.get("tool_name"),
                    parameters=data.get("parameters"),
                    result=data.get("result")
                )

                # Try to extract timestamp from various fields
                if "timestamp" in data:
                    log_entry.timestamp = datetime.fromisoformat(data["timestamp"])

                log_entries.append(log_entry)
            except:
                continue

        return log_entries

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error getting logs for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{task_id}/{agent_id}/output")
async def get_agent_output(
    task_id: str,
    agent_id: str,
    response_format: str = Query("recent", description="Output format: recent, full, compact, summary"),
    recent_lines: int = Query(100, ge=1, le=1000)
):
    """Get agent output using the same format as the MCP tool.

    This endpoint mimics the get_agent_output MCP tool functionality.
    """
    try:
        # Find task workspace
        task_workspace = find_task_workspace(task_id)
        if not task_workspace:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        # Read log file
        log_file = Path(task_workspace) / "logs" / f"{agent_id}_stream.jsonl"
        if not log_file.exists():
            return {
                "output": f"No log file found for agent {agent_id}",
                "metadata": {
                    "file_exists": False,
                    "task_id": task_id,
                    "agent_id": agent_id
                }
            }

        # Get file stats
        file_stats = log_file.stat()

        # Read lines based on format
        if response_format == "recent":
            lines = read_jsonl_lines(str(log_file), tail_lines=recent_lines)
        elif response_format == "full":
            with open(log_file, 'r') as f:
                lines = f.readlines()
        elif response_format == "compact":
            lines = read_jsonl_lines(str(log_file), tail_lines=50)
        else:  # summary
            lines = read_jsonl_lines(str(log_file), tail_lines=20)

        # Format output
        output_text = ""
        for line in lines:
            try:
                data = json.loads(line)
                if data.get("type") == "assistant" and data.get("content"):
                    output_text += f"[Assistant]: {data['content']}\n"
                elif data.get("type") == "tool_call":
                    output_text += f"[Tool Call]: {data.get('tool_name', 'unknown')}\n"
                elif data.get("type") == "tool_result":
                    result = str(data.get("result", ""))[:200]  # Truncate large results
                    output_text += f"[Tool Result]: {result}...\n"
            except:
                continue

        return {
            "output": output_text or "No output available",
            "metadata": {
                "file_exists": True,
                "file_size": file_stats.st_size,
                "lines_read": len(lines),
                "response_format": response_format,
                "task_id": task_id,
                "agent_id": agent_id
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[API] Error getting output for agent {agent_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))