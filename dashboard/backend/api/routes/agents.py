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
    from orchestrator import state_db
except ImportError:
    # Provide fallback state_db module with None functions
    class state_db_fallback:
        @staticmethod
        def get_agent_by_id(**kwargs):
            return None
        @staticmethod
        def get_agents_for_task(**kwargs):
            return None
    state_db = state_db_fallback()

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

    def read_jsonl_lines(path: str, max_lines: Optional[int] = None, tail_lines: int = 100) -> List[str]:
        """Read JSONL file, returning at most N lines (fallback implementation)."""
        try:
            with open(path, 'r') as f:
                lines = f.readlines()
                limit = max_lines if max_lines is not None else tail_lines
                if limit and len(lines) > limit:
                    return lines[-limit:]
                return lines
        except Exception:
            return []

# Import models
from models.schemas import AgentData, AgentProgress, AgentFinding, TrackedFiles, LogEntry

router = APIRouter()

# Define workspace base path - used for state_db
WORKSPACE_BASE = Path.home() / ".agent-workspace"

def _get_workspace_base(task_workspace: str) -> str:
    """Extract workspace base from task workspace path."""
    task_path = Path(task_workspace)
    # Go up one level from task directory to get workspace base
    return str(task_path.parent)

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


def _normalize_agent_status(status: Any, progress: Any = None) -> str:
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


def _read_last_progress(task_workspace: str, agent_id: str) -> Optional[Dict[str, Any]]:
    try:
        if not task_workspace or not agent_id:
            return None
        progress_file = Path(task_workspace) / "progress" / f"{agent_id}_progress.jsonl"
        if not progress_file.exists():
            return None
        from collections import deque

        tail = deque(maxlen=20)
        with open(progress_file, "r", encoding="utf-8", errors="ignore") as f:
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


def _read_jsonl_tail(path: Path, max_lines: int) -> List[str]:
    """Read up to the last N non-empty lines from a JSONL file."""
    try:
        if max_lines <= 0 or not path.exists():
            return []
        from collections import deque

        tail = deque(maxlen=max_lines)
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line:
                    tail.append(line)
        return list(tail)
    except Exception:
        return []


def _resolve_tracked_file(task_workspace: str, agent_id: str, key: str, fallback: Path) -> Path:
    """Resolve a tracked file path from state_db first, then AGENT_REGISTRY.json, falling back to default paths including archive."""
    try:
        # Extract task_id from task_workspace path
        task_id = Path(task_workspace).name
        workspace_base = _get_workspace_base(task_workspace)

        # Try SQLite state_db first
        agent_data = state_db.get_agent_by_id(
            workspace_base=workspace_base,
            task_id=task_id,
            agent_id=agent_id
        )

        if agent_data:
            # Agent found in SQLite - use tracked_files from there
            tracked = agent_data.get("tracked_files") or {}
            tracked_path = tracked.get(key)
            if tracked_path:
                p = Path(tracked_path)
                if p.exists():
                    return p
                # Check archive directory as fallback (files may be moved after completion)
                archive_path = Path(task_workspace) / "archive" / p.name
                if archive_path.exists():
                    return archive_path
        else:
            # Fallback to JSON registry only if SQLite unavailable
            registry_path = Path(task_workspace) / "AGENT_REGISTRY.json"
            if registry_path.exists():
                registry = read_registry_with_lock(str(registry_path)) or {}
                for agent in registry.get("agents", []) or []:
                    if (agent.get("id") or agent.get("agent_id")) == agent_id:
                        tracked = agent.get("tracked_files") or {}
                        tracked_path = tracked.get(key)
                        if tracked_path:
                            p = Path(tracked_path)
                            if p.exists():
                                return p
                            # Check archive directory as fallback (files may be moved after completion)
                            archive_path = Path(task_workspace) / "archive" / p.name
                            if archive_path.exists():
                                return archive_path
    except Exception:
        pass

    # Check if fallback exists, otherwise check archive
    if fallback.exists():
        return fallback
    archive_fallback = Path(task_workspace) / "archive" / fallback.name
    if archive_fallback.exists():
        return archive_fallback
    return fallback


