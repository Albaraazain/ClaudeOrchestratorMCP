"""
Agent Lifecycle Management Module

Handles agent lifecycle operations including:
- Terminating agents (kill_real_agent)
- Resource cleanup (cleanup_agent_resources)
- Progress updates (update_agent_progress)
- Finding reports (report_agent_finding)
- Child agent spawning (spawn_child_agent)
- Completion validation (validate_agent_completion)
- Minimal coordination info (get_minimal_coordination_info)

Dependencies:
- registry: read_registry_with_lock, write_registry_with_lock
- workspace: find_task_workspace, get_workspace_base_from_task_workspace, get_global_registry_path
- tmux: check_tmux_session_exists, kill_tmux_session
"""

import os
import json
import time
import subprocess
import logging
import shutil
import glob
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# These will be imported from sibling modules once they're created
# For now, we define placeholders that will be replaced with actual imports

# Configuration - Claude CLI with tmux only

__all__ = [
    'kill_real_agent',
    'cleanup_agent_resources',
    'update_agent_progress',
    'report_agent_finding',
    'spawn_child_agent',
    'get_minimal_coordination_info',
    'get_comprehensive_coordination_info',
    'validate_agent_completion',
]


def kill_real_agent(
    task_id: str,
    agent_id: str,
    reason: str = "Manual termination",
    # Dependency injection for modularity
    find_task_workspace=None,
    read_registry_with_lock=None,
    write_registry_with_lock=None,
    check_tmux_session_exists=None,
    kill_tmux_session=None,
    get_workspace_base_from_task_workspace=None,
    get_global_registry_path=None,
) -> Dict[str, Any]:
    """
    Terminate a running agent (tmux session).

    Args:
        task_id: Task containing the agent
        agent_id: Agent to terminate
        reason: Reason for termination

    Returns:
        Termination status
    """
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }

    registry_path = f"{workspace}/AGENT_REGISTRY.json"

    # Read registry with file locking to prevent race conditions
    registry = read_registry_with_lock(registry_path)

    # Find agent
    agent = None
    for a in registry['agents']:
        if a['id'] == agent_id:
            agent = a
            break

    if not agent:
        return {
            "success": False,
            "error": f"Agent {agent_id} not found"
        }

    try:
        # Kill tmux session
        session_name = agent.get('tmux_session')

        # Perform comprehensive resource cleanup using cleanup_agent_resources
        cleanup_result = cleanup_agent_resources(
            workspace=workspace,
            agent_id=agent_id,
            agent_data=agent,
            keep_logs=True,  # Archive logs instead of deleting
            check_tmux_session_exists=check_tmux_session_exists,
            kill_tmux_session=kill_tmux_session,
        )

        # Track cleanup status
        killed = cleanup_result.get('tmux_session_killed', False)

        # Update registry
        previous_status = agent.get('status')
        agent['status'] = 'terminated'
        agent['terminated_at'] = datetime.now().isoformat()
        agent['termination_reason'] = reason

        # Only decrement if agent was in active status
        active_statuses = ['running', 'working', 'blocked']
        if previous_status in active_statuses:
            registry['active_count'] = max(0, registry['active_count'] - 1)

        # Write registry with file locking to prevent race conditions
        write_registry_with_lock(registry_path, registry)

        # Update global registry
        try:
            workspace_base = get_workspace_base_from_task_workspace(workspace)
            global_reg_path = get_global_registry_path(workspace_base)
            if os.path.exists(global_reg_path):
                # Read global registry with file locking
                global_reg = read_registry_with_lock(global_reg_path)

                if agent_id in global_reg.get('agents', {}):
                    global_reg['agents'][agent_id]['status'] = 'terminated'
                    global_reg['agents'][agent_id]['terminated_at'] = datetime.now().isoformat()
                    global_reg['agents'][agent_id]['termination_reason'] = reason

                    # Only decrement if agent was in active status
                    if previous_status in active_statuses:
                        global_reg['active_agents'] = max(0, global_reg.get('active_agents', 0) - 1)

                    # Write global registry with file locking
                    write_registry_with_lock(global_reg_path, global_reg)
        except Exception as e:
            logger.error(f"Failed to update global registry on termination: {e}")

        return {
            "success": True,
            "agent_id": agent_id,
            "tmux_session": session_name,
            "session_killed": killed,
            "reason": reason,
            "status": "terminated",
            "cleanup": cleanup_result
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to terminate agent: {str(e)}"
        }


