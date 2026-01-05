"""
Agent Deployment Module

This module handles all agent deployment operations including:
- tmux session management for Claude CLI agents
- Agent ID generation and collision detection
- Deployment preflight checks and cleanup

Extracted from real_mcp_server.py monolith for maintainability.
"""

import json
import logging
import os
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

# No cursor-specific configuration needed - using Claude CLI with tmux

# ============================================================================
# TMUX SESSION MANAGEMENT
# ============================================================================


def check_tmux_available() -> bool:
    """Check if tmux is available"""
    try:
        result = subprocess.run(['tmux', '-V'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("tmux not available or not responding")
        return False


def create_tmux_session(session_name: str, command: str, working_dir: str = None) -> Dict[str, Any]:
    """Create a tmux session to run Claude in background."""
    try:
        cmd = ['tmux', 'new-session', '-d', '-s', session_name]
        if working_dir:
            cmd.extend(['-c', working_dir])
        cmd.append(command)

        logger.info(f"Creating tmux session '{session_name}' with command: {command[:100]}...")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=working_dir, timeout=30)

        if result.returncode == 0:
            logger.info(f"Successfully created tmux session '{session_name}'")
            return {
                "success": True,
                "session_name": session_name,
                "command": command,
                "output": result.stdout,
                "error": result.stderr
            }
        else:
            logger.error(f"Failed to create tmux session '{session_name}': {result.stderr}")
            return {
                "success": False,
                "error": f"Failed to create tmux session: {result.stderr}",
                "return_code": result.returncode
            }
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout creating tmux session '{session_name}'")
        return {
            "success": False,
            "error": "Timeout creating tmux session"
        }
    except Exception as e:
        logger.error(f"Exception creating tmux session '{session_name}': {e}")
        return {
            "success": False,
            "error": f"Exception creating tmux session: {str(e)}"
        }


def get_tmux_session_output(session_name: str) -> str:
    """Capture output from tmux session"""
    try:
        result = subprocess.run([
            'tmux', 'capture-pane', '-t', session_name, '-p'
        ], capture_output=True, text=True, timeout=5)

        if result.returncode == 0:
            return result.stdout
        return f"Error capturing output: {result.stderr}"
    except subprocess.TimeoutExpired:
        return "Error capturing output: tmux capture-pane timed out"
    except Exception as e:
        return f"Exception capturing output: {str(e)}"


def check_tmux_session_exists(session_name: str) -> bool:
    """Check if tmux session exists"""
    try:
        result = subprocess.run([
            'tmux', 'has-session', '-t', session_name
        ], capture_output=True, text=True, timeout=2)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        return False


def kill_tmux_session(session_name: str) -> bool:
    """Kill a tmux session"""
    try:
        result = subprocess.run([
            'tmux', 'kill-session', '-t', session_name
        ], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        return False


def list_all_tmux_sessions() -> Dict[str, Any]:
    """
    List all active tmux sessions and extract agent session info.

    Returns:
        Dict with session names, agent IDs, and metadata
    """
    try:
        result = subprocess.run(
            ['tmux', 'ls', '-F', '#{session_name}'],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            return {'success': False, 'error': 'No tmux sessions found or tmux error', 'sessions': []}

        # Parse tmux output - each line is a session name
        session_names = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]

        # Extract agent sessions (start with 'agent_')
        agent_sessions = {}
        other_sessions = []

        for name in session_names:
            if name.startswith('agent_'):
                # Extract agent_id from session name (format: agent_{agent_id})
                agent_id = name[6:]  # Remove 'agent_' prefix
                agent_sessions[agent_id] = {
                    'session_name': name,
                    'agent_id': agent_id
                }
            else:
                other_sessions.append(name)

        return {
            'success': True,
            'agent_sessions': agent_sessions,
            'agent_count': len(agent_sessions),
            'other_sessions': other_sessions,
            'total_sessions': len(session_names)
        }

    except Exception as e:
        logger.error(f"Error listing tmux sessions: {e}")
        return {'success': False, 'error': str(e), 'sessions': []}



# ============================================================================
# AGENT ID GENERATION AND DEDUPLICATION
# ============================================================================


def find_existing_agent(task_id: str, agent_type: str, registry: dict, status_filter: list = None) -> Optional[dict]:
    """
    Check if an agent of the same type already exists for this task.

    Args:
        task_id: Task ID to check
        agent_type: Type of agent to look for
        registry: Task registry dictionary
        status_filter: List of statuses to consider (default: ['running', 'working'])

    Returns:
        Existing agent dict if found, None otherwise
    """
    if status_filter is None:
        status_filter = ['running', 'working']

    # Search task registry for existing agent of same type
    for agent in registry.get('agents', []):
        if agent.get('type') == agent_type and agent.get('status') in status_filter:
            return agent

    return None


def verify_agent_id_unique(agent_id: str, registry: dict, global_registry: dict) -> bool:
    """
    Verify that an agent_id doesn't already exist in task or global registry.

    Args:
        agent_id: Generated agent ID to verify
        registry: Task registry dictionary
        global_registry: Global registry dictionary

    Returns:
        True if unique, False if already exists
    """
    # Check task registry
    for agent in registry.get('agents', []):
        if agent.get('id') == agent_id:
            return False

    # Check global registry
    if agent_id in global_registry.get('agents', {}):
        return False

    return True


def generate_unique_agent_id(agent_type: str, registry: dict, global_registry: dict, max_attempts: int = 10) -> str:
    """
    Generate a unique agent ID with collision detection.

    Args:
        agent_type: Type of agent
        registry: Task registry dictionary
        global_registry: Global registry dictionary
        max_attempts: Maximum number of attempts to generate unique ID

    Returns:
        Unique agent ID

    Raises:
        RuntimeError: If unable to generate unique ID after max_attempts
    """
    for attempt in range(max_attempts):
        # Generate ID with timestamp and random component
        timestamp = datetime.now().strftime('%H%M%S')
        random_suffix = uuid.uuid4().hex[:6]
        agent_id = f"{agent_type}-{timestamp}-{random_suffix}"

        # Verify uniqueness
        if verify_agent_id_unique(agent_id, registry, global_registry):
            return agent_id

        # If collision detected, add microseconds for next attempt
        if attempt > 0:
            microseconds = datetime.now().strftime('%f')[:3]
            agent_id = f"{agent_type}-{timestamp}{microseconds}-{random_suffix}"
            if verify_agent_id_unique(agent_id, registry, global_registry):
                return agent_id

    raise RuntimeError(f"Failed to generate unique agent_id after {max_attempts} attempts")


# ============================================================================
# PREFLIGHT CHECKS
# ============================================================================


def check_disk_space(workspace: str, min_mb: int = 100) -> Tuple[bool, float, str]:
    """
    Check if there's enough disk space for agent operations.

    Args:
        workspace: Path to workspace directory
        min_mb: Minimum required free space in megabytes

    Returns:
        Tuple of (has_space: bool, free_mb: float, error_message: str)
    """
    try:
        disk_stat = shutil.disk_usage(workspace)
        free_mb = disk_stat.free / (1024 * 1024)
        if free_mb < min_mb:
            return False, free_mb, f"Insufficient disk space: {free_mb:.1f}MB available, need at least {min_mb}MB"
        return True, free_mb, ""
    except Exception as e:
        return False, 0, f"Could not check disk space: {e}"


def test_workspace_writable(workspace: str) -> Tuple[bool, str]:
    """
    Test if workspace directory is writable.

    Args:
        workspace: Path to workspace directory

    Returns:
        Tuple of (is_writable: bool, error_message: str)
    """
    logs_dir = f"{workspace}/logs"
    try:
        os.makedirs(logs_dir, exist_ok=True)
        # Test write access
        test_file = f"{logs_dir}/.write_test_{uuid.uuid4().hex[:8]}"
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        return True, ""
    except Exception as e:
        return False, f"Workspace logs directory not writable: {e}"


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # tmux functions
    'check_tmux_available',
    'create_tmux_session',
    'get_tmux_session_output',
    'check_tmux_session_exists',
    'kill_tmux_session',
    'list_all_tmux_sessions',

    # Agent ID functions
    'find_existing_agent',
    'verify_agent_id_unique',
    'generate_unique_agent_id',

    # Preflight checks
    'check_disk_space',
    'test_workspace_writable',
]