def parse_agent_data(agent: dict, task_workspace: Optional[str] = None) -> AgentData:
    """Parse agent dictionary into AgentData model."""
    # JSONL is the source of truth for status/progress/last_update (registry can drift).
    agent_id = agent.get("id") or agent.get("agent_id") or ""
    if task_workspace:
        last_progress = _read_last_progress(task_workspace, agent_id)
        if last_progress:
            agent = dict(agent)
            # Normalize to match the API schema literals.
            merged_progress = last_progress.get("progress", agent.get("progress", 0))
            merged_status = last_progress.get("status") or agent.get("status")
            agent["progress"] = merged_progress
            agent["status"] = _normalize_agent_status(merged_status, merged_progress)

            ts = last_progress.get("timestamp")
            if ts:
                agent["last_update"] = ts
                if agent["status"] == "completed":
                    agent["completed_at"] = agent.get("completed_at") or ts

    # Ensure registry-only statuses don't violate the schema.
    agent = dict(agent)
    agent["status"] = _normalize_agent_status(agent.get("status"), agent.get("progress", 0))

    tracked_files = TrackedFiles(
        prompt_file=agent.get("tracked_files", {}).get("prompt_file"),
        log_file=agent.get("tracked_files", {}).get("log_file"),
        progress_file=agent.get("tracked_files", {}).get("progress_file"),
        findings_file=agent.get("tracked_files", {}).get("findings_file"),
        deploy_log=agent.get("tracked_files", {}).get("deploy_log")
    )

    return AgentData(
        id=agent_id or agent["id"],
        type=agent.get("type") or agent.get("agent_type") or "unknown",
        tmux_session=agent.get("tmux_session", ""),
        parent=agent.get("parent", "orchestrator"),
        depth=agent.get("depth", 1),
        phase_index=agent.get("phase_index", 0),
        status=agent.get("status", "working"),
        started_at=datetime.fromisoformat(agent["started_at"]),
        completed_at=datetime.fromisoformat(agent["completed_at"]) if agent.get("completed_at") else None,
        progress=agent.get("progress", 0),
        last_update=datetime.fromisoformat(agent.get("last_update") or agent["started_at"]),
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

        workspace_base = _get_workspace_base(task_workspace)

        # Try SQLite state_db first
        agents_from_db = state_db.get_agents_for_task(
            workspace_base=workspace_base,
            task_id=task_id
        )

        if agents_from_db:
            # Use SQLite data
            agents = []
            for agent in agents_from_db:
                # Convert SQLite dict to match expected format for parse_agent_data
                # SQLite returns flat dict, we need to ensure compatibility
                agent_dict = dict(agent)

                # Ensure 'id' field exists (SQLite uses 'agent_id')
                if 'agent_id' in agent_dict and 'id' not in agent_dict:
                    agent_dict['id'] = agent_dict['agent_id']

                agent_data = parse_agent_data(agent_dict, task_workspace)

                # Apply filters based on JSONL-derived state.
                if status and agent_data.status != status:
                    continue
                if phase_index is not None and agent_data.phase_index != phase_index:
                    continue

                agents.append(agent_data)
        else:
            # Fallback to JSON registry only if SQLite unavailable
            registry_path = Path(task_workspace) / "AGENT_REGISTRY.json"
            if not registry_path.exists():
                raise HTTPException(status_code=404, detail=f"Task registry not found")

            registry_data = read_registry_with_lock(str(registry_path))
            if not registry_data:
                raise HTTPException(status_code=500, detail="Failed to read task registry")

            # Parse agents
            agents = []
            for agent in registry_data.get("agents", []):
                agent_data = parse_agent_data(agent, task_workspace)

                # Apply filters based on JSONL-derived state.
                if status and agent_data.status != status:
                    continue
                if phase_index is not None and agent_data.phase_index != phase_index:
                    continue

                agents.append(agent_data)

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

        workspace_base = _get_workspace_base(task_workspace)

        # Try SQLite state_db first
        agent_from_db = state_db.get_agent_by_id(
            workspace_base=workspace_base,
            task_id=task_id,
            agent_id=agent_id
        )

        if agent_from_db:
            # Use SQLite data
            # Convert SQLite dict to match expected format for parse_agent_data
            agent_dict = dict(agent_from_db)

            # Ensure 'id' field exists (SQLite uses 'agent_id')
            if 'agent_id' in agent_dict and 'id' not in agent_dict:
                agent_dict['id'] = agent_dict['agent_id']

            return parse_agent_data(agent_dict, task_workspace)
        else:
            # Fallback to JSON registry only if SQLite unavailable
            registry_path = Path(task_workspace) / "AGENT_REGISTRY.json"
            if not registry_path.exists():
                raise HTTPException(status_code=404, detail=f"Task registry not found")

            registry_data = read_registry_with_lock(str(registry_path))
            if not registry_data:
                raise HTTPException(status_code=500, detail="Failed to read task registry")

            # Find specific agent
            for agent in registry_data.get("agents", []):
                if agent["id"] == agent_id:
                    return parse_agent_data(agent, task_workspace)

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

        # Read progress file (tracked_files is preferred; registry paths can differ across installs).
        progress_file = _resolve_tracked_file(
            task_workspace,
            agent_id,
            "progress_file",
            Path(task_workspace) / "progress" / f"{agent_id}_progress.jsonl",
        )
        if not progress_file.exists():
            return []

        # Read JSONL lines (tail, so UI gets the most recent updates).
        lines = _read_jsonl_tail(progress_file, limit)

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

        # Read findings file (tracked_files is preferred; registry paths can differ across installs).
        findings_file = _resolve_tracked_file(
            task_workspace,
            agent_id,
            "findings_file",
            Path(task_workspace) / "findings" / f"{agent_id}_findings.jsonl",
        )
        if not findings_file.exists():
            return []

        # Read JSONL lines (tail, so UI gets the most recent findings).
        lines = _read_jsonl_tail(findings_file, limit)

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

        # Read log file (tracked_files is preferred; registry paths can differ across installs).
        log_file = _resolve_tracked_file(
            task_workspace,
            agent_id,
            "log_file",
            Path(task_workspace) / "logs" / f"{agent_id}_stream.jsonl",
        )
        if not log_file.exists():
            return []

        # Default behavior: return the most recent logs (tail).
        if offset == 0:
            lines = _read_jsonl_tail(log_file, limit)
        else:
            with open(log_file, 'r', encoding="utf-8", errors="ignore") as f:
                all_lines = f.readlines()
            lines = all_lines[offset:offset + limit]

        log_entries = []
        for line in lines:
            try:
                data = json.loads(line)

                # Apply type filter
                if log_type and data.get("type") != log_type:
                    continue

                # Extract content from nested message structure (Claude Code JSONL format)
                content = None
                tool_name = None
                parameters = None
                result = None
                subtype = data.get("subtype")

                msg = data.get("message", {})
                msg_content = msg.get("content", [])

                if isinstance(msg_content, list):
                    for item in msg_content:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                content = item.get("text", "")
                            elif item.get("type") == "tool_use":
                                tool_name = item.get("name")
                                parameters = item.get("input")
                                if not content:
                                    content = f"Tool call: {tool_name}"
                            elif item.get("type") == "tool_result":
                                result = item.get("content", "")
                                # Store full result for metadata, only truncate display content
                                if not content:
                                    # Try to extract guidance from MCP tool results
                                    guidance_display = ""
                                    if isinstance(result, str):
                                        try:
                                            parsed = json.loads(result)
                                            if isinstance(parsed, dict):
                                                # Extract guidance fields for prominent display
                                                if "guidance" in parsed:
                                                    g = parsed["guidance"]
                                                    if isinstance(g, dict) and g.get("action"):
                                                        guidance_display = f" | GUIDANCE: {g['action']}"
                                                elif "coordination_guidance" in parsed:
                                                    g = parsed["coordination_guidance"]
                                                    if isinstance(g, dict) and g.get("message"):
                                                        guidance_display = f" | GUIDANCE: {g['message'][:100]}"
                                        except (json.JSONDecodeError, TypeError):
                                            pass
                                    content = f"Tool result: {str(result)[:300]}{guidance_display}"

                # Fallback to direct content field
                if not content:
                    content = data.get("content")

                # For tool_result in user messages, extract the content with guidance
                if data.get("type") == "user" and isinstance(msg_content, list):
                    for item in msg_content:
                        if isinstance(item, dict) and item.get("type") == "tool_result":
                            result_content = item.get("content", "")
                            result = result_content

                            # Extract guidance from MCP tool results for display
                            guidance_display = ""
                            if isinstance(result_content, str):
                                try:
                                    parsed = json.loads(result_content)
                                    if isinstance(parsed, dict):
                                        if "guidance" in parsed:
                                            g = parsed["guidance"]
                                            if isinstance(g, dict) and g.get("action"):
                                                guidance_display = f" | GUIDANCE: {g['action']}"
                                        elif "coordination_guidance" in parsed:
                                            g = parsed["coordination_guidance"]
                                            if isinstance(g, dict) and g.get("message"):
                                                guidance_display = f" | GUIDANCE: {g['message'][:100]}"
                                        if "important_reminder" in parsed:
                                            guidance_display += " | REMINDER: completion required"
                                except (json.JSONDecodeError, TypeError):
                                    pass

                            truncated = result_content[:400] if result_content else "(empty)"
                            content = f"Tool result: {truncated}{guidance_display}"

                # For system init messages
                if data.get("type") == "system" and subtype == "init":
                    content = f"Session initialized (model: {data.get('model', 'unknown')}, tools: {len(data.get('tools', []))})"

                # Normalize type to valid Literal values
                raw_type = data.get("type", "system")
                valid_types = {"system", "user", "assistant", "tool_call", "tool_result"}
                entry_type = raw_type if raw_type in valid_types else "system"

                log_entry = LogEntry(
                    timestamp=datetime.now(),  # Use current time if not in log
                    type=entry_type,
                    content=content or "",  # Ensure content is never None
                    subtype=subtype,
                    tool_name=tool_name,
                    parameters=parameters,
                    result=result
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
            lines = _read_jsonl_tail(log_file, recent_lines)
        elif response_format == "full":
            with open(log_file, 'r') as f:
                lines = f.readlines()
        elif response_format == "compact":
            lines = _read_jsonl_tail(log_file, 50)
        else:  # summary
            lines = _read_jsonl_tail(log_file, 20)

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
                    result_str = str(data.get("result", ""))
                    # Extract guidance from MCP results
                    guidance = ""
                    try:
                        parsed = json.loads(result_str) if isinstance(result_str, str) else result_str
                        if isinstance(parsed, dict):
                            if "guidance" in parsed and isinstance(parsed["guidance"], dict):
                                guidance = f" | GUIDANCE: {parsed['guidance'].get('action', '')}"
                            elif "coordination_guidance" in parsed:
                                guidance = f" | GUIDANCE: {parsed['coordination_guidance'].get('message', '')[:80]}"
                    except:
                        pass
                    output_text += f"[Tool Result]: {result_str[:300]}{guidance}\n"
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