def cleanup_agent_resources(
    workspace: str,
    agent_id: str,
    agent_data: Dict[str, Any],
    keep_logs: bool = True,
    # Dependency injection
    check_tmux_session_exists=None,
    kill_tmux_session=None,
) -> Dict[str, Any]:
    """
    Clean up all resources associated with a completed/terminated agent.

    This function performs comprehensive cleanup of:
    - Tmux session (if still running)
    - JSONL log file handles (flush and close)
    - Temporary prompt files
    - Progress/findings JSONL files (archive or delete)
    - Verification of zombie processes

    Args:
        workspace: Task workspace path (e.g., .agent-workspace/TASK-xxx)
        agent_id: Agent ID to clean up
        agent_data: Agent registry data dictionary
        keep_logs: If True, archive logs to workspace/archive/. If False, delete them.

    Returns:
        Dict with cleanup results for each resource type:
        {
            "success": True/False,
            "tmux_session_killed": True/False,
            "prompt_file_deleted": True/False,
            "log_files_archived": True/False,
            "verified_no_zombies": True/False,
            "errors": [...],  # List of any errors encountered
            "archived_files": [...]  # List of archived file paths
        }
    """
    cleanup_results = {
        "success": True,
        "tmux_session_killed": False,
        "prompt_file_deleted": False,
        "log_files_archived": False,
        "verified_no_zombies": False,
        "errors": [],
        "archived_files": []
    }

    try:
        # 1. Kill tmux session if still running with retry mechanism
        session_name = agent_data.get('tmux_session')
        if session_name and check_tmux_session_exists and kill_tmux_session:
            if check_tmux_session_exists(session_name):
                logger.info(f"Cleanup: Killing tmux session {session_name} for agent {agent_id}")
                killed = kill_tmux_session(session_name)

                if killed:
                    # Retry mechanism with escalating delays to ensure processes terminate
                    max_retries = 3
                    retry_delays = [0.5, 1.0, 2.0]  # Escalating delays in seconds
                    processes_terminated = False

                    for attempt in range(max_retries):
                        time.sleep(retry_delays[attempt])

                        # Check if processes still exist
                        try:
                            ps_result = subprocess.run(
                                ['ps', 'aux'],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )

                            if ps_result.returncode == 0:
                                agent_processes = [
                                    line for line in ps_result.stdout.split('\n')
                                    if agent_id in line and 'claude' in line.lower()
                                ]

                                if len(agent_processes) == 0:
                                    processes_terminated = True
                                    cleanup_results["tmux_session_killed"] = True
                                    logger.info(f"Cleanup: Verified processes terminated for {agent_id} after {attempt + 1} attempt(s)")
                                    break
                                elif attempt < max_retries - 1:
                                    logger.warning(f"Cleanup: Found {len(agent_processes)} processes for {agent_id}, waiting (attempt {attempt + 1}/{max_retries})")
                                else:
                                    # Final attempt: escalate to SIGKILL for stubborn processes
                                    logger.error(f"Cleanup: Processes won't die gracefully, escalating to SIGKILL for {agent_id}")
                                    killed_count = 0
                                    for proc_line in agent_processes:
                                        try:
                                            # Extract PID (second column in ps aux output)
                                            pid = int(proc_line.split()[1])
                                            os.kill(pid, 9)  # SIGKILL
                                            killed_count += 1
                                            logger.info(f"Cleanup: Sent SIGKILL to process {pid}")
                                        except (ValueError, IndexError, ProcessLookupError, PermissionError) as e:
                                            logger.warning(f"Cleanup: Failed to kill process: {e}")

                                    if killed_count > 0:
                                        # Wait briefly after SIGKILL
                                        time.sleep(0.5)
                                        cleanup_results["tmux_session_killed"] = True
                                        cleanup_results["escalated_to_sigkill"] = True
                                        logger.warning(f"Cleanup: Escalated to SIGKILL for {killed_count} processes")
                            else:
                                logger.warning(f"Cleanup: ps command failed with return code {ps_result.returncode}")
                        except subprocess.TimeoutExpired:
                            logger.warning(f"Cleanup: ps command timed out during retry {attempt + 1}")
                        except Exception as e:
                            logger.warning(f"Cleanup: Error checking processes during retry {attempt + 1}: {e}")

                    if not processes_terminated and not cleanup_results.get("escalated_to_sigkill"):
                        cleanup_results["tmux_session_killed"] = False
                        cleanup_results["errors"].append(f"Failed to verify process termination for {agent_id} after {max_retries} retries")
                else:
                    cleanup_results["tmux_session_killed"] = False
                    cleanup_results["errors"].append(f"Failed to kill tmux session {session_name}")
            else:
                # Session already gone
                cleanup_results["tmux_session_killed"] = True
                logger.info(f"Cleanup: Tmux session {session_name} already terminated")

        # 2. Delete temporary prompt file (no longer needed after agent starts)
        prompt_file = os.path.abspath(f"{workspace}/agent_prompt_{agent_id}.txt")
        if os.path.exists(prompt_file):
            try:
                os.remove(prompt_file)
                cleanup_results["prompt_file_deleted"] = True
                logger.info(f"Cleanup: Deleted prompt file {prompt_file}")
            except Exception as e:
                error_msg = f"Failed to delete prompt file {prompt_file}: {e}"
                cleanup_results["errors"].append(error_msg)
                logger.warning(error_msg)
        else:
            # Prompt file already deleted or never existed
            cleanup_results["prompt_file_deleted"] = True

        # 3. Archive or delete JSONL log files
        logs_dir = f"{workspace}/logs"
        progress_dir = f"{workspace}/progress"
        findings_dir = f"{workspace}/findings"

        files_to_process = [
            (f"{logs_dir}/{agent_id}_stream.jsonl", "stream log"),
            (f"{progress_dir}/{agent_id}_progress.jsonl", "progress log"),
            (f"{findings_dir}/{agent_id}_findings.jsonl", "findings log")
        ]

        if keep_logs:
            # Archive logs to workspace/archive/ directory
            archive_dir = f"{workspace}/archive"
            try:
                os.makedirs(archive_dir, exist_ok=True)
                logger.info(f"Cleanup: Created archive directory {archive_dir}")
            except Exception as e:
                error_msg = f"Failed to create archive directory {archive_dir}: {e}"
                cleanup_results["errors"].append(error_msg)
                logger.error(error_msg)
                keep_logs = False  # Fall back to deletion if archiving fails

            if keep_logs:
                # CRITICAL FIX: Give time for any writing processes to finish and flush buffers
                # JSONL writers may have buffered data not yet written to disk
                # Without this sleep, shutil.move can cause data corruption or incomplete logs
                time.sleep(0.2)
                logger.info("Cleanup: Waited 200ms for file handles to flush before archiving")

                for src_path, file_type in files_to_process:
                    if os.path.exists(src_path):
                        dst_path = f"{archive_dir}/{os.path.basename(src_path)}"
                        try:
                            # Verify file is not currently being written to by checking size stability
                            initial_size = os.path.getsize(src_path)
                            time.sleep(0.05)  # Brief check
                            final_size = os.path.getsize(src_path)

                            if initial_size != final_size:
                                # File still being written, wait a bit more
                                logger.warning(f"Cleanup: {file_type} still being written, waiting...")
                                time.sleep(0.2)

                            shutil.move(src_path, dst_path)
                            cleanup_results["archived_files"].append(dst_path)
                            logger.info(f"Cleanup: Archived {file_type} to {dst_path}")
                        except OSError as e:
                            # File locked, permission denied, or other OS-level issues
                            error_msg = f"OS error archiving {file_type} {src_path}: {e}"
                            cleanup_results["errors"].append(error_msg)
                            logger.warning(error_msg)
                        except Exception as e:
                            error_msg = f"Failed to archive {file_type} {src_path}: {e}"
                            cleanup_results["errors"].append(error_msg)
                            logger.warning(error_msg)

                # Mark successful if at least one file was archived
                cleanup_results["log_files_archived"] = len(cleanup_results["archived_files"]) > 0
        else:
            # Delete log files instead of archiving
            for src_path, file_type in files_to_process:
                if os.path.exists(src_path):
                    try:
                        os.remove(src_path)
                        logger.info(f"Cleanup: Deleted {file_type} {src_path}")
                    except Exception as e:
                        error_msg = f"Failed to delete {file_type} {src_path}: {e}"
                        cleanup_results["errors"].append(error_msg)
                        logger.warning(error_msg)

            cleanup_results["log_files_archived"] = True  # Deletion counts as "processed"

        # 4. Verify no zombie processes remain
        # Check for lingering Claude processes tied to this agent
        try:
            ps_result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if ps_result.returncode == 0:
                # Look for processes containing both agent_id and 'claude'
                agent_processes = [
                    line for line in ps_result.stdout.split('\n')
                    if agent_id in line and 'claude' in line.lower()
                ]

                if len(agent_processes) == 0:
                    cleanup_results["verified_no_zombies"] = True
                    logger.info(f"Cleanup: Verified no zombie processes for agent {agent_id}")
                else:
                    warning_msg = f"Found {len(agent_processes)} lingering processes for agent {agent_id}"
                    cleanup_results["errors"].append(warning_msg)
                    cleanup_results["zombie_processes"] = len(agent_processes)
                    cleanup_results["zombie_process_details"] = agent_processes[:3]  # First 3 for debugging
                    logger.warning(f"Cleanup: {warning_msg}")
            else:
                error_msg = f"ps command failed with return code {ps_result.returncode}"
                cleanup_results["errors"].append(error_msg)
                logger.warning(f"Cleanup: {error_msg}")
        except subprocess.TimeoutExpired:
            error_msg = "ps command timed out after 5 seconds"
            cleanup_results["errors"].append(error_msg)
            logger.warning(f"Cleanup: {error_msg}")
        except Exception as e:
            error_msg = f"Failed to verify zombie processes: {e}"
            cleanup_results["errors"].append(error_msg)
            logger.warning(f"Cleanup: {error_msg}")

        # 5. Determine overall success
        # Success if critical operations completed (tmux killed, files processed)
        critical_operations = [
            cleanup_results["tmux_session_killed"],
            cleanup_results["prompt_file_deleted"],
            cleanup_results["log_files_archived"]
        ]
        cleanup_results["success"] = all(critical_operations)

        if cleanup_results["success"]:
            logger.info(f"Cleanup: Successfully cleaned up all resources for agent {agent_id}")
        else:
            logger.warning(f"Cleanup: Partial cleanup for agent {agent_id}, errors: {cleanup_results['errors']}")

        return cleanup_results

    except Exception as e:
        # Catch-all for unexpected errors
        error_msg = f"Unexpected error during cleanup: {str(e)}"
        logger.error(f"Cleanup: {error_msg}")
        cleanup_results["success"] = False
        cleanup_results["errors"].append(error_msg)
        return cleanup_results


