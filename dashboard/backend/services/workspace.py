"""
Workspace Service Module for Dashboard Backend

This module provides read-only access to the orchestrator workspace data,
including registries, agent logs, progress, and findings.

Reuses existing orchestrator modules for file locking and JSONL parsing.
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from datetime import datetime

# Add orchestrator modules to path for imports
import sys
orchestrator_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'orchestrator'))
if orchestrator_path not in sys.path:
    sys.path.insert(0, orchestrator_path)

# Import orchestrator modules for reuse
try:
    from registry import read_registry_with_lock, LockedRegistryFile
    from workspace import find_task_workspace, WORKSPACE_BASE
    from status import read_jsonl_lines, tail_jsonl_efficient, parse_jsonl_lines
except ImportError as e:
    # Fallback if orchestrator modules aren't accessible
    logging.warning(f"Could not import orchestrator modules: {e}. Using fallback implementations.")
    WORKSPACE_BASE = os.getenv('CLAUDE_ORCHESTRATOR_WORKSPACE',
                               os.path.expanduser('~/.claude-orchestrator/workspaces'))

logger = logging.getLogger(__name__)


class WorkspaceService:
    """Service for reading orchestrator workspace data."""

    def __init__(self, workspace_base: Optional[str] = None):
        """
        Initialize the workspace service.

        Args:
            workspace_base: Base directory for workspaces. If None, uses default.
        """
        self.workspace_base = workspace_base or WORKSPACE_BASE
        # Try to find .agent-workspace in project directory as fallback
        if not os.path.exists(self.workspace_base):
            project_workspace = os.path.abspath('.agent-workspace')
            if os.path.exists(project_workspace):
                self.workspace_base = project_workspace
                logger.info(f"Using project workspace: {project_workspace}")

        logger.info(f"WorkspaceService initialized with base: {self.workspace_base}")

    def get_global_registry(self) -> Optional[Dict[str, Any]]:
        """
        Read the global registry file.

        Returns:
            Global registry dict or None if not found/error
        """
        try:
            registry_path = os.path.join(self.workspace_base, 'registry', 'GLOBAL_REGISTRY.json')

            # Use orchestrator's locked read if available
            if 'read_registry_with_lock' in globals():
                return read_registry_with_lock(registry_path)

            # Fallback to simple read
            if not os.path.exists(registry_path):
                logger.warning(f"Global registry not found: {registry_path}")
                return None

            with open(registry_path, 'r') as f:
                return json.load(f)

        except Exception as e:
            logger.error(f"Error reading global registry: {e}")
            return None

    def get_task_registry(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Read the registry for a specific task.

        Args:
            task_id: Task ID (e.g., "TASK-20260104-141158-50c60706")

        Returns:
            Task registry dict or None if not found/error
        """
        try:
            # Try to find task workspace
            if 'find_task_workspace' in globals():
                workspace = find_task_workspace(task_id)
                if not workspace:
                    logger.warning(f"Task workspace not found for: {task_id}")
                    return None
                registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
            else:
                # Fallback to direct path construction
                task_dir = os.path.join(self.workspace_base, task_id)
                registry_path = os.path.join(task_dir, 'AGENT_REGISTRY.json')

            # Use orchestrator's locked read if available
            if 'read_registry_with_lock' in globals():
                return read_registry_with_lock(registry_path)

            # Fallback to simple read
            if not os.path.exists(registry_path):
                logger.warning(f"Task registry not found: {registry_path}")
                return None

            with open(registry_path, 'r') as f:
                return json.load(f)

        except Exception as e:
            logger.error(f"Error reading task registry for {task_id}: {e}")
            return None

    def get_agent_logs(self, task_id: str, agent_id: str, lines: int = 100) -> List[Dict[str, Any]]:
        """
        Read agent log entries (stream JSONL).

        Args:
            task_id: Task ID
            agent_id: Agent ID
            lines: Number of recent lines to return (default 100)

        Returns:
            List of parsed log entries (newest last)
        """
        try:
            # Find log file path
            task_dir = os.path.join(self.workspace_base, task_id)
            log_path = os.path.join(task_dir, 'logs', f'{agent_id}_stream.jsonl')

            if not os.path.exists(log_path):
                # Try alternate naming convention
                log_path = os.path.join(task_dir, 'logs', f'{agent_id}.stream-json')
                if not os.path.exists(log_path):
                    logger.debug(f"Log file not found for {agent_id}")
                    return []

            # Use orchestrator's efficient tail if available
            if 'tail_jsonl_efficient' in globals():
                raw_lines = tail_jsonl_efficient(log_path, lines)
            else:
                # Fallback to reading last N lines
                raw_lines = self._tail_file(log_path, lines)

            # Parse JSONL lines
            if 'parse_jsonl_lines' in globals():
                return parse_jsonl_lines(raw_lines)
            else:
                return self._parse_jsonl(raw_lines)

        except Exception as e:
            logger.error(f"Error reading logs for {agent_id}: {e}")
            return []

    def get_agent_progress(self, task_id: str, agent_id: str) -> List[Dict[str, Any]]:
        """
        Read agent progress entries.

        Args:
            task_id: Task ID
            agent_id: Agent ID

        Returns:
            List of progress entries (oldest to newest)
        """
        try:
            task_dir = os.path.join(self.workspace_base, task_id)
            progress_path = os.path.join(task_dir, 'progress', f'{agent_id}_progress.jsonl')

            if not os.path.exists(progress_path):
                logger.debug(f"Progress file not found for {agent_id}")
                return []

            # Read all progress entries
            if 'read_jsonl_lines' in globals():
                raw_lines = read_jsonl_lines(progress_path)
                if 'parse_jsonl_lines' in globals():
                    return parse_jsonl_lines(raw_lines)
                else:
                    return self._parse_jsonl(raw_lines)
            else:
                with open(progress_path, 'r') as f:
                    return [json.loads(line) for line in f if line.strip()]

        except Exception as e:
            logger.error(f"Error reading progress for {agent_id}: {e}")
            return []

    def get_agent_findings(self, task_id: str, agent_id: str) -> List[Dict[str, Any]]:
        """
        Read agent findings entries.

        Args:
            task_id: Task ID
            agent_id: Agent ID

        Returns:
            List of findings entries (oldest to newest)
        """
        try:
            task_dir = os.path.join(self.workspace_base, task_id)
            findings_path = os.path.join(task_dir, 'findings', f'{agent_id}_findings.jsonl')

            if not os.path.exists(findings_path):
                logger.debug(f"Findings file not found for {agent_id}")
                return []

            # Read all findings entries
            if 'read_jsonl_lines' in globals():
                raw_lines = read_jsonl_lines(findings_path)
                if 'parse_jsonl_lines' in globals():
                    return parse_jsonl_lines(raw_lines)
                else:
                    return self._parse_jsonl(raw_lines)
            else:
                with open(findings_path, 'r') as f:
                    return [json.loads(line) for line in f if line.strip()]

        except Exception as e:
            logger.error(f"Error reading findings for {agent_id}: {e}")
            return []

    def list_tasks(self) -> List[Dict[str, Any]]:
        """
        List all task directories with basic info.

        Returns:
            List of task info dicts with id, created_at, status
        """
        try:
            tasks = []

            # First try to get from global registry if available
            global_reg = self.get_global_registry()
            if global_reg and 'tasks' in global_reg:
                for task_id, task_info in global_reg['tasks'].items():
                    tasks.append({
                        'task_id': task_id,
                        'description': task_info.get('description', ''),
                        'status': task_info.get('status', 'UNKNOWN'),
                        'created_at': task_info.get('created_at', '')
                    })
                return sorted(tasks, key=lambda x: x.get('created_at', ''), reverse=True)

            # Fallback to scanning directories
            if not os.path.exists(self.workspace_base):
                return []

            for entry in os.listdir(self.workspace_base):
                if entry.startswith('TASK-') and os.path.isdir(os.path.join(self.workspace_base, entry)):
                    # Try to read task registry for details
                    task_reg = self.get_task_registry(entry)
                    if task_reg:
                        tasks.append({
                            'task_id': entry,
                            'description': task_reg.get('task_description', ''),
                            'status': task_reg.get('status', 'UNKNOWN'),
                            'created_at': task_reg.get('created_at', '')
                        })
                    else:
                        # Basic info if registry not readable
                        tasks.append({
                            'task_id': entry,
                            'description': 'Registry not readable',
                            'status': 'UNKNOWN',
                            'created_at': ''
                        })

            return sorted(tasks, key=lambda x: x.get('task_id', ''), reverse=True)

        except Exception as e:
            logger.error(f"Error listing tasks: {e}")
            return []

    def get_task_summary(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a comprehensive summary of a task including agents and phases.

        Args:
            task_id: Task ID

        Returns:
            Summary dict with task details, phases, and agents
        """
        try:
            registry = self.get_task_registry(task_id)
            if not registry:
                return None

            # Build summary
            summary = {
                'task_id': task_id,
                'description': registry.get('task_description', ''),
                'status': registry.get('status', 'UNKNOWN'),
                'created_at': registry.get('created_at', ''),
                'priority': registry.get('priority', 'P2'),
                'current_phase_index': registry.get('current_phase_index', 0),
                'phases': registry.get('phases', []),
                'agent_stats': {
                    'total_spawned': registry.get('total_spawned', 0),
                    'active_count': registry.get('active_count', 0),
                    'completed_count': registry.get('completed_count', 0),
                    'max_agents': registry.get('max_agents', 45)
                },
                'agents': []
            }

            # Add agent summaries
            for agent in registry.get('agents', []):
                agent_summary = {
                    'id': agent.get('id'),
                    'type': agent.get('type'),
                    'status': agent.get('status'),
                    'progress': agent.get('progress', 0),
                    'phase_index': agent.get('phase_index'),
                    'parent': agent.get('parent'),
                    'last_update': agent.get('last_update')
                }

                # Get latest progress message if available
                progress_entries = self.get_agent_progress(task_id, agent['id'])
                if progress_entries:
                    latest = progress_entries[-1]
                    agent_summary['latest_message'] = latest.get('message', '')

                summary['agents'].append(agent_summary)

            return summary

        except Exception as e:
            logger.error(f"Error getting task summary for {task_id}: {e}")
            return None

    # Helper methods for fallback implementations

    def _tail_file(self, filepath: str, n_lines: int) -> List[str]:
        """Simple tail implementation for fallback."""
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()
                return lines[-n_lines:] if len(lines) > n_lines else lines
        except Exception:
            return []

    def _parse_jsonl(self, lines: List[str]) -> List[Dict[str, Any]]:
        """Parse JSONL lines with error handling."""
        parsed = []
        for line in lines:
            if not line.strip():
                continue
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug(f"Skipping malformed JSON line")
                continue
        return parsed


# Singleton instance for easy import
_workspace_service = None

def get_workspace_service() -> WorkspaceService:
    """Get or create the singleton WorkspaceService instance."""
    global _workspace_service
    if _workspace_service is None:
        _workspace_service = WorkspaceService()
    return _workspace_service