def get_minimal_coordination_info(
    task_id: str,
    # Dependency injection
    find_task_workspace=None,
) -> Dict[str, Any]:
    """
    Get minimal coordination info for MCP tool responses.
    Returns only essential data to prevent log bloat (1-2KB vs 35KB+).

    Returns:
    - success status
    - recent_findings (last 3 only)
    - agent_count summary

    Excludes:
    - Full agent prompts (multi-KB each)
    - Full progress history
    - Full findings history
    - Complete agent status details

    Args:
        task_id: Task ID

    Returns:
        Minimal coordination data (~1-2KB)
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {"success": False, "error": f"Task {task_id} not found"}

    registry_path = f"{workspace}/AGENT_REGISTRY.json"

    try:
        with open(registry_path, 'r') as f:
            registry = json.load(f)
    except:
        return {"success": False, "error": "Failed to read registry"}

    def _read_last_jsonl_entry(filepath: str) -> Optional[Dict[str, Any]]:
        try:
            if not os.path.exists(filepath):
                return None
            from collections import deque

            tail = deque(maxlen=20)
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
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

    # Read only recent findings (last 3)
    recent_findings = []
    findings_dir = f"{workspace}/findings"
    if os.path.exists(findings_dir):
        all_findings = []
        for file in os.listdir(findings_dir):
            if file.endswith('_findings.jsonl'):
                try:
                    with open(f"{findings_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    all_findings.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue

        all_findings.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        recent_findings = all_findings[:3]  # Only last 3

    # JSONL is the source of truth for agent status/progress.
    active_statuses = {"running", "working", "blocked", "reviewing"}
    total_agents = len(registry.get("agents", []))
    active = 0
    completed = 0
    for agent in registry.get("agents", []):
        agent_id = agent.get("id", "")
        status = agent.get("status")
        if agent_id:
            last = _read_last_jsonl_entry(f"{workspace}/progress/{agent_id}_progress.jsonl")
            if last and last.get("status"):
                status = last["status"]
        if status == "completed":
            completed += 1
        if status in active_statuses:
            active += 1

    return {
        "success": True,
        "task_id": task_id,
        "agent_counts": {
            "total_spawned": max(registry.get("total_spawned", 0), total_agents),
            "active": active,
            "completed": completed
        },
        "recent_findings": recent_findings
    }


def get_comprehensive_coordination_info(
    task_id: str,
    max_findings_per_agent: int = 10,
    max_progress_per_agent: int = 5,
    # Dependency injection
    find_task_workspace=None,
) -> Dict[str, Any]:
    """
    Get comprehensive coordination info for enhanced agent collaboration.
    Returns ALL peer data to enable full visibility and prevent duplicate work.

    Returns:
    - Full agent status details (who's working on what)
    - ALL findings grouped by agent (up to max_findings_per_agent per agent)
    - Recent progress from all agents (up to max_progress_per_agent per agent)
    - Summary of work distribution

    This enables agents to:
    - See everything peers have discovered
    - Understand current work distribution
    - Avoid duplicate investigations
    - Build on others' findings

    Args:
        task_id: Task ID
        max_findings_per_agent: Max findings to include per agent (default 10)
        max_progress_per_agent: Max progress updates per agent (default 5)

    Returns:
        Comprehensive coordination data for LLM consumption
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {"success": False, "error": f"Task {task_id} not found"}

    registry_path = f"{workspace}/AGENT_REGISTRY.json"

    try:
        with open(registry_path, 'r') as f:
            registry = json.load(f)
    except:
        return {"success": False, "error": "Failed to read registry"}

    # 1. Get all agents with current status
    agents_status = []
    for agent in registry.get('agents', []):
        agents_status.append({
            "id": agent.get("id"),
            "type": agent.get("type"),
            "status": agent.get("status"),
            "progress": agent.get("progress", 0),
            "last_update": agent.get("last_update"),
            "parent": agent.get("parent", "orchestrator")
        })

    # 2. Get ALL findings grouped by agent
    findings_by_agent = {}
    findings_dir = f"{workspace}/findings"
    if os.path.exists(findings_dir):
        for file in os.listdir(findings_dir):
            if file.endswith('_findings.jsonl'):
                agent_id = file.replace('_findings.jsonl', '')
                agent_findings = []
                try:
                    with open(f"{findings_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    agent_findings.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue

                # Sort by timestamp and limit
                agent_findings.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
                findings_by_agent[agent_id] = agent_findings[:max_findings_per_agent]

    # 3. Get recent progress from all agents
    progress_by_agent = {}
    progress_dir = f"{workspace}/progress"
    if os.path.exists(progress_dir):
        for file in os.listdir(progress_dir):
            if file.endswith('_progress.jsonl'):
                agent_id = file.replace('_progress.jsonl', '')
                agent_progress = []
                try:
                    with open(f"{progress_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    agent_progress.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue

                # Sort by timestamp and get recent ones
                agent_progress.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
                progress_by_agent[agent_id] = agent_progress[:max_progress_per_agent]

    # 4. Create work distribution summary
    work_summary = {
        "total_agents": len(agents_status),
        "active_agents": len([a for a in agents_status if a.get("status") in ["working", "running", "blocked"]]),
        "completed_agents": len([a for a in agents_status if a.get("status") == "completed"]),
        "blocked_agents": len([a for a in agents_status if a.get("status") == "blocked"]),
        "total_findings": sum(len(findings) for findings in findings_by_agent.values()),
        "agents_with_findings": len(findings_by_agent)
    }

    return {
        "success": True,
        "task_id": task_id,
        "work_summary": work_summary,
        "agents": agents_status,
        "findings_by_agent": findings_by_agent,
        "progress_by_agent": progress_by_agent,
        "coordination_data": {
            "message": "Full peer visibility enabled for comprehensive coordination",
            "total_findings_available": sum(len(f) for f in findings_by_agent.values()),
            "total_progress_available": sum(len(p) for p in progress_by_agent.values())
        }
    }


def validate_agent_completion(
    workspace: str,
    agent_id: str,
    agent_type: str,
    message: str,
    registry: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Validate agent completion claims with 4-layer validation.
    Architecture designed by architect-184627-99b952.

    Layers:
    1. Workspace evidence (files modified, findings reported)
    2. Type-specific validation (different requirements per agent type)
    3. Message content validation (evidence keywords, minimum length)
    4. Progress pattern validation (detect fake progress)

    Args:
        workspace: Task workspace path
        agent_id: Agent claiming completion
        agent_type: Type of agent (investigator, builder, fixer, etc.)
        message: Completion message
        registry: Task registry with agent data

    Returns:
        {
            "valid": bool,
            "confidence": float (0-1),
            "warnings": list[str],
            "blocking_issues": list[str],
            "evidence_summary": dict
        }
    """
    warnings = []
    blocking_issues = []
    evidence_summary = {}

    # Find agent in registry
    agent = None
    for a in registry.get('agents', []):
        if a['id'] == agent_id:
            agent = a
            break

    if not agent:
        blocking_issues.append(f"Agent {agent_id} not found in registry")
        return {
            "valid": False,
            "confidence": 0.0,
            "warnings": warnings,
            "blocking_issues": blocking_issues,
            "evidence_summary": evidence_summary
        }

    agent_start_time = agent.get('started_at')
    if not agent_start_time:
        warnings.append("Agent has no start time recorded")

    # LAYER 1: Workspace Evidence Checks
    evidence_summary['workspace_evidence'] = {}

    # Check for files created/modified in workspace
    modified_files = []
    try:
        from datetime import datetime as dt
        workspace_files = glob.glob(f'{workspace}/**/*', recursive=True)
        if agent_start_time:
            start_dt = dt.fromisoformat(agent_start_time.replace('Z', '+00:00'))
            for f in workspace_files:
                if os.path.isfile(f):
                    try:
                        if os.path.getmtime(f) > start_dt.timestamp():
                            modified_files.append(f)
                    except:
                        pass
        evidence_summary['workspace_evidence']['modified_files_count'] = len(modified_files)

        if len(modified_files) == 0:
            warnings.append("No files created or modified in workspace - limited evidence of work")
    except Exception as e:
        logger.warning(f"Error checking workspace files: {e}")
        warnings.append(f"Could not verify workspace files: {e}")

    # Check progress entries count
    progress_file = f"{workspace}/progress/{agent_id}_progress.jsonl"
    progress_entries = []
    try:
        if os.path.exists(progress_file):
            with open(progress_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            progress_entries.append(entry)
                        except:
                            pass
        evidence_summary['workspace_evidence']['progress_entries_count'] = len(progress_entries)

        if len(progress_entries) < 3:
            warnings.append(f"Only {len(progress_entries)} progress updates - expected at least 3")
    except Exception as e:
        logger.warning(f"Error reading progress file: {e}")
        warnings.append(f"Could not verify progress history: {e}")

    # Check findings reported (for investigators)
    findings_file = f"{workspace}/findings/{agent_id}_findings.jsonl"
    finding_count = 0
    try:
        if os.path.exists(findings_file):
            with open(findings_file, 'r') as f:
                for line in f:
                    if line.strip():
                        finding_count += 1
        evidence_summary['workspace_evidence']['findings_count'] = finding_count
    except Exception as e:
        logger.warning(f"Error reading findings file: {e}")

    # LAYER 2: Type-Specific Validation
    evidence_summary['type_specific'] = {}

    if agent_type == 'investigator':
        evidence_summary['type_specific']['type'] = 'investigator'
        evidence_summary['type_specific']['findings_required'] = True

        if finding_count == 0:
            warnings.append("Investigator should report findings - no findings file found")
        elif finding_count < 3:
            warnings.append(f"Only {finding_count} findings reported - expected 3+ for thorough investigation")
        else:
            evidence_summary['type_specific']['findings_ok'] = True

    elif agent_type == 'builder':
        evidence_summary['type_specific']['type'] = 'builder'
        evidence_summary['type_specific']['artifacts_expected'] = True

        if len(progress_entries) < 5:
            warnings.append(f"Builder has fewer than 5 progress updates ({len(progress_entries)}) - expected more for implementation work")

        # Check for test-related evidence in message
        test_keywords = ['test', 'pass', 'fail', 'verify', 'check']
        has_test_evidence = any(kw in message.lower() for kw in test_keywords)
        evidence_summary['type_specific']['test_evidence'] = has_test_evidence
        if not has_test_evidence:
            warnings.append("Builder message lacks test/verification keywords")

    elif agent_type == 'fixer':
        evidence_summary['type_specific']['type'] = 'fixer'
        evidence_summary['type_specific']['verification_expected'] = True

        if len(progress_entries) < 4:
            warnings.append(f"Fixer has fewer than 4 progress updates ({len(progress_entries)})")

        # Check for fix verification evidence
        fix_keywords = ['fix', 'repair', 'resolve', 'correct', 'verify', 'test']
        has_fix_evidence = any(kw in message.lower() for kw in fix_keywords)
        evidence_summary['type_specific']['fix_evidence'] = has_fix_evidence
        if not has_fix_evidence:
            warnings.append("Fixer message lacks fix/verification keywords")

    # LAYER 3: Message Content Validation
    evidence_summary['message_validation'] = {}
    evidence_summary['message_validation']['length'] = len(message)

    if len(message) < 50:
        warnings.append(f"Completion message too short ({len(message)} chars) - should describe what was completed and how it was verified")

    # Check for suspicious phrases
    suspicious_phrases = ['TODO', 'not implemented', 'mock', 'placeholder', 'fake', 'dummy']
    found_suspicious = []
    for phrase in suspicious_phrases:
        if phrase.lower() in message.lower():
            found_suspicious.append(phrase)

    if found_suspicious:
        warnings.append(f"Message contains suspicious phrases: {', '.join(found_suspicious)} - indicates incomplete work")

    evidence_summary['message_validation']['suspicious_phrases_found'] = found_suspicious

    # Check for evidence keywords
    evidence_keywords = ['created', 'modified', 'tested', 'verified', 'found', 'fixed', 'implemented', 'reported', 'analyzed', 'documented']
    found_keywords = [kw for kw in evidence_keywords if kw in message.lower()]
    evidence_summary['message_validation']['evidence_keywords_found'] = found_keywords

    if len(found_keywords) == 0:
        warnings.append("Message lacks evidence keywords - should describe concrete actions taken")

    # LAYER 4: Progress Pattern Validation
    evidence_summary['progress_pattern'] = {}

    if len(progress_entries) < 3:
        warnings.append("Only start and end progress updates - no intermediate work shown")
        evidence_summary['progress_pattern']['pattern'] = 'suspicious_minimal'
    else:
        evidence_summary['progress_pattern']['pattern'] = 'normal'

    # Check time elapsed
    if agent_start_time and len(progress_entries) > 0:
        try:
            from datetime import datetime as dt
            start_dt = dt.fromisoformat(agent_start_time.replace('Z', '+00:00'))
            end_dt = dt.fromisoformat(progress_entries[-1]['timestamp'].replace('Z', '+00:00'))
            elapsed_seconds = (end_dt - start_dt).total_seconds()
            evidence_summary['progress_pattern']['elapsed_seconds'] = elapsed_seconds

            if elapsed_seconds < 120:
                warnings.append(f"Completed in {elapsed_seconds:.0f} seconds - suspiciously fast for quality work")
                evidence_summary['progress_pattern']['speed'] = 'too_fast'
            elif elapsed_seconds < 180:
                warnings.append(f"Completed in {elapsed_seconds:.0f} seconds - consider spending more time on quality")
                evidence_summary['progress_pattern']['speed'] = 'fast'
            else:
                evidence_summary['progress_pattern']['speed'] = 'reasonable'
        except Exception as e:
            logger.warning(f"Error calculating time elapsed: {e}")

    # Check for 'working' status updates
    working_updates = [e for e in progress_entries if e.get('status') == 'working']
    evidence_summary['progress_pattern']['working_updates_count'] = len(working_updates)

    if len(working_updates) == 0 and len(progress_entries) > 1:
        warnings.append("No 'working' status updates - agent may have skipped actual work phase")

    # Calculate confidence score
    # Start with 1.0, subtract for each warning/issue
    confidence = 1.0
    confidence -= len(warnings) * 0.1  # Each warning reduces confidence by 10%
    confidence -= len(blocking_issues) * 0.3  # Each blocking issue reduces by 30%
    confidence = max(0.0, min(1.0, confidence))  # Clamp to [0, 1]

    # Determine if valid (in WARNING mode, always valid unless critical blocking issues)
    # Critical blocking issues: agent not found, major evidence missing
    valid = len(blocking_issues) == 0

    return {
        "valid": valid,
        "confidence": confidence,
        "warnings": warnings,
        "blocking_issues": blocking_issues,
        "evidence_summary": evidence_summary
    }


def update_agent_progress(
    task_id: str,
    agent_id: str,
    status: str,
    message: str,
    progress: int = 0,
    # Dependency injection
    find_task_workspace=None,
    get_workspace_base_from_task_workspace=None,
    get_global_registry_path=None,
    check_tmux_session_exists=None,
    kill_tmux_session=None,
) -> Dict[str, Any]:
    """
    Update agent progress - called by agents themselves to self-report.
    Returns comprehensive status of all agents for coordination.

    Args:
        task_id: Task ID
        agent_id: Agent ID reporting progress
        status: Current status (working/blocked/completed/etc)
        message: Status message describing current work
        progress: Progress percentage (0-100)

    Returns:
        Update result with comprehensive task status for coordination
    """
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }

    registry_path = f"{workspace}/AGENT_REGISTRY.json"

    # Log progress update
    progress_file = f"{workspace}/progress/{agent_id}_progress.jsonl"
    os.makedirs(f"{workspace}/progress", exist_ok=True)

    progress_entry = {
        "timestamp": datetime.now().isoformat(),
        "agent_id": agent_id,
        "status": status,
        "message": message,
        "progress": progress
    }

    with open(progress_file, 'a') as f:
        f.write(json.dumps(progress_entry) + '\n')

    # Update registry with ATOMIC LOCKING to prevent race conditions
    # Multiple agents completing simultaneously would cause lost updates without locking
    from .registry import LockedRegistryFile

    agent_found = None
    previous_status = None
    active_statuses = ['running', 'working', 'blocked']
    terminal_statuses = ['completed', 'terminated', 'error', 'failed']

    try:
        with LockedRegistryFile(registry_path) as (registry, f):
            # Find and update agent
            for agent in registry['agents']:
                if agent['id'] == agent_id:
                    agent_found = agent
                    previous_status = agent.get('status')
                    break

            # MIT-003: Validate phase binding before accepting progress
            # Agents bound to completed/approved phases should not be able to report progress
            if agent_found:
                from .registry import validate_agent_phase
                phase_validation = validate_agent_phase(registry, agent_id)
                if not phase_validation['valid']:
                    logger.warning(
                        f"Agent {agent_id} phase validation failed: {phase_validation.get('reason', 'unknown')}. "
                        f"Agent phase: {phase_validation.get('agent_phase', 'none')}, "
                        f"Current phase: {phase_validation.get('current_phase', 'none')}"
                    )
                    # For now, log warning but allow progress (non-blocking for backward compatibility)

            # Update agent fields if found
            if agent_found:
                agent_found['last_update'] = datetime.now().isoformat()
                agent_found['status'] = status
                agent_found['progress'] = progress

            # VALIDATION: When agent claims completion, validate the claim
            if status == 'completed' and agent_found:
                agent_type = agent_found.get('type', 'unknown')

                # Run 4-layer validation
                validation = validate_agent_completion(workspace, agent_id, agent_type, message, registry)

                # In WARNING mode: log but don't block completion
                if not validation['valid'] or validation['warnings']:
                    logger.warning(f"Completion validation for {agent_id}: confidence={validation['confidence']:.2f}, "
                                 f"warnings={len(validation['warnings'])}, blocking_issues={len(validation['blocking_issues'])}")
                    logger.warning(f"Validation warnings: {validation['warnings']}")
                    if validation['blocking_issues']:
                        logger.warning(f"Blocking issues: {validation['blocking_issues']}")

                # Store validation results in agent record for future reference
                agent_found['completion_validation'] = {
                    'confidence': validation['confidence'],
                    'warnings': validation['warnings'],
                    'blocking_issues': validation['blocking_issues'],
                    'evidence_summary': validation['evidence_summary'],
                    'validated_at': datetime.now().isoformat()
                }

                logger.info(f"Agent {agent_id} completion validated: confidence={validation['confidence']:.2f}, "
                           f"{len(validation['warnings'])} warnings, {len(validation['blocking_issues'])} blocking issues")

                # Mark completion timestamp
                agent_found['completed_at'] = datetime.now().isoformat()

            # UPDATE ACTIVE COUNT: Decrement when transitioning to completed/terminated/error from active status
            if previous_status in active_statuses and status in terminal_statuses:
                # Agent transitioned from active to terminal state
                registry['active_count'] = max(0, registry.get('active_count', 0) - 1)
                registry['completed_count'] = registry.get('completed_count', 0) + 1
                logger.info(f"Agent {agent_id} transitioned from {previous_status} to {status}. Active count: {registry['active_count']}")

            # Write back atomically while still holding the lock
            f.seek(0)
            f.write(json.dumps(registry, indent=2))
            f.truncate()

    except TimeoutError as e:
        logger.error(f"Timeout acquiring lock on task registry for agent {agent_id}: {e}")
        return {"success": False, "error": "Registry locked by another process, retry later"}
    except FileNotFoundError:
        return {"success": False, "error": f"Registry file not found: {registry_path}"}

    # AUTOMATIC RESOURCE CLEANUP: Free computing resources on terminal status
    # This is done OUTSIDE the lock to avoid holding it during potentially slow cleanup
    if previous_status in active_statuses and status in terminal_statuses:
        try:
            cleanup_result = cleanup_agent_resources(
                workspace=workspace,
                agent_id=agent_id,
                agent_data=agent_found,
                keep_logs=True,  # Archive logs instead of deleting for post-mortem analysis
                check_tmux_session_exists=check_tmux_session_exists,
                kill_tmux_session=kill_tmux_session,
            )
            logger.info(f"Auto-cleanup for {agent_id}: tmux_killed={cleanup_result.get('tmux_session_killed')}, "
                       f"prompt_deleted={cleanup_result.get('prompt_file_deleted')}, "
                       f"logs_archived={cleanup_result.get('log_files_archived')}, "
                       f"no_zombies={cleanup_result.get('verified_no_zombies')}")

            # Update cleanup result in registry (separate atomic update)
            if agent_found:
                try:
                    with LockedRegistryFile(registry_path) as (registry2, f2):
                        for agent in registry2['agents']:
                            if agent['id'] == agent_id:
                                agent['auto_cleanup_result'] = cleanup_result
                                agent['auto_cleanup_timestamp'] = datetime.now().isoformat()
                                break
                        f2.seek(0)
                        f2.write(json.dumps(registry2, indent=2))
                        f2.truncate()
                except Exception as cleanup_update_err:
                    logger.warning(f"Could not update cleanup result in registry: {cleanup_update_err}")
        except Exception as e:
            logger.error(f"Auto-cleanup failed for {agent_id}: {e}")
            # Update error in registry
            try:
                with LockedRegistryFile(registry_path) as (registry2, f2):
                    for agent in registry2['agents']:
                        if agent['id'] == agent_id:
                            agent['auto_cleanup_error'] = str(e)
                            agent['auto_cleanup_timestamp'] = datetime.now().isoformat()
                            break
                    f2.seek(0)
                    f2.write(json.dumps(registry2, indent=2))
                    f2.truncate()
            except Exception as cleanup_update_err:
                logger.warning(f"Could not update cleanup error in registry: {cleanup_update_err}")

    # UPDATE GLOBAL REGISTRY: Sync the global registry's active agent count
    # Uses atomic locking to prevent race conditions with concurrent agent updates
    try:
        workspace_base = get_workspace_base_from_task_workspace(workspace)
        global_reg_path = get_global_registry_path(workspace_base)
        if os.path.exists(global_reg_path):
            with LockedRegistryFile(global_reg_path) as (global_reg, gf):
                # Update agent status in global registry
                if agent_id in global_reg.get('agents', {}):
                    global_reg['agents'][agent_id]['status'] = status
                    global_reg['agents'][agent_id]['last_update'] = datetime.now().isoformat()

                    # If transitioned to terminal state, update global active count
                    if previous_status in active_statuses and status in terminal_statuses:
                        global_reg['active_agents'] = max(0, global_reg.get('active_agents', 0) - 1)
                        if status == 'completed':
                            global_reg['agents'][agent_id]['completed_at'] = datetime.now().isoformat()
                        logger.info(f"Global registry updated: Active agents: {global_reg['active_agents']}")

                # Write back atomically while still holding the lock
                gf.seek(0)
                gf.write(json.dumps(global_reg, indent=2))
                gf.truncate()
    except TimeoutError as e:
        logger.warning(f"Timeout acquiring lock on global registry for agent {agent_id}: {e}")
    except Exception as e:
        logger.error(f"Failed to update global registry: {e}")

    # Get minimal status for coordination (prevents log bloat)
    minimal_status = get_minimal_coordination_info(task_id, find_task_workspace=find_task_workspace)

    # Return own update confirmation plus minimal coordination data
    return {
        "success": True,
        "own_update": {
            "agent_id": agent_id,
            "status": status,
            "progress": progress,
            "message": message,
            "timestamp": progress_entry["timestamp"]
        },
        "coordination_info": minimal_status if minimal_status["success"] else None
    }


def report_agent_finding(
    task_id: str,
    agent_id: str,
    finding_type: str,
    severity: str,
    message: str,
    data: dict = None,
    # Dependency injection
    find_task_workspace=None,
) -> Dict[str, Any]:
    """
    Report a finding/discovery - called by agents to share discoveries.
    Returns comprehensive status of all agents for coordination.

    Args:
        task_id: Task ID
        agent_id: Agent ID reporting finding
        finding_type: Type of finding (issue/solution/insight/etc)
        severity: Severity level (low/medium/high/critical)
        message: Finding description
        data: Additional finding data

    Returns:
        Report result with comprehensive task status for coordination
    """
    if data is None:
        data = {}

    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }

    findings_file = f"{workspace}/findings/{agent_id}_findings.jsonl"
    os.makedirs(f"{workspace}/findings", exist_ok=True)

    finding_entry = {
        "timestamp": datetime.now().isoformat(),
        "agent_id": agent_id,
        "finding_type": finding_type,
        "severity": severity,
        "message": message,
        "data": data
    }

    with open(findings_file, 'a') as f:
        f.write(json.dumps(finding_entry) + '\n')

    # Get minimal status for coordination (prevents log bloat)
    minimal_status = get_minimal_coordination_info(task_id, find_task_workspace=find_task_workspace)

    # Return own finding confirmation plus minimal coordination data
    return {
        "success": True,
        "own_finding": {
            "agent_id": agent_id,
            "finding_type": finding_type,
            "severity": severity,
            "message": message,
            "timestamp": finding_entry["timestamp"],
            "data": data
        },
        "coordination_info": minimal_status if minimal_status["success"] else None
    }


def spawn_child_agent(
    task_id: str,
    parent_agent_id: str,
    child_agent_type: str,
    child_prompt: str,
    # Dependency injection
    deploy_headless_agent_fn=None,
) -> Dict[str, Any]:
    """
    Spawn a child agent - called by agents to create sub-agents.

    Args:
        task_id: Parent task ID
        parent_agent_id: ID of parent agent spawning this child
        child_agent_type: Type of child agent
        child_prompt: Prompt for child agent

    Returns:
        Child agent spawn result
    """
    # Delegate to existing deployment function
    if deploy_headless_agent_fn:
        return deploy_headless_agent_fn(task_id, child_agent_type, child_prompt, parent_agent_id)
    else:
        return {
            "success": False,
            "error": "deploy_headless_agent function not provided"
        }
