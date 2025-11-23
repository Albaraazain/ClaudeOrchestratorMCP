#!/usr/bin/env python3
"""
Claude Orchestrator MCP Server

A Model Context Protocol (MCP) server for managing headless Claude agent orchestration
with tmux-based background execution and comprehensive progress tracking.

Author: Claude Code Orchestrator Project
License: MIT
"""

from fastmcp import FastMCP
from typing import Dict, List, Optional, Any
import json
import os
import subprocess
import uuid
import time
import logging
from datetime import datetime
from pathlib import Path
import sys
import re
import shutil
import fcntl
import errno

# Initialize MCP server
mcp = FastMCP("Claude Orchestrator")

# Project context detection cache
_project_context_cache: Dict[str, Dict[str, Any]] = {}

# Configuration
# WORKSPACE_BASE: Set via CLAUDE_ORCHESTRATOR_WORKSPACE env var to control where task workspaces are created
# Example: export CLAUDE_ORCHESTRATOR_WORKSPACE=/Users/yourname/Developer/Projects/yourproject/.agent-workspace
# Default: Creates .agent-workspace in the MCP server's directory
WORKSPACE_BASE = os.getenv('CLAUDE_ORCHESTRATOR_WORKSPACE', os.path.abspath('.agent-workspace'))
DEFAULT_MAX_AGENTS = int(os.getenv('CLAUDE_ORCHESTRATOR_MAX_AGENTS', '45'))
DEFAULT_MAX_CONCURRENT = int(os.getenv('CLAUDE_ORCHESTRATOR_MAX_CONCURRENT', '20'))
DEFAULT_MAX_DEPTH = int(os.getenv('CLAUDE_ORCHESTRATOR_MAX_DEPTH', '5'))

# Agent Backend Configuration
# AGENT_BACKEND: Choose between 'claude' (tmux+claude CLI) or 'cursor' (cursor-agent)
# Example: export CLAUDE_ORCHESTRATOR_BACKEND=claude  # to switch back to claude
# Default: 'cursor' - uses cursor-agent by default
AGENT_BACKEND = os.getenv('CLAUDE_ORCHESTRATOR_BACKEND', 'cursor')
CURSOR_AGENT_PATH = os.getenv('CURSOR_AGENT_PATH', shutil.which('cursor-agent') or '~/.local/bin/cursor-agent')
CURSOR_AGENT_MODEL = os.getenv('CURSOR_AGENT_MODEL', 'auto')
CURSOR_AGENT_FLAGS = os.getenv('CURSOR_AGENT_FLAGS', '--approve-mcps --force')
CURSOR_ENABLE_THINKING_LOGS = os.getenv('CURSOR_ENABLE_THINKING_LOGS', 'false').lower() == 'true'

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# FILE LOCKING FOR REGISTRY OPERATIONS
# ============================================================================

class LockedRegistryFile:
    """
    Context manager for atomic registry file operations with exclusive locking.

    Prevents race conditions in concurrent registry access by using fcntl-based
    file locking. Ensures read-modify-write operations are atomic.

    Usage:
        with LockedRegistryFile(registry_path) as (registry, f):
            registry['agents'].append(agent_data)
            registry['total_spawned'] += 1
            f.seek(0)
            f.write(json.dumps(registry, indent=2))
            f.truncate()

    Features:
    - Exclusive lock (LOCK_EX) blocks other processes until released
    - Automatic unlock on context exit (even if exception occurs)
    - Handles lock acquisition failures with retries
    - Thread-safe and process-safe
    """

    def __init__(self, path: str, timeout: int = 10, retry_delay: float = 0.1):
        """
        Initialize registry file lock manager.

        Args:
            path: Path to registry JSON file
            timeout: Maximum seconds to wait for lock acquisition
            retry_delay: Seconds to wait between lock attempts
        """
        self.path = path
        self.timeout = timeout
        self.retry_delay = retry_delay
        self.file = None
        self.registry = None

    def __enter__(self):
        """
        Acquire exclusive lock and load registry.

        Returns:
            Tuple of (registry_dict, file_handle) for modification

        Raises:
            TimeoutError: If lock cannot be acquired within timeout
            FileNotFoundError: If registry file doesn't exist
            json.JSONDecodeError: If registry is corrupted
        """
        start_time = time.time()

        # Open file in read-write mode (must exist)
        try:
            self.file = open(self.path, 'r+')
        except FileNotFoundError:
            logger.error(f"Registry file not found: {self.path}")
            raise

        # Try to acquire exclusive lock with timeout
        while True:
            try:
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                # Lock acquired successfully
                break
            except (IOError, OSError) as e:
                if e.errno not in (errno.EACCES, errno.EAGAIN):
                    # Unexpected error, not a lock conflict
                    self.file.close()
                    raise

                # Lock is held by another process
                elapsed = time.time() - start_time
                if elapsed >= self.timeout:
                    self.file.close()
                    raise TimeoutError(
                        f"Could not acquire lock on {self.path} after {self.timeout}s. "
                        f"Another process may be holding it."
                    )

                # Wait and retry
                time.sleep(self.retry_delay)

        # Lock acquired - now read and parse registry
        try:
            self.file.seek(0)
            self.registry = json.load(self.file)
            logger.debug(f"Registry locked and loaded: {self.path}")
            return self.registry, self.file
        except json.JSONDecodeError as e:
            # Registry is corrupted
            logger.error(f"Corrupted registry JSON in {self.path}: {e}")
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            self.file.close()
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Release lock and close file.

        Called automatically when exiting 'with' block, even if exception occurred.
        """
        if self.file:
            try:
                # Always unlock, even if there was an exception
                fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
                logger.debug(f"Registry unlocked: {self.path}")
            except Exception as e:
                logger.error(f"Error unlocking registry {self.path}: {e}")
            finally:
                self.file.close()

        # Don't suppress exceptions
        return False


# ============================================================================
# ATOMIC REGISTRY OPERATIONS
# ============================================================================

def atomic_add_agent(
    registry_path: str,
    agent_data: Dict[str, Any],
    parent: str
) -> None:
    """
    Atomically add agent to registry with proper count updates.

    Args:
        registry_path: Path to task registry JSON
        agent_data: Agent metadata dict to append
        parent: Parent agent ID for hierarchy tracking

    Raises:
        TimeoutError: If lock cannot be acquired
        FileNotFoundError: If registry doesn't exist
    """
    with LockedRegistryFile(registry_path) as (registry, f):
        # Add agent to list
        registry['agents'].append(agent_data)

        # Increment counters
        registry['total_spawned'] += 1
        registry['active_count'] += 1

        # Update hierarchy
        if parent not in registry['agent_hierarchy']:
            registry['agent_hierarchy'][parent] = []
        registry['agent_hierarchy'][parent].append(agent_data['id'])

        # Write back to file
        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.info(
            f"Atomically added agent {agent_data['id']} to registry. "
            f"Total: {registry['total_spawned']}, Active: {registry['active_count']}"
        )


def atomic_update_agent_status(
    registry_path: str,
    agent_id: str,
    status: str,
    **extra_fields
) -> Dict[str, Any]:
    """
    Atomically update agent status in registry.

    Args:
        registry_path: Path to task registry JSON
        agent_id: Agent ID to update
        status: New status value
        **extra_fields: Additional fields to update (e.g., completed_at, progress)

    Returns:
        Dict with update result and previous status

    Raises:
        ValueError: If agent not found in registry
    """
    active_statuses = ['running', 'working', 'blocked']
    terminal_statuses = ['completed', 'error', 'terminated']

    with LockedRegistryFile(registry_path) as (registry, f):
        # Find agent
        agent = None
        for a in registry['agents']:
            if a['id'] == agent_id:
                agent = a
                break

        if not agent:
            raise ValueError(f"Agent {agent_id} not found in registry")

        previous_status = agent.get('status')

        # Update status and extra fields
        agent['status'] = status
        agent['last_update'] = datetime.now().isoformat()
        for key, value in extra_fields.items():
            agent[key] = value

        # Update counts if transitioning to terminal state
        if previous_status in active_statuses and status in terminal_statuses:
            registry['active_count'] = max(0, registry['active_count'] - 1)
            if status == 'completed':
                registry['completed_count'] = registry.get('completed_count', 0) + 1

        # Write back
        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.info(
            f"Atomically updated agent {agent_id}: {previous_status} -> {status}. "
            f"Active: {registry['active_count']}"
        )

        return {
            'success': True,
            'agent_id': agent_id,
            'previous_status': previous_status,
            'new_status': status,
            'active_count': registry['active_count']
        }


def atomic_increment_counts(registry_path: str, active: int = 0, total: int = 0) -> None:
    """
    Atomically increment registry counters.

    Args:
        registry_path: Path to registry JSON
        active: Amount to increment active_count by
        total: Amount to increment total_spawned by
    """
    with LockedRegistryFile(registry_path) as (registry, f):
        registry['active_count'] = registry.get('active_count', 0) + active
        registry['total_spawned'] = registry.get('total_spawned', 0) + total

        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.debug(f"Atomically incremented counts: +{active} active, +{total} total")


def atomic_decrement_active_count(registry_path: str, amount: int = 1) -> None:
    """
    Atomically decrement active agent count.

    Args:
        registry_path: Path to registry JSON
        amount: Amount to decrement by (default 1)
    """
    with LockedRegistryFile(registry_path) as (registry, f):
        registry['active_count'] = max(0, registry.get('active_count', 0) - amount)

        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.debug(f"Atomically decremented active_count by {amount}")


def atomic_mark_agents_completed(
    registry_path: str,
    agent_ids: List[str]
) -> int:
    """
    Atomically mark multiple agents as completed (for auto-cleanup).

    Args:
        registry_path: Path to task registry JSON
        agent_ids: List of agent IDs to mark as completed

    Returns:
        Number of agents actually marked as completed
    """
    if not agent_ids:
        return 0

    with LockedRegistryFile(registry_path) as (registry, f):
        marked_count = 0
        completed_at = datetime.now().isoformat()

        for agent in registry['agents']:
            if agent['id'] in agent_ids and agent['status'] == 'running':
                agent['status'] = 'completed'
                agent['completed_at'] = completed_at
                marked_count += 1

        # Update counts
        registry['active_count'] = max(0, registry['active_count'] - marked_count)
        registry['completed_count'] = registry.get('completed_count', 0) + marked_count

        # Write back
        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.info(
            f"Atomically marked {marked_count} agents as completed. "
            f"Active: {registry['active_count']}"
        )

        return marked_count


# ============================================================================
# TASK PARAMETER VALIDATION CLASSES
# ============================================================================

class TaskValidationError(ValueError):
    """Raised when task parameters fail critical validation"""

    def __init__(self, field: str, reason: str, value: Any):
        self.field = field
        self.reason = reason
        self.value = value
        super().__init__(f"Validation failed for '{field}': {reason}")


class TaskValidationWarning:
    """Non-fatal validation issue"""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, str]:
        return {
            'field': self.field,
            'message': self.message,
            'timestamp': self.timestamp
        }


def find_task_workspace(task_id: str) -> str:
    """
    Find the workspace directory for a given task ID.
    Searches in multiple locations:
    1. Server's default WORKSPACE_BASE
    2. Global registries to find the stored workspace location
    3. Common project locations (fallback for tasks created with client_cwd)
    
    Returns the workspace path or None if not found.
    """
    # Check server's default workspace first (fastest path)
    workspace = f"{WORKSPACE_BASE}/{task_id}"
    if os.path.exists(f"{workspace}/AGENT_REGISTRY.json"):
        return workspace
    
    # Check global registries to find where the task was created
    # This handles tasks created with client_cwd from different projects
    potential_registry_locations = [
        WORKSPACE_BASE,  # Default server location
    ]
    
    # Also check current directory tree for .agent-workspace
    current_dir = os.getcwd()
    for _ in range(5):  # Search up to 5 levels up
        potential_location = os.path.join(current_dir, '.agent-workspace')
        if os.path.isdir(potential_location) and potential_location not in potential_registry_locations:
            potential_registry_locations.append(potential_location)
        parent = os.path.dirname(current_dir)
        if parent == current_dir:  # Reached root
            break
        current_dir = parent
    
    # Search through global registries to find the task
    for registry_base in potential_registry_locations:
        global_reg_path = f"{registry_base}/registry/GLOBAL_REGISTRY.json"
        if os.path.exists(global_reg_path):
            try:
                with open(global_reg_path, 'r') as f:
                    global_reg = json.load(f)
                    
                # Check if this registry knows about our task
                if task_id in global_reg.get('tasks', {}):
                    task_info = global_reg['tasks'][task_id]
                    
                    # First, check if the global registry has the workspace location stored
                    stored_workspace = task_info.get('workspace')
                    if stored_workspace and os.path.exists(f"{stored_workspace}/AGENT_REGISTRY.json"):
                        logger.info(f"Found task {task_id} at stored workspace from global registry: {stored_workspace}")
                        return stored_workspace
                    
                    # Otherwise, try the expected location based on this registry's location
                    candidate = f"{registry_base}/{task_id}"
                    if os.path.exists(f"{candidate}/AGENT_REGISTRY.json"):
                        logger.info(f"Found task {task_id} via global registry at {candidate}")
                        return candidate
                        
                    # Also try reading the task registry directly to get stored workspace path
                    task_reg_path = f"{candidate}/AGENT_REGISTRY.json"
                    if os.path.exists(task_reg_path):
                        try:
                            with open(task_reg_path, 'r') as tf:
                                task_reg = json.load(tf)
                                stored_workspace = task_reg.get('workspace')
                                if stored_workspace and os.path.exists(f"{stored_workspace}/AGENT_REGISTRY.json"):
                                    logger.info(f"Found task {task_id} at stored workspace from task registry: {stored_workspace}")
                                    return stored_workspace
                        except Exception as e:
                            logger.debug(f"Could not read task registry at {task_reg_path}: {e}")
            except Exception as e:
                logger.debug(f"Could not read global registry at {global_reg_path}: {e}")
                continue
    
    # Fallback: Search in common project locations
    # Look for .agent-workspace directories in parent directories
    current_dir = os.getcwd()
    for _ in range(5):  # Search up to 5 levels up
        candidate = os.path.join(current_dir, '.agent-workspace', task_id)
        if os.path.exists(f"{candidate}/AGENT_REGISTRY.json"):
            logger.info(f"Found task {task_id} in client workspace: {candidate}")
            return candidate
        parent = os.path.dirname(current_dir)
        if parent == current_dir:  # Reached root
            break
        current_dir = parent
    
    return None

def get_workspace_base_from_task_workspace(task_workspace: str) -> str:
    """
    Extract workspace base from a task workspace path.
    
    Args:
        task_workspace: Path to task workspace (e.g., /path/to/.agent-workspace/TASK-xxx)
    
    Returns:
        Workspace base path (e.g., /path/to/.agent-workspace)
    """
    # Task workspace is typically: <workspace_base>/<task_id>
    # So parent directory is the workspace_base
    return os.path.dirname(task_workspace)

def get_global_registry_path(workspace_base: str = None) -> str:
    """
    Get the path to the global registry based on workspace base.
    
    Args:
        workspace_base: Optional workspace base directory. If not provided, uses WORKSPACE_BASE.
    
    Returns:
        Path to GLOBAL_REGISTRY.json
    """
    if workspace_base is None:
        workspace_base = WORKSPACE_BASE
    return f"{workspace_base}/registry/GLOBAL_REGISTRY.json"

def read_registry_with_lock(registry_path: str, timeout: float = 5.0) -> dict:
    """
    Read a registry file with exclusive file locking to prevent race conditions.

    This function uses fcntl.flock to acquire an exclusive lock on the registry file
    before reading it, preventing concurrent modifications from corrupting the data.

    Args:
        registry_path: Path to the registry JSON file
        timeout: Maximum time in seconds to wait for lock acquisition (default: 5.0)

    Returns:
        Dictionary containing the registry data

    Raises:
        FileNotFoundError: If the registry file doesn't exist
        TimeoutError: If unable to acquire lock within timeout period
        json.JSONDecodeError: If the registry file contains invalid JSON
    """
    import time
    start_time = time.time()

    while True:
        try:
            f = open(registry_path, 'r')
            try:
                # Try to acquire lock with non-blocking mode in loop for timeout
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    # Lock not available, check timeout
                    if time.time() - start_time >= timeout:
                        raise TimeoutError(f"Could not acquire lock on {registry_path} within {timeout}s")
                    # Release file handle and retry after short delay
                    f.close()
                    time.sleep(0.05)  # 50ms delay before retry
                    continue

                # Lock acquired, read the file
                registry = json.load(f)
                return registry
            finally:
                # Unlock and close
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except:
                    pass
                f.close()
        except FileNotFoundError:
            raise
        except json.JSONDecodeError:
            raise
        except Exception as e:
            logger.error(f"Error reading registry {registry_path}: {e}")
            raise

def write_registry_with_lock(registry_path: str, registry: dict, timeout: float = 5.0) -> None:
    """
    Write a registry file with exclusive file locking to prevent race conditions.

    This function uses fcntl.flock to acquire an exclusive lock on the registry file
    before writing it, preventing concurrent modifications from corrupting the data.

    Args:
        registry_path: Path to the registry JSON file
        registry: Dictionary containing the registry data to write
        timeout: Maximum time in seconds to wait for lock acquisition (default: 5.0)

    Raises:
        TimeoutError: If unable to acquire lock within timeout period
        OSError: If unable to write to the file
    """
    import time
    start_time = time.time()

    while True:
        try:
            # Open in r+ mode to allow locking before truncating
            # This prevents creating a zero-length file if lock fails
            f = open(registry_path, 'r+')
            try:
                # Try to acquire lock with non-blocking mode in loop for timeout
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    # Lock not available, check timeout
                    if time.time() - start_time >= timeout:
                        raise TimeoutError(f"Could not acquire lock on {registry_path} within {timeout}s")
                    # Release file handle and retry after short delay
                    f.close()
                    time.sleep(0.05)  # 50ms delay before retry
                    continue

                # Lock acquired, truncate and write
                f.seek(0)
                f.truncate()
                json.dump(registry, f, indent=2)
                f.flush()  # Ensure data is written to disk
                os.fsync(f.fileno())  # Force write to physical storage
                return
            finally:
                # Unlock and close
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except:
                    pass
                f.close()
        except FileNotFoundError:
            # File doesn't exist yet, create it
            # Use a+x mode would fail if exists, so use 'w' with O_CREAT
            f = open(registry_path, 'w')
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                json.dump(registry, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
                return
            finally:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                except:
                    pass
                f.close()
        except Exception as e:
            logger.error(f"Error writing registry {registry_path}: {e}")
            raise

def ensure_global_registry(workspace_base: str = None):
    """
    Ensure global registry exists at the specified workspace base.
    
    Args:
        workspace_base: Optional workspace base directory. If not provided, uses WORKSPACE_BASE.
    """
    if workspace_base is None:
        workspace_base = WORKSPACE_BASE
    
    os.makedirs(f"{workspace_base}/registry", exist_ok=True)
    global_reg_path = get_global_registry_path(workspace_base)
    
    if not os.path.exists(global_reg_path):
        initial_registry = {
            "created_at": datetime.now().isoformat(),
            "total_tasks": 0,
            "active_tasks": 0,
            "total_agents_spawned": 0,
            "active_agents": 0,
            "max_concurrent_agents": DEFAULT_MAX_CONCURRENT,
            "tasks": {},
            "agents": {}
        }
        with open(global_reg_path, 'w') as f:
            json.dump(initial_registry, f, indent=2)
        logger.info(f"Global registry created at {global_reg_path}")

def ensure_workspace():
    """Ensure workspace directory structure exists with proper initialization."""
    try:
        ensure_global_registry(WORKSPACE_BASE)
        logger.info(f"Workspace initialized at {WORKSPACE_BASE}")
    except Exception as e:
        logger.error(f"Failed to initialize workspace: {e}")
        raise

def check_tmux_available():
    """Check if tmux is available"""
    try:
        result = subprocess.run(['tmux', '-V'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("tmux not available or not responding")
        return False

def check_cursor_agent_available() -> bool:
    """
    Check if cursor-agent is available and functional.
    
    Returns:
        True if cursor-agent is installed and accessible, False otherwise
    """
    try:
        # Expand ~ in path if present
        cursor_path = os.path.expanduser(CURSOR_AGENT_PATH)
        
        # Check if file exists and is executable
        if not os.path.exists(cursor_path):
            logger.warning(f"cursor-agent not found at {cursor_path}")
            return False
        
        if not os.access(cursor_path, os.X_OK):
            logger.warning(f"cursor-agent at {cursor_path} is not executable")
            return False
        
        # Verify it responds to --version
        result = subprocess.run(
            [cursor_path, '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            logger.info(f"cursor-agent available: {result.stdout.strip()}")
            return True
        else:
            logger.warning(f"cursor-agent returned non-zero exit code: {result.returncode}")
            return False
            
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.warning(f"cursor-agent not available or not responding: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error checking cursor-agent: {e}")
        return False

def get_cursor_agent_path() -> str:
    """Get the full path to cursor-agent executable"""
    return os.path.expanduser(CURSOR_AGENT_PATH)

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
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            return result.stdout
        return f"Error capturing output: {result.stderr}"
    except Exception as e:
        return f"Exception capturing output: {str(e)}"

def check_tmux_session_exists(session_name: str) -> bool:
    """Check if tmux session exists"""
    try:
        result = subprocess.run([
            'tmux', 'has-session', '-t', session_name
        ], capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False

def kill_tmux_session(session_name: str) -> bool:
    """Kill a tmux session"""
    try:
        result = subprocess.run([
            'tmux', 'kill-session', '-t', session_name
        ], capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
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
        for session_name in session_names:
            if session_name.startswith('agent_'):
                # Extract agent ID from session name: agent_TYPE-TIMESTAMP-HASH
                agent_id = session_name.replace('agent_', '')
                agent_sessions[session_name] = {
                    'agent_id': agent_id,
                    'session_name': session_name,
                    'is_agent': True
                }

        return {
            'success': True,
            'total_sessions': len(session_names),
            'agent_sessions': len(agent_sessions),
            'sessions': agent_sessions
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Exception listing tmux sessions: {str(e)}',
            'sessions': {}
        }

def registry_health_check(registry_path: str) -> Dict[str, Any]:
    """
    Compare registry state against actual tmux sessions to detect discrepancies.

    Args:
        registry_path: Path to AGENT_REGISTRY.json

    Returns:
        Health report with discrepancies and recommendations
    """
    try:
        # Get actual tmux sessions
        tmux_result = list_all_tmux_sessions()
        if not tmux_result['success']:
            return {
                'success': False,
                'error': f"Failed to list tmux sessions: {tmux_result.get('error')}",
                'healthy': False
            }

        actual_sessions = set(tmux_result['sessions'].keys())

        # Load registry with file locking
        with open(registry_path, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)  # Shared lock for reading
            registry = json.load(f)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        # Analyze agents in registry
        active_statuses = {'running', 'working', 'blocked'}
        registry_active_agents = []
        registry_sessions = set()

        for agent in registry.get('agents', []):
            if agent.get('status') in active_statuses:
                registry_active_agents.append(agent)
                if 'tmux_session' in agent:
                    registry_sessions.add(agent['tmux_session'])

        # Find discrepancies
        zombie_agents = []  # In registry as active, but no tmux session
        orphan_sessions = []  # Tmux session exists, but not in registry

        for agent in registry_active_agents:
            session = agent.get('tmux_session')
            if session and session not in actual_sessions:
                zombie_agents.append({
                    'agent_id': agent['id'],
                    'agent_type': agent.get('type'),
                    'status': agent.get('status'),
                    'tmux_session': session,
                    'started_at': agent.get('started_at'),
                    'last_update': agent.get('last_update')
                })

        for session in actual_sessions:
            if session not in registry_sessions:
                orphan_sessions.append(session)

        # Calculate counts
        registry_active_count = registry.get('active_count', 0)
        actual_active_count = len(actual_sessions)
        count_mismatch = registry_active_count != actual_active_count

        healthy = (
            len(zombie_agents) == 0 and
            len(orphan_sessions) == 0 and
            not count_mismatch
        )

        return {
            'success': True,
            'healthy': healthy,
            'registry_path': registry_path,
            'actual_tmux_sessions': actual_active_count,
            'registry_active_count': registry_active_count,
            'count_mismatch': count_mismatch,
            'zombie_agents': zombie_agents,
            'zombie_count': len(zombie_agents),
            'orphan_sessions': orphan_sessions,
            'orphan_count': len(orphan_sessions),
            'recommendations': generate_health_recommendations(
                zombie_agents, orphan_sessions, count_mismatch
            )
        }
    except FileNotFoundError:
        return {
            'success': False,
            'error': f'Registry not found: {registry_path}',
            'healthy': False
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Health check exception: {str(e)}',
            'healthy': False
        }

def generate_health_recommendations(zombie_agents, orphan_sessions, count_mismatch):
    """Generate actionable recommendations based on health check results"""
    recommendations = []

    if zombie_agents:
        recommendations.append({
            'severity': 'high',
            'issue': f'{len(zombie_agents)} zombie agents detected',
            'action': 'Run validate_and_repair_registry() to mark zombies as terminated',
            'details': 'Agents marked as active/working but tmux sessions do not exist'
        })

    if orphan_sessions:
        recommendations.append({
            'severity': 'medium',
            'issue': f'{len(orphan_sessions)} orphan tmux sessions detected',
            'action': 'Investigate orphan sessions - may be leaked agents or manual sessions',
            'details': 'Tmux sessions exist but not tracked in registry'
        })

    if count_mismatch:
        recommendations.append({
            'severity': 'high',
            'issue': 'Active count mismatch between registry and reality',
            'action': 'Run validate_and_repair_registry() to fix counts',
            'details': 'Registry active_count does not match actual tmux session count'
        })

    if not recommendations:
        recommendations.append({
            'severity': 'info',
            'issue': 'No issues detected',
            'action': 'Registry is healthy',
            'details': 'All agents in registry match tmux sessions'
        })

    return recommendations

def validate_and_repair_registry(registry_path: str, dry_run: bool = False) -> Dict[str, Any]:
    """
    Scan tmux sessions and repair registry discrepancies.

    This function:
    1. Lists all active tmux sessions
    2. Compares with agents marked as active in registry
    3. Marks zombie agents (no tmux session) as 'terminated'
    4. Fixes active_count to match reality
    5. Updates total_spawned if needed

    Args:
        registry_path: Path to AGENT_REGISTRY.json
        dry_run: If True, report what would be changed without actually changing

    Returns:
        Repair report with changes made
    """
    try:
        # Get actual tmux sessions
        tmux_result = list_all_tmux_sessions()
        if not tmux_result['success']:
            return {
                'success': False,
                'error': f"Failed to list tmux sessions: {tmux_result.get('error')}",
                'changes_made': 0
            }

        actual_sessions = set(tmux_result['sessions'].keys())

        # Acquire exclusive lock for modification
        with open(registry_path, 'r+') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock

            # Load current registry
            registry = json.load(f)

            # Track changes
            changes = {
                'zombies_terminated': [],
                'orphans_found': [],
                'count_corrected': False,
                'old_active_count': registry.get('active_count', 0),
                'new_active_count': 0
            }

            # Process all agents
            active_statuses = {'running', 'working', 'blocked'}
            actual_active_count = 0

            for agent in registry.get('agents', []):
                agent_status = agent.get('status')
                tmux_session = agent.get('tmux_session')

                # Check if agent claims to be active
                if agent_status in active_statuses:
                    # Verify tmux session exists
                    if tmux_session and tmux_session in actual_sessions:
                        # Agent is truly active
                        actual_active_count += 1
                    else:
                        # Zombie agent - mark as terminated
                        if not dry_run:
                            agent['status'] = 'terminated'
                            agent['termination_reason'] = 'session_not_found'
                            agent['terminated_at'] = datetime.now().isoformat()
                            agent['last_update'] = datetime.now().isoformat()

                        changes['zombies_terminated'].append({
                            'agent_id': agent['id'],
                            'agent_type': agent.get('type'),
                            'old_status': agent_status,
                            'tmux_session': tmux_session,
                            'started_at': agent.get('started_at')
                        })

            # Find orphan sessions
            registry_sessions = {
                agent.get('tmux_session')
                for agent in registry.get('agents', [])
                if agent.get('tmux_session')
            }

            for session in actual_sessions:
                if session not in registry_sessions:
                    changes['orphans_found'].append(session)

            # Fix active_count
            if registry.get('active_count', 0) != actual_active_count:
                changes['count_corrected'] = True
                changes['new_active_count'] = actual_active_count
                if not dry_run:
                    registry['active_count'] = actual_active_count
            else:
                changes['new_active_count'] = actual_active_count

            # Write changes if not dry run
            if not dry_run:
                f.seek(0)
                f.write(json.dumps(registry, indent=2))
                f.truncate()
                logger.info(f"Registry repaired: {len(changes['zombies_terminated'])} zombies terminated, "
                           f"active_count corrected to {actual_active_count}")

            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            return {
                'success': True,
                'dry_run': dry_run,
                'registry_path': registry_path,
                'changes': changes,
                'zombies_terminated': len(changes['zombies_terminated']),
                'orphans_found': len(changes['orphans_found']),
                'count_corrected': changes['count_corrected'],
                'summary': (
                    f"{'[DRY RUN] ' if dry_run else ''}Terminated {len(changes['zombies_terminated'])} zombies, "
                    f"found {len(changes['orphans_found'])} orphans, "
                    f"{'corrected' if changes['count_corrected'] else 'verified'} active_count "
                    f"({changes['old_active_count']} -> {changes['new_active_count']})"
                )
            }
    except FileNotFoundError:
        return {
            'success': False,
            'error': f'Registry not found: {registry_path}',
            'changes_made': 0
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Repair exception: {str(e)}',
            'changes_made': 0
        }

def calculate_task_complexity(description: str) -> int:
    """Calculate task complexity to guide orchestration depth"""
    complexity_keywords = {
        'comprehensive': 5, 'complete': 4, 'full': 4, 'entire': 4,
        'system': 3, 'platform': 3, 'application': 3, 'website': 2,
        'frontend': 2, 'backend': 2, 'database': 2, 'api': 2,
        'testing': 2, 'security': 2, 'performance': 2, 'optimization': 2,
        'deployment': 2, 'ci/cd': 2, 'monitoring': 2, 'analytics': 2,
        'authentication': 2, 'authorization': 2, 'integration': 2
    }
    
    score = 1  # Base complexity
    description_lower = description.lower()
    
    for keyword, points in complexity_keywords.items():
        if keyword in description_lower:
            score += points
    
    # Additional factors
    if len(description) > 200:
        score += 2
    if 'layers' in description_lower or 'multi' in description_lower:
        score += 3
    if 'specialist' in description_lower or 'expert' in description_lower:
        score += 2
        
    return min(score, 20)  # Cap at 20

def generate_specialization_recommendations(task_description: str, current_depth: int) -> List[str]:
    """Dynamically recommend specialist agent types based on task context"""
    description_lower = task_description.lower()
    
    # Domain detection patterns
    domain_patterns = {
        'frontend': ['frontend', 'ui', 'ux', 'react', 'vue', 'angular', 'css', 'javascript', 'html'],
        'backend': ['backend', 'api', 'server', 'database', 'sql', 'node', 'python', 'java'],
        'design': ['design', 'ui/ux', 'visual', 'branding', 'typography', 'layout', 'user experience'],
        'data': ['data', 'analytics', 'metrics', 'tracking', 'database', 'sql', 'mongodb'],
        'security': ['security', 'auth', 'authentication', 'authorization', 'encryption', 'ssl'],
        'performance': ['performance', 'optimization', 'speed', 'caching', 'load', 'scalability'],
        'testing': ['testing', 'qa', 'test', 'validation', 'e2e', 'unit test', 'integration'],
        'devops': ['deployment', 'ci/cd', 'docker', 'kubernetes', 'infrastructure', 'monitoring'],
        'mobile': ['mobile', 'ios', 'android', 'react native', 'flutter', 'responsive'],
        'ai_ml': ['ai', 'ml', 'machine learning', 'recommendation', 'algorithm', 'intelligence']
    }
    
    recommendations = []
    
    for domain, keywords in domain_patterns.items():
        if any(keyword in description_lower for keyword in keywords):
            if current_depth == 1:
                # First level: broad coordinators
                recommendations.append(f"{domain}_lead")
            elif current_depth == 2:
                # Second level: specific specialists
                if domain == 'frontend':
                    recommendations.extend(['css_specialist', 'js_specialist', 'component_specialist', 'animation_specialist'])
                elif domain == 'backend':
                    recommendations.extend(['api_specialist', 'database_specialist', 'auth_specialist', 'integration_specialist'])
                elif domain == 'design':
                    recommendations.extend(['visual_designer', 'ux_researcher', 'interaction_designer', 'brand_specialist'])
                elif domain == 'data':
                    recommendations.extend(['data_engineer', 'analytics_specialist', 'visualization_expert', 'etl_specialist'])
            elif current_depth >= 3:
                # Deeper levels: hyper-specialized micro-agents
                recommendations.extend([
                    f"{domain}_optimizer", f"{domain}_validator", f"{domain}_implementer", f"{domain}_tester"
                ])
    
    # Always recommend some general specialists for comprehensive coverage
    if current_depth <= 2:
        recommendations.extend(['architect', 'quality_assurance', 'documentation_specialist'])
    
    return list(set(recommendations))  # Remove duplicates

def parse_markdown_context(content: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse markdown content to extract language, framework, and testing information.

    Args:
        content: Markdown file content
        context: Existing context dict to update

    Returns:
        Updated context dict with extracted information
    """
    content_lower = content.lower()

    # Language detection - search for explicit mentions
    language_keywords = {
        'python': ['python', 'py', 'pip', 'pyproject', 'virtualenv', 'venv'],
        'javascript': ['javascript', 'js', 'node.js', 'nodejs', 'npm'],
        'typescript': ['typescript', 'ts', 'tsc'],
        'go': ['golang', 'go ', ' go'],
        'rust': ['rust', 'cargo', 'rustc'],
        'java': ['java', 'jvm', 'maven', 'gradle'],
        'ruby': ['ruby', 'gem', 'bundler'],
        'php': ['php', 'composer'],
        'c++': ['c++', 'cpp', 'cmake'],
        'c#': ['c#', 'csharp', '.net', 'dotnet']
    }

    for lang, keywords in language_keywords.items():
        if any(kw in content_lower for kw in keywords):
            context['language'] = lang.title() if lang != 'c++' else 'C++'
            if lang == 'typescript':
                context['language'] = 'TypeScript'
            elif lang == 'javascript':
                context['language'] = 'JavaScript'
            break

    # Framework detection
    framework_keywords = {
        'FastMCP': ['fastmcp', 'fast mcp', 'mcp server'],
        'Django': ['django'],
        'Flask': ['flask'],
        'FastAPI': ['fastapi', 'fast api'],
        'React': ['react', 'reactjs'],
        'Vue': ['vue', 'vuejs', 'vue.js'],
        'Angular': ['angular'],
        'Next.js': ['next.js', 'nextjs'],
        'Express': ['express', 'expressjs'],
        'Svelte': ['svelte'],
        'Spring': ['spring boot', 'spring framework'],
        'Rails': ['rails', 'ruby on rails']
    }

    for framework, keywords in framework_keywords.items():
        if any(kw in content_lower for kw in keywords):
            if framework not in context['frameworks']:
                context['frameworks'].append(framework)

    # Testing framework detection
    testing_keywords = {
        'pytest': ['pytest'],
        'unittest': ['unittest'],
        'jest': ['jest'],
        'mocha': ['mocha'],
        'vitest': ['vitest'],
        'playwright': ['playwright'],
        'cypress': ['cypress'],
        'go test': ['go test', 'testing package'],
        'cargo test': ['cargo test'],
        'junit': ['junit']
    }

    for test_fw, keywords in testing_keywords.items():
        if any(kw in content_lower for kw in keywords):
            if not context['testing_framework']:
                context['testing_framework'] = test_fw
            break

    # Package manager detection
    pm_keywords = {
        'pip': ['pip', 'pypi'],
        'npm': ['npm'],
        'yarn': ['yarn'],
        'pnpm': ['pnpm'],
        'cargo': ['cargo'],
        'go mod': ['go mod', 'go modules'],
        'maven': ['maven'],
        'gradle': ['gradle']
    }

    for pm, keywords in pm_keywords.items():
        if any(kw in content_lower for kw in keywords):
            if not context['package_manager']:
                context['package_manager'] = pm
            break

    # Project type inference
    if 'mcp' in content_lower or 'fastmcp' in content_lower:
        context['project_type'] = 'mcp_server'
    elif any(fw in content_lower for fw in ['django', 'flask', 'fastapi', 'express', 'rails', 'spring']):
        context['project_type'] = 'web_application'
    elif any(fw in content_lower for fw in ['react', 'vue', 'angular', 'svelte', 'next']):
        context['project_type'] = 'web_application'

    return context

def detect_project_context(project_dir: str) -> Dict[str, Any]:
    """
    Detect project language, frameworks, testing tools, and patterns.
    Prioritizes human-curated markdown files over config file scanning.

    Priority order:
    1. .claude/CLAUDE.md (project-specific)
    2. project_context.md (project root)
    3. Config files (pyproject.toml, package.json, go.mod, etc.) as fallback

    Fast detection (<500ms) with graceful error handling.
    """
    cache_key = os.path.abspath(project_dir)
    if cache_key in _project_context_cache:
        return _project_context_cache[cache_key]

    context = {
        'language': 'Unknown',
        'frameworks': [],
        'testing_framework': None,
        'package_manager': None,
        'project_type': 'unknown',
        'config_files_found': [],
        'confidence': 'low',
        'source': 'none'
    }

    # PRIORITY 1: Check .claude/CLAUDE.md (relative to project_dir)
    claude_md_path = os.path.join(project_dir, '.claude', 'CLAUDE.md')
    if os.path.exists(claude_md_path):
        try:
            with open(claude_md_path, 'r', encoding='utf-8') as f:
                content = f.read()
                context = parse_markdown_context(content, context)
                context['source'] = '.claude/CLAUDE.md'
                context['confidence'] = 'high'
                context['config_files_found'].append('.claude/CLAUDE.md')
                _project_context_cache[cache_key] = context
                return context
        except Exception as e:
            logger.warning(f"Error reading .claude/CLAUDE.md: {e}")
            # Fall through to next priority

    # PRIORITY 2: Check project_context.md (project root)
    project_md_path = os.path.join(project_dir, 'project_context.md')
    if os.path.exists(project_md_path):
        try:
            with open(project_md_path, 'r', encoding='utf-8') as f:
                content = f.read()
                context = parse_markdown_context(content, context)
                context['source'] = 'project_context.md'
                context['confidence'] = 'high'
                context['config_files_found'].append('project_context.md')
                _project_context_cache[cache_key] = context
                return context
        except Exception as e:
            logger.warning(f"Error reading project_context.md: {e}")
            # Fall through to config file scanning

    # FALLBACK: Use config file scanning (existing logic)
    try:
        # Python detection
        pyproject_path = os.path.join(project_dir, 'pyproject.toml')
        if os.path.exists(pyproject_path):
            context['language'] = 'Python'
            context['config_files_found'].append('pyproject.toml')
            try:
                with open(pyproject_path, 'r') as f:
                    content = f.read().lower()
                    if 'fastmcp' in content:
                        context['frameworks'].append('FastMCP')
                        context['project_type'] = 'mcp_server'
                    if 'django' in content:
                        context['frameworks'].append('Django')
                        context['project_type'] = 'web_application'
                    if 'flask' in content:
                        context['frameworks'].append('Flask')
                        context['project_type'] = 'web_application'
                    if 'fastapi' in content:
                        context['frameworks'].append('FastAPI')
                        context['project_type'] = 'web_application'
                    if 'pytest' in content:
                        context['testing_framework'] = 'pytest'
                    if 'unittest' in content and not context['testing_framework']:
                        context['testing_framework'] = 'unittest'
                    context['package_manager'] = 'pip'
                    context['confidence'] = 'high'
            except Exception:
                pass

        requirements_path = os.path.join(project_dir, 'requirements.txt')
        if os.path.exists(requirements_path) and context['language'] == 'Unknown':
            context['language'] = 'Python'
            context['config_files_found'].append('requirements.txt')
            context['package_manager'] = 'pip'
            context['confidence'] = 'medium'
            try:
                with open(requirements_path, 'r') as f:
                    content = f.read().lower()
                    if 'fastmcp' in content:
                        context['frameworks'].append('FastMCP')
                        context['project_type'] = 'mcp_server'
                    if 'django' in content:
                        context['frameworks'].append('Django')
                        context['project_type'] = 'web_application'
                    if 'flask' in content:
                        context['frameworks'].append('Flask')
                        context['project_type'] = 'web_application'
                    if 'pytest' in content:
                        context['testing_framework'] = 'pytest'
            except Exception:
                pass

        # JavaScript/TypeScript detection
        package_json_path = os.path.join(project_dir, 'package.json')
        if os.path.exists(package_json_path):
            context['language'] = 'JavaScript'
            context['config_files_found'].append('package.json')
            try:
                with open(package_json_path, 'r') as f:
                    pkg_data = json.load(f)
                    deps = {**pkg_data.get('dependencies', {}), **pkg_data.get('devDependencies', {})}

                    if 'react' in deps:
                        context['frameworks'].append('React')
                        context['project_type'] = 'web_application'
                    if 'vue' in deps:
                        context['frameworks'].append('Vue')
                        context['project_type'] = 'web_application'
                    if 'angular' in deps or '@angular/core' in deps:
                        context['frameworks'].append('Angular')
                        context['project_type'] = 'web_application'
                    if 'next' in deps:
                        context['frameworks'].append('Next.js')
                        context['project_type'] = 'web_application'
                    if 'express' in deps:
                        context['frameworks'].append('Express')
                        context['project_type'] = 'web_application'
                    if 'jest' in deps:
                        context['testing_framework'] = 'jest'
                    if 'mocha' in deps and not context['testing_framework']:
                        context['testing_framework'] = 'mocha'
                    if 'playwright' in deps:
                        if not context['testing_framework']:
                            context['testing_framework'] = 'playwright'
                        context['frameworks'].append('Playwright')

                    # Check for lock files
                    if os.path.exists(os.path.join(project_dir, 'package-lock.json')):
                        context['package_manager'] = 'npm'
                    elif os.path.exists(os.path.join(project_dir, 'yarn.lock')):
                        context['package_manager'] = 'yarn'
                    elif os.path.exists(os.path.join(project_dir, 'pnpm-lock.yaml')):
                        context['package_manager'] = 'pnpm'
                    else:
                        context['package_manager'] = 'npm'

                    context['confidence'] = 'high'
            except Exception:
                context['package_manager'] = 'npm'
                context['confidence'] = 'low'

        tsconfig_path = os.path.join(project_dir, 'tsconfig.json')
        if os.path.exists(tsconfig_path) and context['language'] == 'JavaScript':
            context['language'] = 'TypeScript'
            context['config_files_found'].append('tsconfig.json')

        # Go detection
        go_mod_path = os.path.join(project_dir, 'go.mod')
        if os.path.exists(go_mod_path):
            context['language'] = 'Go'
            context['config_files_found'].append('go.mod')
            context['package_manager'] = 'go mod'
            context['testing_framework'] = 'go test'
            context['confidence'] = 'high'

        # Rust detection
        cargo_path = os.path.join(project_dir, 'Cargo.toml')
        if os.path.exists(cargo_path):
            context['language'] = 'Rust'
            context['config_files_found'].append('Cargo.toml')
            context['package_manager'] = 'cargo'
            context['testing_framework'] = 'cargo test'
            context['confidence'] = 'high'

    except Exception as e:
        logger.warning(f"Error detecting project context: {e}")

    # Set source for config file fallback
    if context['source'] == 'none' and context['config_files_found']:
        context['source'] = 'config_files'

    # Cache and return
    _project_context_cache[cache_key] = context
    return context


def format_project_context_prompt(context: Dict[str, Any]) -> str:
    """
    Format detected project context as a prompt section with implications and constraints.
    """
    if context['language'] == 'Unknown' or context['confidence'] == 'low':
        return """
🏗️ PROJECT CONTEXT:
Unable to auto-detect project details. Search for config files (package.json, pyproject.toml, go.mod, etc.) to understand project structure, language, and frameworks before proceeding.
"""

    frameworks_str = ', '.join(context['frameworks']) if context['frameworks'] else 'None detected'
    testing_str = context['testing_framework'] or 'Not detected'
    pm_str = context['package_manager'] or 'Not detected'

    source_str = context.get('source', 'unknown')
    prompt = f"""
🏗️ PROJECT CONTEXT (Source: {source_str}):
- Language: {context['language']}
- Frameworks: {frameworks_str}
- Testing: {testing_str}
- Package Manager: {pm_str}
- Project Type: {context['project_type']}
- Config Files: {', '.join(context['config_files_found'])}
"""

    # Add language-specific implications
    if context['language'] == 'Python':
        prompt += """
IMPLICATIONS FOR YOUR WORK:
- Use snake_case for functions and variables
- Follow PEP 8 style guidelines
- Check pyproject.toml or requirements.txt for dependencies before importing
- Write async functions if the project uses async/await patterns
"""
        if 'FastMCP' in context['frameworks']:
            prompt += """- Follow FastMCP conventions: @mcp.tool decorator for tools
- Use .fn attribute when calling MCP tools from within other MCP tools
"""
        if context['testing_framework'] == 'pytest':
            prompt += """- Add tests in tests/ directory with test_*.py naming
- Use pytest fixtures and assertions
"""
        prompt += """
DO NOT:
- Use camelCase (this is Python, not JavaScript)
- Import libraries not in requirements.txt/pyproject.toml
- Write synchronous code if async patterns are used
"""

    elif context['language'] in ['JavaScript', 'TypeScript']:
        prompt += """
IMPLICATIONS FOR YOUR WORK:
- Use camelCase for variables and functions
- Follow modern ES6+ syntax
- Check package.json for dependencies before importing
"""
        if context['testing_framework'] == 'jest':
            prompt += """- Write tests with .test.js or .spec.js suffix
- Use Jest assertions and mocking
"""
        elif context['testing_framework'] == 'playwright':
            prompt += """- Write browser automation tests using Playwright
- Follow page object model patterns
"""
        prompt += """
DO NOT:
- Use snake_case (this is JavaScript, not Python)
- Import packages not in package.json
- Use outdated var declarations (use const/let)
"""

    elif context['language'] == 'Go':
        prompt += """
IMPLICATIONS FOR YOUR WORK:
- Use Go naming conventions (exported names start with capital letter)
- Handle errors explicitly (if err != nil pattern)
- Write tests in *_test.go files
- Use go fmt for formatting

DO NOT:
- Ignore error returns
- Use try/catch (Go uses error returns)
- Import packages without go.mod entry
"""

    elif context['language'] == 'Rust':
        prompt += """
IMPLICATIONS FOR YOUR WORK:
- Use snake_case for functions and variables
- Handle Result and Option types properly
- Write tests with #[test] attribute
- Use cargo fmt for formatting

DO NOT:
- Use unwrap() without good reason (handle errors properly)
- Ignore compiler warnings
- Import crates not in Cargo.toml
"""

    return prompt


def format_task_enrichment_prompt(task_registry: Dict[str, Any]) -> str:
    """
    Format task enrichment context as a prompt section for agents.
    Reads task_context from registry and returns formatted markdown or empty string.

    Args:
        task_registry: Task registry dict that may contain 'task_context' field

    Returns:
        Formatted markdown section with task context, or empty string if no enrichment
    """
    task_context = task_registry.get('task_context', {})
    if not task_context:
        return ""

    sections = []

    # Background context
    if bg := task_context.get('background_context'):
        sections.append(f"""
📋 BACKGROUND CONTEXT:
{bg}
""")

    # Expected deliverables
    if deliverables := task_context.get('expected_deliverables'):
        items = '\n'.join(f"  • {d}" for d in deliverables)
        sections.append(f"""
✅ EXPECTED DELIVERABLES:
{items}
""")

    # Success criteria
    if criteria := task_context.get('success_criteria'):
        items = '\n'.join(f"  • {c}" for c in criteria)
        sections.append(f"""
🎯 SUCCESS CRITERIA:
{items}
""")

    # Constraints
    if constraints := task_context.get('constraints'):
        items = '\n'.join(f"  • {c}" for c in constraints)
        sections.append(f"""
⚠️ CONSTRAINTS:
{items}
""")

    # Relevant files (limit to first 10)
    if files := task_context.get('relevant_files'):
        items = '\n'.join(f"  • {f}" for f in files[:10])
        if len(files) > 10:
            items += f"\n  • ... and {len(files) - 10} more files"
        sections.append(f"""
📁 RELEVANT FILES TO EXAMINE:
{items}
""")

    # Related documentation
    if docs := task_context.get('related_documentation'):
        items = '\n'.join(f"  • {d}" for d in docs)
        sections.append(f"""
📚 RELATED DOCUMENTATION:
{items}
""")

    # Conversation history that led to this task
    if conv_history := task_context.get('conversation_history'):
        messages = conv_history.get('messages', [])
        metadata = conv_history.get('metadata', {})
        truncated_count = conv_history.get('truncated_count', 0)

        if messages:
            # Format messages with numbering and role indicators
            formatted_messages = []
            for idx, msg in enumerate(messages, 1):
                role = msg['role']
                content = msg['content']
                timestamp = msg.get('timestamp', 'unknown time')
                truncated_flag = " [TRUNCATED]" if msg.get('truncated') else ""

                # Parse timestamp to human-readable format
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp)
                    time_str = dt.strftime('%H:%M:%S')
                except:
                    time_str = timestamp

                # Role emoji mapping
                role_emoji = {
                    'user': '👤',
                    'assistant': '🤖',
                    'orchestrator': '🎯'
                }
                emoji = role_emoji.get(role, '💬')

                formatted_messages.append(
                    f"[{idx}] {emoji} {role.capitalize()} ({time_str}){truncated_flag}:\n    {content}\n"
                )

            messages_text = '\n'.join(formatted_messages)

            # Add metadata footer
            footer = f"\n📊 History metadata: {len(messages)} messages"
            if truncated_count > 0:
                footer += f", {truncated_count} truncated (user messages kept concise)"

            sections.append(f"""
💬 CONVERSATION HISTORY (Leading to This Task):

The orchestrator had the following conversation before creating this task.
This provides context for WHY this task exists and WHAT the user wants.

{messages_text}{footer}
""")

    if sections:
        return f"""
{'='*80}
🎯 TASK CONTEXT (Provided by task creator)
{'='*80}

{''.join(sections)}

{'='*80}
"""
    return ""


def create_orchestration_guidance_prompt(agent_type: str, task_description: str, current_depth: int, max_depth: int) -> str:
    """Generate dynamic guidance for orchestration based on context"""
    complexity = calculate_task_complexity(task_description)
    recommendations = generate_specialization_recommendations(task_description, current_depth + 1)
    
    if current_depth >= max_depth - 1:
        return "\n⚠️  DEPTH LIMIT REACHED - Focus on implementation rather than spawning children."
    
    # Determine orchestration intensity based on complexity and depth
    if complexity >= 15:
        intensity = "STRONGLY ENCOURAGED"
        child_count = "3-4 child agents"
    elif complexity >= 10:
        intensity = "ENCOURAGED"
        child_count = "2-3 child agents"
    else:
        intensity = "may consider"
        child_count = "1-2 child agents"
    
    guidance = f"""

🎯 ORCHESTRATION GUIDANCE (Depth {current_depth}/{max_depth}, Complexity: {complexity}/20):

You are {intensity} to spawn specialized child agents for better implementation quality.

RECOMMENDED CHILD SPECIALISTS:
{chr(10).join(f'• {agent}' for agent in recommendations[:6])}

🚀 ORCHESTRATION STRATEGY:
1. ANALYZE if your task benefits from specialization
2. SPAWN {child_count} with focused, specific roles
3. COORDINATE their work efficiently
4. Each child should handle a distinct domain

💡 NAMING CONVENTION: Use clear, descriptive names:
   - 'css_responsive_specialist' not just 'css'
   - 'api_authentication_handler' not just 'auth'
   - 'database_optimization_expert' not just 'db'

⭐ SUCCESS CRITERIA: Balance specialization with efficiency:
   - Spawn specialists only when beneficial
   - Coordinate effectively without micro-management
   - Deliver comprehensive, integrated results"""
    
    return guidance


def get_investigator_requirements() -> str:
    """Return investigator-specific requirements enforcing Read-First Development."""
    return """
🔍 INVESTIGATOR PROTOCOL - READ-FIRST DEVELOPMENT

📋 MANDATORY INVESTIGATION STEPS (IN ORDER):
1. CONTEXT GATHERING (30-40% of time):
   - Search codebase for existing patterns FIRST
   - Read relevant files to understand current state
   - Identify what exists vs what's missing
   - Check documentation, comments, git history
   - Map dependencies and relationships

2. PATTERN ANALYSIS (30-40% of time):
   - What patterns are used consistently?
   - What conventions must be followed?
   - What are the architectural boundaries?
   - What similar code exists that we can learn from?
   - What constraints exist (performance, compatibility)?

3. EVIDENCE COLLECTION (20-30% of time):
   - Document findings with file paths and line numbers
   - Quote relevant code sections
   - Capture metrics (file counts, complexity, coverage)
   - List gaps, issues, or inconsistencies found
   - Provide concrete examples, not generalizations

✅ SUCCESS CRITERIA - Definition of 'DONE':
Your investigation is ONLY complete when:
- All relevant code has been READ (not assumed)
- Findings are DOCUMENTED with evidence (file paths, line numbers)
- Patterns are IDENTIFIED and EXPLAINED (not just listed)
- Gaps or issues are SPECIFIC (not vague)
- Recommendations are ACTIONABLE (not generic)

📊 EVIDENCE REQUIRED FOR COMPLETION:
BEFORE reporting status='completed', you MUST provide:
1. Files you read - list specific paths and what you learned
2. Patterns you found - describe with code examples
3. Findings documented - use report_agent_finding for each discovery
4. Metrics collected - how many files, functions, patterns?
5. Gaps identified - what's missing or broken?
6. Recommendations - specific, actionable next steps

🚫 ANTI-PATTERNS TO AVOID:
- Assuming without reading actual code
- Generic findings without evidence
- Incomplete investigation (only surface-level)
- No concrete examples or quotes
- Vague recommendations like "needs improvement"
- Claiming done without documenting findings

🎯 FORCED SELF-INTERROGATION CHECKLIST:
Answer BEFORE claiming done:
1. Did I READ the code or just assume based on filenames?
2. Can I quote specific lines from files I claim to have analyzed?
3. Did I document findings with file paths and line numbers?
4. Are my recommendations specific and actionable?
5. What did I miss? What should I investigate deeper?
6. Would another investigator reach the same conclusions from my findings?

🔍 VALIDATION CHECKPOINT - Answer Before Claiming Complete:

Run this self-check. If you answer 'NO' to ANY question, you are NOT done:

□ Did I read at least 3 relevant files? (List them: ___, ___, ___)
□ Can I cite specific line numbers for my findings? (Show examples: file.py:123, ...)
□ Did I document findings using report_agent_finding? (How many: ___)
□ Did I identify at least 2 alternative approaches? (List: 1.___, 2.___)
□ Are my findings specific enough that a builder could act on them without asking questions?
□ Did I check for similar patterns elsewhere in the codebase?
□ Would a senior engineer approve this investigation without follow-up questions?

If ANY checkbox is unchecked, CONTINUE investigating before reporting completed.
"""


def get_builder_requirements() -> str:
    """Return builder-specific requirements enforcing Quality Implementation."""
    return """
🏗️ BUILDER PROTOCOL - QUALITY IMPLEMENTATION

📋 MANDATORY BUILD STEPS (IN ORDER):
1. UNDERSTAND BEFORE CODING (30% of time):
   - Read existing code to match style and patterns
   - Identify project conventions (naming, structure, testing)
   - Check what APIs must NOT break (backward compatibility)
   - Search for similar existing implementations
   - Identify constraints: performance, security, compatibility

2. ERROR-FIRST IMPLEMENTATION (40% of time):
   - Think: What can go wrong? List failure modes FIRST
   - Implement error handling for edge cases BEFORE happy path
   - What if input is null/empty/invalid/huge?
   - What if network fails? What if dependency is unavailable?
   - Add logging for debugging future issues

3. TEST AND VERIFY (30% of time):
   - Write or update tests for new functionality
   - Test edge cases (empty, null, boundary values)
   - Run test suite - MUST pass before claiming done
   - Manual testing: actually use what you built
   - Check: did I break anything else?

✅ SUCCESS CRITERIA - Definition of 'DONE':
Your build is ONLY complete when:
- Tests pass (show test output)
- Edge cases handled (null, empty, invalid, boundary)
- No regressions (existing functionality still works)
- Code follows project patterns (style, structure, conventions)
- Error handling is comprehensive (not just happy path)

📊 EVIDENCE REQUIRED FOR COMPLETION:
BEFORE reporting status='completed', you MUST provide:
1. List of files you modified (with what changed)
2. Test results - show actual command output
3. Edge cases you handled - list them specifically
4. Manual testing performed - what did you test?
5. Impact analysis - what else could this affect?
6. Self-review - what's the weakest part of your implementation?

🚫 ANTI-PATTERNS TO AVOID:
- Coding before understanding existing patterns
- Implementing without error handling
- Not testing edge cases (null, empty, invalid)
- Claiming done without running tests
- Breaking existing APIs without migration path
- No logging for future debugging
- Leaving debug code or console.logs

🎯 FORCED SELF-INTERROGATION CHECKLIST:
Answer BEFORE claiming done:
1. Did tests pass? Show command output.
2. What files did I modify? List them.
3. What edge cases did I handle? Name 3 minimum.
4. What breaks if input is null/empty/invalid?
5. Did I manually test this? What did I test?
6. What's the weakest part of my implementation?
7. Would I approve this PR if someone else wrote it?

🔍 VALIDATION CHECKPOINT - Answer Before Claiming Complete:

Run this self-check. If you answer 'NO' to ANY question, you are NOT done:

□ Did tests pass? (Show command output: ___)
□ What files did I modify? (List them: ___)
□ What edge cases did I handle? (Name 3 minimum: ___, ___, ___)
□ What breaks if input is null/empty/invalid? (Answer: ___)
□ Did I manually test this? (What did I test: ___)
□ What's the weakest part of my implementation? (Be honest: ___)
□ Would I approve this PR if someone else wrote it? (Yes/No with reason: ___)
□ Did I add error handling and logging for debugging?
□ Does my code follow project patterns and conventions?

If ANY checkbox is unchecked, CONTINUE building before reporting completed.
"""


def get_fixer_requirements() -> str:
    """Return fixer-specific requirements enforcing Root Cause Diagnosis."""
    return """
🔧 FIXER PROTOCOL - ROOT CAUSE DIAGNOSIS

📋 MANDATORY DEBUGGING STEPS (IN ORDER):
1. REPRODUCE FIRST (25% of time):
   - Reproduce the bug reliably with exact steps
   - Document EXACT reproduction steps (command/input/environment)
   - If you can't reproduce it, you can't verify the fix
   - Test on clean environment: is it environmental or code?
   - Verify error message/behavior matches reported issue

2. ROOT CAUSE ANALYSIS (40% of time):
   - Identify root cause, NOT just symptoms
   - Ask: Why did this happen? Trace execution path
   - Read the actual code, don't trust error messages
   - Check git history: when was this introduced? Why?
   - Is this a regression? Was it working before?
   - What assumptions were violated?

3. FIX AND VERIFY (25% of time):
   - Fix the root cause, not the symptom
   - Verify fix addresses the actual problem
   - Test that bug no longer reproduces
   - Add regression test to prevent recurrence
   - Check: did my fix break anything else?

4. PREVENT RECURRENCE (10% of time):
   - Search for similar bugs in other code
   - Add tests for edge cases that caused this
   - Update documentation if assumptions were wrong
   - Consider: how could we have caught this earlier?

✅ SUCCESS CRITERIA - Definition of 'DONE':
Your fix is ONLY complete when:
- Bug is reproducible (documented exact steps)
- Root cause identified (not just symptoms)
- Fix verified (bug no longer occurs)
- Regression tests added (prevents future recurrence)
- Similar issues checked (are there other instances?)

📊 EVIDENCE REQUIRED FOR COMPLETION:
BEFORE reporting status='completed', you MUST provide:
1. Bug reproduction steps - exact commands/input
2. Root cause explanation - why did this happen?
3. Files modified to fix the issue
4. Test results - show bug fixed
5. Regression tests added - show test code
6. Similar issues checked - where did you look?

🚫 ANTI-PATTERNS TO AVOID:
- Fixing symptoms instead of root cause
- Claiming fix without reproducing bug first
- No regression tests to prevent recurrence
- Not checking for similar bugs elsewhere
- Trusting error messages without reading code
- Not verifying the fix actually works
- Breaking other functionality with the fix

🔍 VALIDATION CHECKPOINT - Answer Before Claiming Complete:

Run this self-check. If you answer 'NO' to ANY question, you are NOT done:

□ Can I reproduce the bug? (Show exact steps: ___)
□ What is the root cause? (Explain why it happens: ___)
□ Does my fix address root cause or just symptoms? (Which: ___)
□ Did I verify the bug no longer occurs? (How: ___)
□ What regression tests did I add? (Show test code or file: ___)
□ Did I check for similar bugs? (Where did I look: ___)
□ Could my fix break anything else? (Analyzed: ___)
□ Did I update documentation if assumptions were wrong? (Files: ___)

If ANY checkbox is unchecked, CONTINUE fixing before reporting completed.
"""


def get_universal_protocol() -> str:
    """
    Return universal protocol that works for ANY agent type without restriction.
    Allows fully dynamic agent types per user request for flexibility.

    The specialized protocols (investigator/builder/fixer) remain available as reference
    but are no longer enforced, enabling custom agent types like 'jwt-validator',
    'security-analyzer', etc. without forcing them into predefined buckets.
    """
    return """
📋 AGENT PROTOCOL - SYSTEMATIC APPROACH

🎯 MISSION EXECUTION STEPS:
1. UNDERSTAND (30% of time):
   - Read relevant code/documentation to understand context
   - Identify what exists vs what needs to change
   - Check project conventions and patterns
   - Map dependencies and constraints

2. PLAN & IMPLEMENT (40% of time):
   - Break down the task into specific steps
   - Consider edge cases and error scenarios
   - Implement with proper error handling
   - Follow project coding standards

3. VERIFY & DOCUMENT (30% of time):
   - Test your changes work correctly
   - Check for regressions or side effects
   - Document findings with file:line citations
   - Provide evidence of completion

✅ SUCCESS CRITERIA - Definition of 'DONE':
Your work is ONLY complete when:
- Task requirements fully addressed (not partial)
- Changes tested and verified working
- Evidence provided (file paths, test results, findings)
- No regressions introduced
- Work follows project patterns and conventions

📊 EVIDENCE REQUIRED FOR COMPLETION:
BEFORE reporting status='completed', you MUST provide:
1. What you accomplished - specific changes made
2. Files modified - list paths with what changed
3. Testing performed - show results/output
4. Findings documented - use report_agent_finding for discoveries
5. Quality check - did you verify it works?

🚫 ANTI-PATTERNS TO AVOID:
- Assuming without reading actual code
- Generic findings without specific evidence
- Claiming done without testing/verification
- Breaking existing functionality
- No file:line citations for your findings

🎯 FORCED SELF-INTERROGATION CHECKLIST:
Answer BEFORE claiming done:
1. Did I READ the relevant code or assume?
2. Can I cite specific files/lines I analyzed or modified?
3. Did I TEST my changes work?
4. Did I document findings with evidence?
5. What could go wrong? Did I handle edge cases?
6. Would I accept this work quality from someone else?
"""

def get_type_specific_requirements(agent_type: str) -> str:
    """Get type-specific requirements for agent based on type.

    Now fully dynamic - accepts ANY agent_type string without restriction.
    Specialized protocols (investigator/builder/fixer) kept for reference
    but no longer enforced, allowing custom types like 'jwt-validator',
    'security-analyzer', 'performance-optimizer', etc.

    Args:
        agent_type: Type of agent - ANY string accepted

    Returns:
        Universal protocol that works for all agent types
    """
    # Check if user wants a specific specialized protocol (optional)
    # Otherwise, return universal protocol that works for any type
    type_specific_protocols = {
        'investigator': get_investigator_requirements,
        'builder': get_builder_requirements,
        'fixer': get_fixer_requirements,
    }

    # If agent_type exactly matches a specialized protocol, use it
    # Otherwise use universal protocol (allows ANY custom type)
    if agent_type.lower() in type_specific_protocols:
        return type_specific_protocols[agent_type.lower()]()
    else:
        # Universal protocol works for ANY agent type - fully dynamic
        return get_universal_protocol()


def resolve_workspace_variables(path: str) -> str:
    """
    Resolve template variables in workspace paths.

    Detects and resolves template variables like:
    - ${workspaceFolder} (VSCode/Claude Code style)
    - $WORKSPACE_FOLDER (environment variable style)
    - {workspaceFolder} (simple bracket style)

    Resolves them to os.getcwd() (the actual project directory).

    Args:
        path: Path string that may contain template variables

    Returns:
        Resolved path with template variables replaced

    Examples:
        >>> resolve_workspace_variables("${workspaceFolder}")
        "/Users/user/project"
        >>> resolve_workspace_variables("${workspaceFolder}/subdir")
        "/Users/user/project/subdir"
        >>> resolve_workspace_variables("/absolute/path")
        "/absolute/path"
        >>> resolve_workspace_variables(None)
        None
    """
    # Handle None and empty strings
    if not path:
        return path

    # Get the actual workspace folder (current working directory)
    actual_workspace = os.getcwd()

    # Define template patterns to detect and replace
    # Order matters: more specific patterns first
    patterns = [
        r'\$\{workspaceFolder\}',      # ${workspaceFolder}
        r'\$\{WORKSPACE_FOLDER\}',     # ${WORKSPACE_FOLDER}
        r'\$WORKSPACE_FOLDER',         # $WORKSPACE_FOLDER
        r'\{workspaceFolder\}',        # {workspaceFolder}
        r'\{WORKSPACE_FOLDER\}',       # {WORKSPACE_FOLDER}
    ]

    resolved_path = path
    for pattern in patterns:
        resolved_path = re.sub(pattern, actual_workspace, resolved_path)

    # If path was already resolved (absolute path without template vars), return as-is
    return resolved_path


# ============================================================================
# JSONL Utility Functions for Agent Log Management
# ============================================================================

def parse_jsonl_robust(file_path: str) -> List[Dict[str, Any]]:
    """
    Parse JSONL file with robust error recovery.

    Handles edge cases:
    - Incomplete lines from agent crashes (SIGKILL)
    - Malformed JSON
    - Empty lines
    - File corruption

    Args:
        file_path: Path to JSONL file

    Returns:
        List of successfully parsed JSON objects. Malformed lines are skipped
        with a warning logged.

    Examples:
        >>> parse_jsonl_robust("agent_stream.jsonl")
        [{"timestamp": "...", "type": "progress"}, ...]
    """
    if not os.path.exists(file_path):
        return []

    if os.path.getsize(file_path) == 0:
        return []

    lines = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:  # Skip empty lines
                continue

            try:
                parsed = json.loads(line)
                lines.append(parsed)
            except json.JSONDecodeError as e:
                # Log warning but continue parsing
                logger.warning(f"Malformed JSON at {file_path}:{line_num}: {e}")
                # Include error record for debugging
                lines.append({
                    "type": "parse_error",
                    "line_number": line_num,
                    "raw_content": line[:200],  # Truncate for safety
                    "error": str(e)
                })

    return lines


def tail_jsonl_efficient(file_path: str, n_lines: int = 100) -> List[Dict[str, Any]]:
    """
    Efficiently read last N lines from JSONL file using file seeking.

    Critical for large logs (10GB+) - avoids loading entire file into memory.
    Performance requirement: <100ms even for 10GB files.

    Algorithm:
    - For files >10MB: Seek from EOF, estimate bytes = n_lines * 300
    - Binary mode seeking to avoid encoding issues
    - Parse only tail portion
    - Return last N valid JSONL entries

    Args:
        file_path: Path to JSONL file
        n_lines: Number of lines to return from end of file

    Returns:
        List of last N successfully parsed JSON objects

    Examples:
        >>> tail_jsonl_efficient("large_agent.jsonl", 100)
        [{"timestamp": "...", "message": "..."}, ...]  # Last 100 lines
    """
    if not os.path.exists(file_path):
        return []

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return []

    # For small files (<10MB), just parse entire file
    if file_size < 10 * 1024 * 1024:  # 10MB
        all_lines = parse_jsonl_robust(file_path)
        return all_lines[-n_lines:] if len(all_lines) > n_lines else all_lines

    # For large files: efficient tail using seeking
    # Estimate: average line ~200 bytes, read 50% extra to ensure we get n_lines
    seek_size = min(n_lines * 300, file_size)

    try:
        with open(file_path, 'rb') as f:
            # Acquire shared lock (multiple readers OK, blocks writers)
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                f.seek(-seek_size, os.SEEK_END)
                data = f.read().decode('utf-8', errors='ignore')
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        lines = data.split('\n')
        valid_lines = []

        # Parse from end, collecting last n_lines valid JSON objects
        for line in reversed(lines):
            if len(valid_lines) >= n_lines:
                break

            line = line.strip()
            if not line:
                continue

            try:
                parsed = json.loads(line)
                valid_lines.append(parsed)
            except json.JSONDecodeError:
                # Skip malformed lines in tail
                continue

        return list(reversed(valid_lines))

    except Exception as e:
        logger.error(f"Error tailing {file_path}: {e}")
        # Fallback: try parsing entire file
        all_lines = parse_jsonl_robust(file_path)
        return all_lines[-n_lines:] if len(all_lines) > n_lines else all_lines


# ============================================================================
# Cursor CLI Stream-JSON Parser Functions
# ============================================================================

def parse_cursor_stream_jsonl(log_file: str, include_thinking: bool = None) -> Dict[str, Any]:
    """
    Parse cursor-agent stream-json output and extract structured information.
    
    Cursor stream-json format emits NDJSON events with types:
    - system: Initialization metadata
    - user: User messages
    - thinking: Internal reasoning (if thinking model used)
    - assistant: Assistant responses
    - tool_call: Tool invocations with results
    - result: Final completion status
    
    Args:
        log_file: Path to cursor-agent stream-json log file
        include_thinking: Whether to include thinking deltas (defaults to CURSOR_ENABLE_THINKING_LOGS)
    
    Returns:
        Dictionary with parsed information:
        {
            "session_id": str,
            "events": List[Dict],
            "tool_calls": List[Dict],
            "assistant_messages": List[str],
            "thinking_text": str (if include_thinking=True),
            "final_result": Dict or None,
            "duration_ms": int,
            "success": bool,
            "error": str or None
        }
    """
    if include_thinking is None:
        include_thinking = CURSOR_ENABLE_THINKING_LOGS
    
    if not os.path.exists(log_file):
        return {
            "success": False,
            "error": f"Log file not found: {log_file}"
        }
    
    result = {
        "session_id": None,
        "events": [],
        "tool_calls": [],
        "assistant_messages": [],
        "thinking_text": "",
        "final_result": None,
        "duration_ms": 0,
        "success": False,
        "error": None,
        "model": None,
        "cwd": None
    }
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                
                try:
                    event = json.loads(line)
                    event_type = event.get("type")
                    
                    # Extract session_id from any event that has it
                    if "session_id" in event and not result["session_id"]:
                        result["session_id"] = event["session_id"]
                    
                    # System initialization
                    if event_type == "system" and event.get("subtype") == "init":
                        result["model"] = event.get("model")
                        result["cwd"] = event.get("cwd")
                        result["events"].append({
                            "type": "system_init",
                            "model": event.get("model"),
                            "cwd": event.get("cwd"),
                            "permission_mode": event.get("permissionMode")
                        })
                    
                    # Thinking deltas (optional)
                    elif event_type == "thinking" and include_thinking:
                        if event.get("subtype") == "delta":
                            text = event.get("text", "")
                            if text:
                                result["thinking_text"] += text
                        elif event.get("subtype") == "completed":
                            result["events"].append({
                                "type": "thinking_completed",
                                "timestamp_ms": event.get("timestamp_ms")
                            })
                    
                    # Assistant messages
                    elif event_type == "assistant":
                        message = event.get("message", {})
                        content = message.get("content", [])
                        for item in content:
                            if item.get("type") == "text":
                                text = item.get("text", "")
                                result["assistant_messages"].append(text)
                                result["events"].append({
                                    "type": "assistant_message",
                                    "text": text,
                                    "timestamp_ms": event.get("timestamp_ms"),
                                    "model_call_id": event.get("model_call_id")
                                })
                    
                    # Tool calls
                    elif event_type == "tool_call":
                        tool_call_info = parse_cursor_tool_call(event)
                        if tool_call_info:
                            result["tool_calls"].append(tool_call_info)
                            result["events"].append({
                                "type": "tool_call",
                                "subtype": event.get("subtype"),
                                "tool_info": tool_call_info,
                                "timestamp_ms": event.get("timestamp_ms")
                            })
                    
                    # Final result
                    elif event_type == "result":
                        result["final_result"] = {
                            "subtype": event.get("subtype"),
                            "is_error": event.get("is_error", False),
                            "duration_ms": event.get("duration_ms", 0),
                            "result_text": event.get("result", ""),
                            "request_id": event.get("request_id")
                        }
                        result["duration_ms"] = event.get("duration_ms", 0)
                        result["success"] = event.get("subtype") == "success" and not event.get("is_error", False)
                        if event.get("is_error"):
                            result["error"] = event.get("result", "Unknown error")
                
                except json.JSONDecodeError as e:
                    logger.warning(f"Malformed JSON at line {line_num} in {log_file}: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error parsing line {line_num} in {log_file}: {e}")
                    continue
        
        return result

    except Exception as e:
        logger.error(f"Error reading cursor log file {log_file}: {e}")
        return {
            "success": False,
            "error": f"Failed to read log file: {e}"
        }


def truncate_content_smart(content: str, max_len: int = 500, keep_tail: int = 100) -> str:
    """
    Smart truncation that keeps beginning and end of content.

    Args:
        content: String to truncate
        max_len: Maximum total length
        keep_tail: Chars to preserve at end

    Returns:
        Truncated string with middle removed if needed
    """
    if not content or len(content) <= max_len:
        return content

    head_len = max_len - keep_tail - 30  # 30 chars for ellipsis marker
    if head_len < 50:
        head_len = 50
        keep_tail = max_len - head_len - 30

    return f"{content[:head_len]}\n... [{len(content) - head_len - keep_tail} chars truncated] ...\n{content[-keep_tail:]}"


def truncate_tool_result_smart(tool_info: Dict[str, Any], aggressive: bool = False) -> Dict[str, Any]:
    """
    Apply smart truncation to tool call results.

    Args:
        tool_info: Parsed tool call dictionary
        aggressive: Use aggressive limits (True for recent logs)

    Returns:
        Tool info with truncated content
    """
    # Truncation limits
    stdout_limit = 300 if aggressive else 1000
    stderr_limit = 500  # Keep more stderr (errors are important)
    file_content_limit = 200 if aggressive else 500
    diff_limit = 300 if aggressive else 800

    result = tool_info.copy()

    # Truncate stdout
    if 'stdout' in result and result['stdout']:
        result['stdout'] = truncate_content_smart(result['stdout'], stdout_limit, 50)

    # Truncate stderr (keep more - errors matter)
    if 'stderr' in result and result['stderr']:
        result['stderr'] = truncate_content_smart(result['stderr'], stderr_limit, 100)

    # Truncate file content
    if 'file_content' in result and result['file_content']:
        result['file_content'] = truncate_content_smart(result['file_content'], file_content_limit, 50)

    # Truncate diff strings
    if 'diff_string' in result and result['diff_string']:
        result['diff_string'] = truncate_content_smart(result['diff_string'], diff_limit, 100)

    return result


def truncate_tool_result_content(content: str, is_error: bool, aggressive: bool) -> str:
    """
    Intelligently truncate tool result content based on content type.

    Truncation rules:
    - Errors: Keep more (500 chars) - debugging matters
    - Read results (file content): HARD truncate (100 chars) - just show it worked
    - MCP coordination results: Strip task_status, keep success/error only
    - Grep/Glob results: Keep more (300 chars) - search results useful
    - Other: Default truncate (150 chars)

    Args:
        content: Raw tool result content string
        is_error: Whether this result is an error
        aggressive: Whether to use aggressive truncation

    Returns:
        Truncated content string
    """
    if not content:
        return ""

    content_len = len(content)

    # Errors - keep more for debugging
    if is_error:
        limit = 500 if aggressive else 1000
        if content_len <= limit:
            return content
        return content[:limit] + f"... [{content_len - limit} more chars]"

    # Try to parse as JSON for smarter handling
    try:
        data = json.loads(content)

        # MCP coordination results (update_agent_progress, report_agent_finding)
        if isinstance(data, dict):
            # Strip task_status entirely - it's huge and redundant
            if "task_status" in data:
                summary = {
                    "success": data.get("success"),
                    "agent_id": data.get("agent_id", data.get("own_update", {}).get("agent_id")),
                }
                if data.get("own_update"):
                    summary["status"] = data["own_update"].get("status")
                    summary["progress"] = data["own_update"].get("progress")
                if data.get("own_finding"):
                    summary["finding_type"] = data["own_finding"].get("finding_type")
                    summary["severity"] = data["own_finding"].get("severity")
                return f"MCP: {json.dumps(summary)}"

            # get_agent_output results - just show success + agent
            if "output" in data and "agent_id" in data:
                output_size = len(str(data.get("output", "")))
                return f"agent_output: {data.get('agent_id', 'unknown')} ({output_size} chars)"

            # Other success responses
            if "success" in data:
                return f"success={data['success']}" + (f" error={data.get('error', '')[:100]}" if not data['success'] else "")

    except (json.JSONDecodeError, TypeError):
        pass

    # Read tool results (file content with line numbers)
    if "→" in content[:200] and any(c.isdigit() for c in content[:20]):
        # This is file content with line numbers like "  123→ code here"
        lines = content.split('\n')
        if aggressive:
            # Just show first 2 lines
            preview = '\n'.join(lines[:2])[:100]
            return f"[{len(lines)} lines] {preview}..."
        else:
            preview = '\n'.join(lines[:5])[:300]
            return f"[{len(lines)} lines]\n{preview}..."

    # Grep/Glob results - slightly more generous
    if "matches found" in content.lower() or "No matches" in content:
        limit = 200 if aggressive else 400
        if content_len <= limit:
            return content
        return content[:limit] + f"... [{content_len - limit} more]"

    # Default truncation
    limit = 100 if aggressive else 200
    if content_len <= limit:
        return content
    return content[:limit] + f"... [{content_len - limit} more]"


def parse_cursor_stream_jsonl_recent(
    log_file: str,
    recent_lines: int = 100,
    include_thinking: bool = False,
    aggressive_truncate: bool = True
) -> Dict[str, Any]:
    """
    Parse RECENT cursor-agent stream-json output efficiently.

    This function:
    1. Reads FIRST line for system init (session_id, model, cwd)
    2. Tails LAST N lines for recent activity
    3. Applies smart truncation to tool results
    4. Skips thinking blocks by default (huge token cost)

    Args:
        log_file: Path to cursor-agent stream-json log file
        recent_lines: Number of recent lines to parse (default 100)
        include_thinking: Include thinking deltas (default False - saves tokens)
        aggressive_truncate: Apply aggressive content truncation (default True)

    Returns:
        Dictionary with parsed recent activity:
        {
            "session_id": str,
            "model": str,
            "cwd": str,
            "recent_events": List[Dict],  # Recent events only
            "recent_tool_calls": List[Dict],
            "recent_messages": List[str],
            "final_result": Dict or None,
            "stats": {
                "total_lines": int,
                "lines_parsed": int,
                "truncation_applied": bool
            },
            "success": bool
        }
    """
    if not os.path.exists(log_file):
        return {
            "success": False,
            "error": f"Log file not found: {log_file}"
        }

    result = {
        "session_id": None,
        "model": None,
        "cwd": None,
        "recent_events": [],
        "recent_tool_calls": [],
        "recent_messages": [],
        "final_result": None,
        "stats": {
            "total_lines": 0,
            "lines_parsed": 0,
            "truncation_applied": aggressive_truncate
        },
        "success": True
    }

    try:
        # Step 1: Count total lines and read first line (system init)
        with open(log_file, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            total_lines = 1
            for _ in f:
                total_lines += 1

        result["stats"]["total_lines"] = total_lines

        # Parse first line for system init info
        if first_line:
            try:
                first_event = json.loads(first_line)
                if first_event.get("type") == "system" and first_event.get("subtype") == "init":
                    result["session_id"] = first_event.get("session_id")
                    result["model"] = first_event.get("model")
                    result["cwd"] = first_event.get("cwd")
            except json.JSONDecodeError:
                pass

        # Step 2: Tail last N lines efficiently
        lines_to_read = min(recent_lines, total_lines)
        recent_raw_lines = []

        with open(log_file, 'rb') as f:
            # Seek to end and work backwards
            f.seek(0, 2)  # End of file
            file_size = f.tell()

            if file_size == 0:
                return result

            # Read chunks from end until we have enough lines
            buffer = b''
            chunk_size = 8192
            position = file_size

            while len(recent_raw_lines) < lines_to_read and position > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                f.seek(position)
                chunk = f.read(read_size)
                buffer = chunk + buffer

                # Split into lines
                lines = buffer.split(b'\n')

                # Keep incomplete first line in buffer for next iteration
                if position > 0:
                    buffer = lines[0]
                    recent_raw_lines = lines[1:] + recent_raw_lines
                else:
                    recent_raw_lines = lines + recent_raw_lines

            # Trim to requested count and remove empty lines
            recent_raw_lines = [l for l in recent_raw_lines if l.strip()][-lines_to_read:]

        result["stats"]["lines_parsed"] = len(recent_raw_lines)

        # Step 3: Parse recent lines
        for raw_line in recent_raw_lines:
            try:
                line = raw_line.decode('utf-8') if isinstance(raw_line, bytes) else raw_line
                event = json.loads(line.strip())
                event_type = event.get("type")

                # Extract session_id if not yet found
                if "session_id" in event and not result["session_id"]:
                    result["session_id"] = event["session_id"]

                # Skip thinking by default (huge token cost)
                if event_type == "thinking" and not include_thinking:
                    continue

                # Assistant messages - keep full text
                if event_type == "assistant":
                    message = event.get("message", {})
                    content = message.get("content", [])
                    for item in content:
                        if item.get("type") == "text":
                            text = item.get("text", "")
                            if text:
                                result["recent_messages"].append(text)
                                result["recent_events"].append({
                                    "type": "assistant_message",
                                    "text": text[:500] if aggressive_truncate else text,
                                    "timestamp_ms": event.get("timestamp_ms")
                                })

                # Tool calls - with smart truncation
                elif event_type == "tool_call":
                    tool_info = parse_cursor_tool_call(event)
                    if tool_info:
                        # Apply smart truncation
                        truncated_tool = truncate_tool_result_smart(tool_info, aggressive_truncate)
                        result["recent_tool_calls"].append(truncated_tool)
                        result["recent_events"].append({
                            "type": "tool_call",
                            "subtype": event.get("subtype"),
                            "tool_info": truncated_tool
                        })

                # Final result - always include
                elif event_type == "result":
                    result["final_result"] = {
                        "subtype": event.get("subtype"),
                        "is_error": event.get("is_error", False),
                        "duration_ms": event.get("duration_ms", 0),
                        "result_text": truncate_content_smart(event.get("result", ""), 500, 100) if aggressive_truncate else event.get("result", "")
                    }
                    result["recent_events"].append({
                        "type": "result",
                        "subtype": event.get("subtype"),
                        "is_error": event.get("is_error", False),
                        "duration_ms": event.get("duration_ms", 0)
                    })

                # User messages (tool results) - AGGRESSIVE summarization
                elif event_type == "user":
                    msg = event.get("message", {})
                    content = msg.get("content", [])
                    for item in content:
                        if item.get("type") == "tool_result":
                            tool_use_id = item.get("tool_use_id", "")
                            is_error = item.get("is_error", False)
                            raw_content = str(item.get("content", ""))

                            # Smart truncation based on content type
                            truncated = truncate_tool_result_content(raw_content, is_error, aggressive_truncate)

                            result["recent_events"].append({
                                "type": "tool_result",
                                "tool_use_id": tool_use_id[-8:] if tool_use_id else "",
                                "is_error": is_error,
                                "preview": truncated
                            })

            except json.JSONDecodeError:
                continue
            except Exception as e:
                logger.warning(f"Error parsing recent log line: {e}")
                continue

        return result

    except Exception as e:
        logger.error(f"Error reading cursor log file {log_file}: {e}")
        return {
            "success": False,
            "error": f"Failed to read log file: {e}"
        }


def parse_cursor_tool_call(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Parse a cursor tool_call event and extract relevant information.
    
    Args:
        event: Tool call event from cursor stream-json
    
    Returns:
        Dictionary with tool call info, or None if not parseable
    """
    tool_call = event.get("tool_call", {})
    call_id = event.get("call_id")
    subtype = event.get("subtype")  # "started" or "completed"
    
    # Shell tool calls
    if "shellToolCall" in tool_call:
        shell_info = tool_call["shellToolCall"]
        args = shell_info.get("args", {})
        result_data = shell_info.get("result", {})
        
        info = {
            "tool_type": "shell",
            "call_id": call_id,
            "status": subtype,
            "command": args.get("command"),
            "working_directory": args.get("workingDirectory"),
            "timeout": args.get("timeout"),
        }
        
        # Add result info if completed
        if subtype == "completed":
            if "success" in result_data:
                success = result_data["success"]
                info.update({
                    "success": True,
                    "exit_code": success.get("exitCode"),
                    "stdout": success.get("stdout", ""),
                    "stderr": success.get("stderr", ""),
                    "execution_time_ms": success.get("executionTime")
                })
            elif "failure" in result_data:
                failure = result_data["failure"]
                info.update({
                    "success": False,
                    "exit_code": failure.get("exitCode"),
                    "stdout": failure.get("stdout", ""),
                    "stderr": failure.get("stderr", ""),
                    "execution_time_ms": failure.get("executionTime")
                })
        
        return info
    
    # Edit tool calls (file operations)
    elif "editToolCall" in tool_call:
        edit_info = tool_call["editToolCall"]
        args = edit_info.get("args", {})
        result_data = edit_info.get("result", {})
        
        info = {
            "tool_type": "edit",
            "call_id": call_id,
            "status": subtype,
            "path": args.get("path"),
        }
        
        # Add result info if completed
        if subtype == "completed" and "success" in result_data:
            success = result_data["success"]
            info.update({
                "success": True,
                "lines_added": success.get("linesAdded"),
                "lines_removed": success.get("linesRemoved"),
                "diff_string": success.get("diffString"),
                "file_size": len(success.get("afterFullFileContent", ""))
            })
        
        return info
    
    # Read tool calls
    elif "readToolCall" in tool_call:
        read_info = tool_call["readToolCall"]
        args = read_info.get("args", {})
        result_data = read_info.get("result", {})
        
        info = {
            "tool_type": "read",
            "call_id": call_id,
            "status": subtype,
            "path": args.get("path"),
        }
        
        # Add result info if completed
        if subtype == "completed" and "success" in result_data:
            success = result_data["success"]
            info.update({
                "success": True,
                "file_size": success.get("fileSize"),
                "total_lines": success.get("totalLines"),
                "is_empty": success.get("isEmpty", False)
            })
        
        return info
    
    # Unknown tool type
    else:
        return {
            "tool_type": "unknown",
            "call_id": call_id,
            "status": subtype,
            "raw_data": tool_call
        }


def check_disk_space(workspace: str, min_mb: int = 100) -> tuple[bool, float, str]:
    """
    Pre-flight check for disk space before agent deployment.

    Critical to prevent:
    - OSError ENOSPC during agent writes
    - Partial writes corrupting JSONL
    - System-wide disk full impact

    Args:
        workspace: Workspace directory path to check
        min_mb: Minimum required free space in MB (default: 100MB)

    Returns:
        Tuple of (has_space: bool, free_mb: float, error_msg: str)

    Examples:
        >>> check_disk_space("/path/to/workspace", min_mb=100)
        (True, 5432.1, "")  # 5.4GB free

        >>> check_disk_space("/full/partition", min_mb=100)
        (False, 12.3, "Insufficient disk space: 12.3 MB free, need 100 MB")
    """
    try:
        stat = shutil.disk_usage(workspace)
        free_mb = stat.free / (1024 * 1024)

        if free_mb >= min_mb:
            return (True, free_mb, "")
        else:
            error_msg = f"Insufficient disk space: {free_mb:.1f} MB free, need {min_mb} MB"
            return (False, free_mb, error_msg)

    except Exception as e:
        return (False, 0.0, f"Failed to check disk space: {e}")


def test_write_access(workspace: str) -> tuple[bool, str]:
    """
    Test write access to workspace before agent deployment.

    Critical to detect:
    - Read-only filesystems
    - Permission issues
    - Network mount failures
    - SELinux/AppArmor restrictions

    Args:
        workspace: Workspace directory path to test

    Returns:
        Tuple of (is_writable: bool, error_msg: str)

    Examples:
        >>> test_write_access("/writable/workspace")
        (True, "")

        >>> test_write_access("/readonly/mount")
        (False, "Workspace is not writable: [Errno 30] Read-only file system")
    """
    test_file = None
    try:
        # Ensure directory exists
        os.makedirs(workspace, mode=0o755, exist_ok=True)

        # Create test file with unique name
        test_file = os.path.join(workspace, f".write_test_{uuid.uuid4().hex[:8]}")

        # Attempt write
        with open(test_file, 'w') as f:
            f.write("test")

        # Attempt read back (verify write succeeded)
        with open(test_file, 'r') as f:
            content = f.read()
            if content != "test":
                return (False, "Write verification failed: content mismatch")

        # Clean up
        os.remove(test_file)

        return (True, "")

    except (OSError, IOError, PermissionError) as e:
        error_msg = f"Workspace is not writable: {e}"
        # Attempt cleanup if test file was created
        if test_file and os.path.exists(test_file):
            try:
                os.remove(test_file)
            except:
                pass
        return (False, error_msg)

    except Exception as e:
        return (False, f"Unexpected error testing write access: {e}")


# ============================================================================
# CONVERSATION HISTORY HELPER FUNCTION
# ============================================================================

def truncate_conversation_history(messages: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Apply intelligent asymmetric truncation to conversation history.

    User messages: kept mostly intact (8KB max) - preserve valuable user context
    Assistant/Orchestrator: heavily truncated (150 chars max) - summarize verbose responses

    Args:
        messages: List of validated message dicts with role, content, timestamp

    Returns:
        Dict with truncated messages and metadata
    """
    USER_MAX_CHARS = 8000  # Keep user context intact
    ASSISTANT_MAX_CHARS = 150  # Heavily truncate verbose assistant responses

    truncated_messages = []
    truncated_count = 0

    for msg in messages:
        role = msg['role']
        content = msg['content']
        original_length = len(content)
        truncated = False

        # Apply role-specific truncation
        if role == 'user':
            # Keep user messages mostly intact (up to 8KB)
            if original_length > USER_MAX_CHARS:
                remaining = USER_MAX_CHARS - 100  # space for suffix
                content = content[:remaining] + f" ... (truncated, original: {original_length} chars)"
                truncated = True
                truncated_count += 1
        else:  # assistant or orchestrator
            # Heavily truncate verbose assistant responses (150 chars)
            if original_length > ASSISTANT_MAX_CHARS:
                content = content[:ASSISTANT_MAX_CHARS] + " ... (truncated)"
                truncated = True
                truncated_count += 1

        truncated_messages.append({
            'role': role,
            'content': content,
            'timestamp': msg['timestamp'],
            'truncated': truncated,
            'original_length': original_length
        })

    # Calculate metadata
    timestamps = [msg['timestamp'] for msg in messages]

    return {
        'messages': truncated_messages,
        'total_messages': len(truncated_messages),
        'truncated_count': truncated_count,
        'metadata': {
            'collection_time': datetime.now().isoformat(),
            'oldest_message': min(timestamps) if timestamps else None,
            'newest_message': max(timestamps) if timestamps else None
        }
    }


# ============================================================================
# TASK PARAMETER VALIDATION FUNCTION
# ============================================================================

def validate_task_parameters(
    description: str,
    priority: str = "P2",
    background_context: Optional[str] = None,
    expected_deliverables: Optional[List[str]] = None,
    success_criteria: Optional[List[str]] = None,
    constraints: Optional[List[str]] = None,
    relevant_files: Optional[List[str]] = None,
    related_documentation: Optional[List[str]] = None,
    client_cwd: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> tuple[Dict[str, Any], List[TaskValidationWarning]]:
    """
    Validate all task parameters and return cleaned data + warnings.

    Args:
        description: Task description (required)
        priority: Priority level (P0-P3)
        background_context: Multi-line context about the problem
        expected_deliverables: List of concrete outputs required
        success_criteria: List of measurable completion criteria
        conversation_history: Optional conversation context (list of message dicts)
        constraints: List of boundaries agents must respect
        relevant_files: List of file paths to examine
        related_documentation: List of docs to reference
        client_cwd: Client working directory for path resolution

    Returns:
        Tuple of (validated_data, warnings)

    Raises:
        TaskValidationError: On critical validation failures
    """
    warnings: List[TaskValidationWarning] = []
    validated: Dict[str, Any] = {}

    # Validate description
    description = description.strip()
    if len(description) < 10:
        raise TaskValidationError("description", "Must be at least 10 characters", description)
    if len(description) > 500:
        raise TaskValidationError("description", "Must be at most 500 characters", description)

    # Check for overly generic descriptions
    generic_patterns = [r'^fix bug$', r'^do task$', r'^implement feature$', r'^update code$']
    if any(re.match(pattern, description.lower()) for pattern in generic_patterns):
        warnings.append(TaskValidationWarning("description", f"Description is too generic: '{description}'. Consider being more specific."))

    validated['description'] = description

    # Validate priority
    priority = priority.upper()
    if priority not in ["P0", "P1", "P2", "P3"]:
        raise TaskValidationError("priority", "Must be P0, P1, P2, or P3", priority)
    validated['priority'] = priority

    # Validate background_context
    if background_context is not None:
        background_context = background_context.strip()
        if len(background_context) < 50:
            warnings.append(TaskValidationWarning("background_context", f"Background context is very short ({len(background_context)} chars). Consider adding more detail."))
        if len(background_context) > 5000:
            raise TaskValidationError("background_context", "Must be at most 5000 characters", f"{background_context[:100]}...")
        validated['background_context'] = background_context

    # Validate expected_deliverables
    if expected_deliverables is not None:
        deliverables = [d.strip() for d in expected_deliverables if d and d.strip()]
        deliverables = list(dict.fromkeys(deliverables))
        if len(deliverables) == 0:
            warnings.append(TaskValidationWarning("expected_deliverables", "List is empty after filtering. Consider omitting this parameter."))
        if len(deliverables) > 20:
            raise TaskValidationError("expected_deliverables", f"Maximum 20 items allowed, got {len(deliverables)}", deliverables)
        for i, item in enumerate(deliverables):
            if len(item) < 10:
                warnings.append(TaskValidationWarning(f"expected_deliverables[{i}]", f"Deliverable is very short: '{item}'. Consider being more specific."))
            if len(item) > 200:
                raise TaskValidationError(f"expected_deliverables[{i}]", "Each item must be at most 200 characters", item)
        validated['expected_deliverables'] = {'items': deliverables, 'validation_added': datetime.now().isoformat()}

    # Validate success_criteria
    if success_criteria is not None:
        criteria = [c.strip() for c in success_criteria if c and c.strip()]
        criteria = list(dict.fromkeys(criteria))
        if len(criteria) == 0:
            warnings.append(TaskValidationWarning("success_criteria", "List is empty after filtering. Consider omitting this parameter."))
        if len(criteria) > 15:
            raise TaskValidationError("success_criteria", f"Maximum 15 items allowed, got {len(criteria)}", criteria)
        measurable_keywords = ['pass', 'complete', 'under', 'above', 'below', 'equal', 'verify', 'test', 'validate', 'all', 'no', 'zero', 'every', 'none', 'within', 'less than', 'greater than', 'at least', 'at most']
        for i, item in enumerate(criteria):
            if len(item) < 10:
                warnings.append(TaskValidationWarning(f"success_criteria[{i}]", f"Criterion is very short: '{item}'. Consider being more specific."))
            if len(item) > 200:
                raise TaskValidationError(f"success_criteria[{i}]", "Each item must be at most 200 characters", item)
            if not any(keyword in item.lower() for keyword in measurable_keywords):
                warnings.append(TaskValidationWarning(f"success_criteria[{i}]", f"Criterion may not be measurable: '{item}'. Consider adding quantifiable metrics."))
        validated['success_criteria'] = {'criteria': criteria, 'all_required': True}

    # Validate constraints
    if constraints is not None:
        constraint_list = [c.strip() for c in constraints if c and c.strip()]
        constraint_list = list(dict.fromkeys(constraint_list))
        if len(constraint_list) == 0:
            warnings.append(TaskValidationWarning("constraints", "List is empty after filtering. Consider omitting this parameter."))
        if len(constraint_list) > 15:
            raise TaskValidationError("constraints", f"Maximum 15 items allowed, got {len(constraint_list)}", constraint_list)
        constraint_keywords = ['do not', 'must not', 'never', 'cannot', 'should not', 'must use', 'required to', 'only use', 'must maintain']
        for i, item in enumerate(constraint_list):
            if len(item) < 10:
                warnings.append(TaskValidationWarning(f"constraints[{i}]", f"Constraint is very short: '{item}'. Consider being more specific."))
            if len(item) > 200:
                raise TaskValidationError(f"constraints[{i}]", "Each item must be at most 200 characters", item)
            if not any(keyword in item.lower() for keyword in constraint_keywords):
                warnings.append(TaskValidationWarning(f"constraints[{i}]", f"Constraint should start with imperative: '{item}'"))
        validated['constraints'] = {'rules': constraint_list, 'enforcement_level': 'strict'}

    # Validate relevant_files
    if relevant_files is not None:
        file_list = [f.strip() for f in relevant_files if f and f.strip()]
        file_list = list(dict.fromkeys(file_list))
        if len(file_list) == 0:
            warnings.append(TaskValidationWarning("relevant_files", "List is empty after filtering. Consider omitting this parameter."))
        if len(file_list) > 50:
            raise TaskValidationError("relevant_files", f"Maximum 50 files allowed, got {len(file_list)}", file_list)
        validated_files = []
        for filepath in file_list:
            original_path = filepath
            if not os.path.isabs(filepath):
                if client_cwd:
                    filepath = os.path.join(client_cwd, filepath)
                else:
                    filepath = os.path.abspath(filepath)
            try:
                filepath = os.path.realpath(filepath)
            except Exception as e:
                warnings.append(TaskValidationWarning("relevant_files", f"Could not resolve path '{original_path}': {e}"))
                continue
            if not os.path.exists(filepath):
                warnings.append(TaskValidationWarning("relevant_files", f"File not found: '{filepath}' - agents will skip if unavailable"))
            elif not os.path.isfile(filepath):
                warnings.append(TaskValidationWarning("relevant_files", f"Path is not a file: '{filepath}' - may be a directory"))
            validated_files.append(filepath)
        validated['relevant_files'] = validated_files

    # Validate related_documentation
    if related_documentation is not None:
        doc_list = [d.strip() for d in related_documentation if d and d.strip()]
        doc_list = list(dict.fromkeys(doc_list))
        if len(doc_list) == 0:
            warnings.append(TaskValidationWarning("related_documentation", "List is empty after filtering. Consider omitting this parameter."))
        if len(doc_list) > 20:
            raise TaskValidationError("related_documentation", f"Maximum 20 items allowed, got {len(doc_list)}", doc_list)
        validated_docs = []
        for item in doc_list:
            if item.startswith('http://') or item.startswith('https://'):
                if ' ' in item:
                    warnings.append(TaskValidationWarning("related_documentation", f"URL contains spaces (may be invalid): '{item}'"))
                if item.endswith('.'):
                    warnings.append(TaskValidationWarning("related_documentation", f"URL ends with period (may be typo): '{item}'"))
                validated_docs.append(item)
            else:
                original_path = item
                if not os.path.isabs(item):
                    if client_cwd:
                        item = os.path.join(client_cwd, item)
                    else:
                        item = os.path.abspath(item)
                if not os.path.exists(item):
                    warnings.append(TaskValidationWarning("related_documentation", f"Documentation file not found: '{original_path}' - agents will skip if unavailable"))
                validated_docs.append(item)
        validated['related_documentation'] = validated_docs

    # Validate conversation_history
    if conversation_history is not None:
        if not isinstance(conversation_history, list):
            raise TaskValidationError(
                "conversation_history",
                "Must be a list of message dictionaries",
                type(conversation_history).__name__
            )

        # Limit to 50 most recent messages
        if len(conversation_history) > 50:
            warnings.append(TaskValidationWarning(
                "conversation_history",
                f"Too many messages ({len(conversation_history)} > 50). Keeping only the last 50 messages."
            ))
            conversation_history = conversation_history[-50:]

        # Validate each message
        validated_messages = []
        for i, msg in enumerate(conversation_history):
            if not isinstance(msg, dict):
                raise TaskValidationError(
                    f"conversation_history[{i}]",
                    "Each message must be a dictionary",
                    type(msg).__name__
                )

            # Check required fields
            missing_fields = []
            if 'role' not in msg:
                missing_fields.append('role')
            if 'content' not in msg:
                missing_fields.append('content')

            if missing_fields:
                raise TaskValidationError(
                    f"conversation_history[{i}]",
                    f"Missing required fields: {', '.join(missing_fields)}",
                    list(msg.keys())
                )

            # Validate role
            role = msg['role'].strip().lower()
            if role not in ['user', 'assistant', 'orchestrator']:
                raise TaskValidationError(
                    f"conversation_history[{i}].role",
                    f"Role must be one of ['user', 'assistant', 'orchestrator'], got '{role}'",
                    role
                )

            # Get and clean content
            content = str(msg['content']).strip()

            # Skip empty messages
            if not content:
                warnings.append(TaskValidationWarning(
                    f"conversation_history[{i}].content",
                    "Empty message content - message will be skipped"
                ))
                continue

            # Validate/fix timestamp
            timestamp = msg.get('timestamp', '')
            if not timestamp:
                timestamp = datetime.now().isoformat()
                warnings.append(TaskValidationWarning(
                    f"conversation_history[{i}].timestamp",
                    f"Missing timestamp - added current time: {timestamp}"
                ))
            else:
                try:
                    datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    new_timestamp = datetime.now().isoformat()
                    timestamp = new_timestamp
                    warnings.append(TaskValidationWarning(
                        f"conversation_history[{i}].timestamp",
                        f"Invalid timestamp format - replaced with current time"
                    ))

            validated_messages.append({
                'role': role,
                'content': content,
                'timestamp': timestamp
            })

        # Check if all messages were filtered out
        if len(validated_messages) == 0:
            warnings.append(TaskValidationWarning(
                "conversation_history",
                "All messages were filtered out due to validation issues. History will be omitted."
            ))
            validated['conversation_history'] = None
        else:
            validated['conversation_history'] = validated_messages

    return validated, warnings


@mcp.tool
def create_real_task(
    description: str,
    priority: str = "P2",
    client_cwd: str = None,
    background_context: Optional[str] = None,
    expected_deliverables: Optional[List[str]] = None,
    success_criteria: Optional[List[str]] = None,
    constraints: Optional[List[str]] = None,
    relevant_files: Optional[List[str]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """
    Create a real orchestration task with proper workspace.

    Args:
        description: Description of the task
        priority: Task priority
        client_cwd: Optional client working directory (defaults to server's location if not provided)
        background_context: Optional background information and context for the task
        expected_deliverables: Optional list of expected deliverables
        success_criteria: Optional list of success criteria
        constraints: Optional list of constraints
        relevant_files: Optional list of relevant file paths
        conversation_history: Optional conversation context (list of message dicts with role, content, timestamp)

    Returns:
        Task creation result with optional validation warnings and enhancement flags
    """
    ensure_workspace()

    # Use client's working directory if provided, otherwise use server's WORKSPACE_BASE
    if client_cwd:
        # Resolve template variables (e.g., ${workspaceFolder} -> actual path)
        client_cwd = resolve_workspace_variables(client_cwd)
        workspace_base = os.path.join(client_cwd, '.agent-workspace')
        logger.info(f"Using client workspace: {workspace_base}")
    else:
        workspace_base = resolve_workspace_variables(WORKSPACE_BASE)
        logger.info(f"Using server workspace: {workspace_base}")
    
    # Ensure client workspace directory exists
    os.makedirs(workspace_base, exist_ok=True)

    # Ensure global registry exists in this workspace
    ensure_global_registry(workspace_base)

    # Validate and process enhancement parameters
    validation_warnings = []
    has_enhanced_context = False
    task_context = {}

    # Validate background_context
    if background_context is not None:
        if not isinstance(background_context, str):
            validation_warnings.append("background_context must be a string, ignoring invalid value")
        elif len(background_context.strip()) == 0:
            validation_warnings.append("background_context is empty, ignoring")
        else:
            task_context['background_context'] = background_context.strip()
            has_enhanced_context = True

    # Validate expected_deliverables
    if expected_deliverables is not None:
        if not isinstance(expected_deliverables, list):
            validation_warnings.append("expected_deliverables must be a list, ignoring invalid value")
        elif len(expected_deliverables) == 0:
            validation_warnings.append("expected_deliverables is empty, ignoring")
        elif not all(isinstance(d, str) and len(d.strip()) > 0 for d in expected_deliverables):
            validation_warnings.append("expected_deliverables contains invalid items (must be non-empty strings), filtering")
            valid_deliverables = [d.strip() for d in expected_deliverables if isinstance(d, str) and len(d.strip()) > 0]
            if valid_deliverables:
                task_context['expected_deliverables'] = valid_deliverables
                has_enhanced_context = True
        else:
            task_context['expected_deliverables'] = [d.strip() for d in expected_deliverables]
            has_enhanced_context = True

    # Validate success_criteria
    if success_criteria is not None:
        if not isinstance(success_criteria, list):
            validation_warnings.append("success_criteria must be a list, ignoring invalid value")
        elif len(success_criteria) == 0:
            validation_warnings.append("success_criteria is empty, ignoring")
        elif not all(isinstance(c, str) and len(c.strip()) > 0 for c in success_criteria):
            validation_warnings.append("success_criteria contains invalid items (must be non-empty strings), filtering")
            valid_criteria = [c.strip() for c in success_criteria if isinstance(c, str) and len(c.strip()) > 0]
            if valid_criteria:
                task_context['success_criteria'] = valid_criteria
                has_enhanced_context = True
        else:
            task_context['success_criteria'] = [c.strip() for c in success_criteria]
            has_enhanced_context = True

    # Validate constraints
    if constraints is not None:
        if not isinstance(constraints, list):
            validation_warnings.append("constraints must be a list, ignoring invalid value")
        elif len(constraints) == 0:
            validation_warnings.append("constraints is empty, ignoring")
        elif not all(isinstance(c, str) and len(c.strip()) > 0 for c in constraints):
            validation_warnings.append("constraints contains invalid items (must be non-empty strings), filtering")
            valid_constraints = [c.strip() for c in constraints if isinstance(c, str) and len(c.strip()) > 0]
            if valid_constraints:
                task_context['constraints'] = valid_constraints
                has_enhanced_context = True
        else:
            task_context['constraints'] = [c.strip() for c in constraints]
            has_enhanced_context = True

    # Validate relevant_files
    if relevant_files is not None:
        if not isinstance(relevant_files, list):
            validation_warnings.append("relevant_files must be a list, ignoring invalid value")
        elif len(relevant_files) == 0:
            validation_warnings.append("relevant_files is empty, ignoring")
        elif not all(isinstance(f, str) and len(f.strip()) > 0 for f in relevant_files):
            validation_warnings.append("relevant_files contains invalid items (must be non-empty strings), filtering")
            valid_files = [f.strip() for f in relevant_files if isinstance(f, str) and len(f.strip()) > 0]
            if valid_files:
                task_context['relevant_files'] = valid_files
                has_enhanced_context = True
        else:
            task_context['relevant_files'] = [f.strip() for f in relevant_files]
            has_enhanced_context = True

    # Validate and process conversation_history
    if conversation_history is not None:
        if not isinstance(conversation_history, list):
            validation_warnings.append("conversation_history must be a list, ignoring invalid value")
        elif len(conversation_history) == 0:
            validation_warnings.append("conversation_history is empty, ignoring")
        else:
            # Validate each message structure
            validated_messages = []
            for i, msg in enumerate(conversation_history):
                if not isinstance(msg, dict):
                    validation_warnings.append(f"conversation_history[{i}] must be a dict, skipping")
                    continue

                if 'role' not in msg or 'content' not in msg:
                    validation_warnings.append(f"conversation_history[{i}] missing required fields (role, content), skipping")
                    continue

                role = str(msg['role']).strip().lower()
                if role not in ['user', 'assistant', 'orchestrator']:
                    validation_warnings.append(f"conversation_history[{i}] has invalid role '{role}', skipping")
                    continue

                content = str(msg['content']).strip()
                if not content:
                    validation_warnings.append(f"conversation_history[{i}] has empty content, skipping")
                    continue

                # Auto-generate timestamp if missing
                timestamp = msg.get('timestamp', datetime.now().isoformat())

                validated_messages.append({
                    'role': role,
                    'content': content,
                    'timestamp': timestamp
                })

            if validated_messages:
                # Apply intelligent truncation
                truncated_history = truncate_conversation_history(validated_messages)
                task_context['conversation_history'] = truncated_history
                has_enhanced_context = True
            else:
                validation_warnings.append("All conversation_history messages were invalid, ignoring")

    # Generate task ID
    task_id = f"TASK-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    workspace = f"{workspace_base}/{task_id}"
    
    # Create task workspace
    os.makedirs(f"{workspace}/progress", exist_ok=True)
    os.makedirs(f"{workspace}/logs", exist_ok=True)
    os.makedirs(f"{workspace}/findings", exist_ok=True)
    os.makedirs(f"{workspace}/output", exist_ok=True)  # For agent outputs
    
    # Create task registry
    registry = {
        "task_id": task_id,
        "task_description": description,
        "created_at": datetime.now().isoformat(),
        "workspace": workspace,
        "workspace_base": workspace_base,  # Store the workspace base for global registry updates
        "client_cwd": client_cwd,  # Store client's working directory for context detection
        "status": "INITIALIZED",
        "priority": priority,
        "agents": [],
        "agent_hierarchy": {"orchestrator": []},
        "max_agents": DEFAULT_MAX_AGENTS,
        "max_depth": DEFAULT_MAX_DEPTH,
        "max_concurrent": DEFAULT_MAX_CONCURRENT,
        "total_spawned": 0,
        "active_count": 0,
        "completed_count": 0,
        "orchestration_guidance": {
            "min_specialization_depth": 2,  # Encourage at least 2 layers (practical minimum)
            "recommended_child_agents_per_parent": 3,  # Each parent should spawn ~3 children (manageable)
            "specialization_domains": [],  # Dynamic list of identified domains
            "complexity_score": calculate_task_complexity(description)
        },
        "spiral_checks": {
            "enabled": True,
            "last_check": datetime.now().isoformat(),
            "violations": 0
        }
    }

    # Add task_context to registry only if enhancement fields provided
    if has_enhanced_context:
        registry['task_context'] = task_context

    with open(f"{workspace}/AGENT_REGISTRY.json", 'w') as f:
        json.dump(registry, f, indent=2)
    
    # Update global registry (in the same workspace_base where task was created)
    global_reg_path = get_global_registry_path(workspace_base)
    with open(global_reg_path, 'r') as f:
        global_reg = json.load(f)
    
    global_reg['total_tasks'] += 1
    global_reg['active_tasks'] += 1
    global_reg['tasks'][task_id] = {
        'description': description,
        'created_at': datetime.now().isoformat(),
        'status': 'INITIALIZED',
        'has_enhanced_context': has_enhanced_context
    }

    # Add counts for quick reference if enhanced context present
    if has_enhanced_context:
        global_reg['tasks'][task_id]['deliverables_count'] = len(task_context.get('expected_deliverables', []))
        global_reg['tasks'][task_id]['success_criteria_count'] = len(task_context.get('success_criteria', []))
    
    # Store workspace location for cross-project discovery
    global_reg['tasks'][task_id]['workspace'] = workspace
    global_reg['tasks'][task_id]['workspace_base'] = workspace_base
    
    with open(global_reg_path, 'w') as f:
        json.dump(global_reg, f, indent=2)
    
    # If task was created in a non-default workspace (client_cwd), 
    # ALSO register it in the default WORKSPACE_BASE global registry for cross-project discovery
    if client_cwd and workspace_base != resolve_workspace_variables(WORKSPACE_BASE):
        try:
            default_workspace_base = resolve_workspace_variables(WORKSPACE_BASE)
            ensure_global_registry(default_workspace_base)
            default_global_reg_path = get_global_registry_path(default_workspace_base)
            
            with open(default_global_reg_path, 'r') as f:
                default_global_reg = json.load(f)
            
            # Add task reference with workspace location
            if task_id not in default_global_reg.get('tasks', {}):
                default_global_reg.setdefault('tasks', {})[task_id] = {
                    'description': description,
                    'created_at': datetime.now().isoformat(),
                    'status': 'INITIALIZED',
                    'has_enhanced_context': has_enhanced_context,
                    'workspace': workspace,  # Store actual workspace location
                    'workspace_base': workspace_base,
                    'client_cwd': client_cwd,  # Store client_cwd for reference
                    'cross_project_reference': True  # Flag this as a reference from another workspace
                }
                
                if has_enhanced_context:
                    default_global_reg['tasks'][task_id]['deliverables_count'] = len(task_context.get('expected_deliverables', []))
                    default_global_reg['tasks'][task_id]['success_criteria_count'] = len(task_context.get('success_criteria', []))
                
                with open(default_global_reg_path, 'w') as f:
                    json.dump(default_global_reg, f, indent=2)
                
                logger.info(f"Registered task {task_id} in default global registry for cross-project discovery")
        except Exception as e:
            logger.warning(f"Failed to register task in default global registry: {e}")
            # Non-fatal - task is still properly registered in its own workspace
    
    # Build return value with enhanced context info
    result = {
        "success": True,
        "task_id": task_id,
        "description": description,
        "priority": priority,
        "workspace": workspace,
        "status": "INITIALIZED",
        "has_enhanced_context": has_enhanced_context
    }

    # Include validation warnings if any
    if validation_warnings:
        result['validation_warnings'] = validation_warnings

    # Include task_context fields in response if provided
    if has_enhanced_context:
        for key, value in task_context.items():
            result[key] = value

    return result

def find_existing_agent(task_id: str, agent_type: str, registry: dict, status_filter: list = None) -> dict:
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

@mcp.tool
def deploy_headless_agent(
    task_id: str,
    agent_type: str, 
    prompt: str,
    parent: str = "orchestrator"
) -> Dict[str, Any]:
    """
    Deploy a headless agent using configured backend (tmux+claude or cursor-agent).
    
    Automatically routes to appropriate deployment method based on AGENT_BACKEND config:
    - 'claude': Uses tmux + claude CLI (original method)
    - 'cursor': Uses cursor-agent with native process management
    
    Args:
        task_id: Task ID to deploy agent for
        agent_type: Type of agent (investigator, fixer, etc.)
        prompt: Instructions for the agent
        parent: Parent agent ID
    
    Returns:
        Agent deployment result
    """
    # Route to appropriate backend
    if AGENT_BACKEND == 'cursor':
        logger.info(f"Using cursor-agent backend for deployment")
        return deploy_cursor_agent(task_id, agent_type, prompt, parent)
    else:
        logger.info(f"Using claude+tmux backend for deployment")
        return deploy_claude_tmux_agent(task_id, agent_type, prompt, parent)


def deploy_claude_tmux_agent(
    task_id: str,
    agent_type: str, 
    prompt: str,
    parent: str = "orchestrator"
) -> Dict[str, Any]:
    """
    Deploy a headless Claude agent using tmux for background execution.
    
    Original deployment method using tmux sessions and claude CLI.
    
    Args:
        task_id: Task ID to deploy agent for
        agent_type: Type of agent (investigator, fixer, etc.)
        prompt: Instructions for the agent
        parent: Parent agent ID
    
    Returns:
        Agent deployment result
    """
    if not check_tmux_available():
        logger.error("tmux not available for agent deployment")
        return {
            "success": False,
            "error": "tmux is not available - required for background execution"
        }
    
    # Find the task workspace (may be in client or server location)
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
    
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    
    # Load registry
    with open(registry_path, 'r') as f:
        registry = json.load(f)
    
    # Anti-spiral checks
    if registry['active_count'] >= registry['max_concurrent']:
        return {
            "success": False,
            "error": f"Too many active agents ({registry['active_count']}/{registry['max_concurrent']})"
        }
    
    if registry['total_spawned'] >= registry['max_agents']:
        return {
            "success": False,
            "error": f"Max agents reached ({registry['total_spawned']}/{registry['max_agents']})"
        }

    # Check for duplicate agents (deduplication)
    existing_agent = find_existing_agent(task_id, agent_type, registry)
    if existing_agent:
        logger.warning(f"Agent type '{agent_type}' already exists for task {task_id}: {existing_agent['id']}")
        return {
            "success": False,
            "error": f"Agent of type '{agent_type}' already running for this task",
            "existing_agent_id": existing_agent['id'],
            "existing_agent_status": existing_agent['status'],
            "note": "Use the existing agent or wait for it to complete before spawning a new one"
        }

    # Load global registry for unique ID verification
    workspace_base = get_workspace_base_from_task_workspace(workspace)
    global_reg_path = get_global_registry_path(workspace_base)
    with open(global_reg_path, 'r') as f:
        global_registry = json.load(f)

    # Generate unique agent ID with collision detection
    try:
        agent_id = generate_unique_agent_id(agent_type, registry, global_registry)
    except RuntimeError as e:
        logger.error(f"Failed to generate unique agent ID: {e}")
        return {
            "success": False,
            "error": str(e)
        }

    session_name = f"agent_{agent_id}"
    
    # Calculate agent depth based on parent
    depth = 1 if parent == "orchestrator" else 2
    if parent != "orchestrator":
        # Try to find parent depth and increment
        with open(registry_path, 'r') as f:
            registry = json.load(f)
        for agent in registry['agents']:
            if agent['id'] == parent:
                depth = agent.get('depth', 1) + 1
                break
    
    # Load registry to get task description for orchestration guidance
    with open(registry_path, 'r') as f:
        task_registry = json.load(f)

    task_description = task_registry.get('task_description', '')
    max_depth = task_registry.get('max_depth', 5)
    orchestration_prompt = create_orchestration_guidance_prompt(agent_type, task_description, depth, max_depth)

    # Build task enrichment context from registry
    try:
        enrichment_prompt = format_task_enrichment_prompt(task_registry)
    except Exception as e:
        logger.error(f"Error in format_task_enrichment_prompt: {e}")
        logger.error(f"task_registry keys: {task_registry.keys()}")
        if 'task_context' in task_registry:
            logger.error(f"task_context keys: {task_registry['task_context'].keys()}")
            for key, value in task_registry['task_context'].items():
                logger.error(f"  {key}: type={type(value)}, value={str(value)[:100]}")
        raise

    # Detect project context from CLIENT's project directory (not MCP server's cwd)
    client_project_dir = task_registry.get('client_cwd')
    if not client_project_dir:
        # Fallback: extract from workspace path if client_cwd not stored
        # workspace = "/path/to/client/project/.agent-workspace/TASK-xxx"
        # client_project_dir = "/path/to/client/project"
        workspace_parent = os.path.dirname(workspace)
        if workspace_parent.endswith('.agent-workspace'):
            client_project_dir = os.path.dirname(workspace_parent)
        else:
            # Workspace is in server's WORKSPACE_BASE, use that as fallback
            client_project_dir = os.getcwd()

    project_context = detect_project_context(client_project_dir)
    context_prompt = format_project_context_prompt(project_context)

    # Get type-specific requirements for this agent type
    type_requirements = get_type_specific_requirements(agent_type)

    # Create comprehensive agent prompt with MCP self-reporting capabilities
    agent_prompt = f"""You are a headless Claude agent in an orchestrator system.

🤖 AGENT IDENTITY:
- Agent ID: {agent_id}
- Agent Type: {agent_type}
- Task ID: {task_id}
- Parent Agent: {parent}
- Depth Level: {depth}
- Workspace: {workspace}

📝 YOUR MISSION:
{prompt}
{enrichment_prompt}
{context_prompt}

{type_requirements}

{orchestration_prompt}

🔗 MCP SELF-REPORTING WITH COORDINATION - You MUST use these MCP functions to report progress:

1. PROGRESS UPDATES (every few minutes):
```
mcp__claude-orchestrator__update_agent_progress
Parameters: 
- task_id: "{task_id}"
- agent_id: "{agent_id}"  
- status: "working" | "blocked" | "completed" | "error"
- message: "Description of current work"
- progress: 0-100 (percentage)

RETURNS: Your update confirmation + comprehensive status of ALL agents for coordination!
- coordination_info.agents: Status of all other agents
- coordination_info.coordination_data.recent_progress: Latest progress from all agents
- coordination_info.coordination_data.recent_findings: Latest discoveries from all agents
```

2. REPORT FINDINGS (whenever you discover something important):
```
mcp__claude-orchestrator__report_agent_finding
Parameters:
- task_id: "{task_id}"
- agent_id: "{agent_id}"
- finding_type: "issue" | "solution" | "insight" | "recommendation"
- severity: "low" | "medium" | "high" | "critical"  
- message: "What you discovered"
- data: {{"any": "additional info"}}

RETURNS: Your finding confirmation + comprehensive status of ALL agents for coordination!
- coordination_info.agents: Status of all other agents
- coordination_info.coordination_data.recent_progress: Latest progress from all agents
- coordination_info.coordination_data.recent_findings: Latest discoveries from all agents
```

💡 COORDINATION ADVANTAGE: Every time you update progress or report a finding, you'll receive:
- Complete status of all other agents working on this task
- Their latest progress updates and discoveries
- Opportunity to coordinate and avoid duplicate work
- Insights to build upon others' findings

3. SPAWN CHILD AGENTS (if you need specialized help):
```
mcp__claude-orchestrator__spawn_child_agent
Parameters:
- task_id: "{task_id}"
- parent_agent_id: "{agent_id}"
- child_agent_type: "investigator" | "builder" | "fixer" | etc
- child_prompt: "Specific task for the child agent"
```

🚨 CRITICAL PROTOCOL:
1. START by calling update_agent_progress with status="working", progress=0
2. REGULARLY update progress every few minutes
3. REPORT key findings as you discover them
4. SPAWN child agents if you need specialized help
5. END by calling update_agent_progress with status="completed", progress=100

⚠️ REPORTING REQUIREMENTS:
- Update progress EVERY 3-5 minutes minimum
- Progress must be REALISTIC and match actual work done
- Completion requires EVIDENCE: files modified, tests passed, findings documented
- If you don't report for 5+ minutes, you'll be flagged as stalled
- BEFORE claiming done: perform self-review and list what could be improved

You are working independently but can coordinate through the MCP orchestrator system.

BEGIN YOUR WORK NOW!
"""

    # Resource tracking variables for cleanup on failure
    prompt_file_created = None
    tmux_session_created = None
    registry_updated = False
    global_registry_updated = False

    try:
        # Pre-flight checks before deployment
        import shutil

        # Check disk space (minimum 100MB required)
        try:
            disk_stat = shutil.disk_usage(workspace)
            free_mb = disk_stat.free / (1024 * 1024)
            if free_mb < 100:
                logger.error(f"Insufficient disk space: {free_mb:.1f}MB available (need 100MB)")
                return {
                    "success": False,
                    "error": f"Insufficient disk space: {free_mb:.1f}MB available, need at least 100MB"
                }
        except Exception as e:
            logger.warning(f"Could not check disk space: {e}")

        # Create logs directory and test write access
        logs_dir = f"{workspace}/logs"
        try:
            os.makedirs(logs_dir, exist_ok=True)
            # Test write access
            test_file = f"{logs_dir}/.write_test_{uuid.uuid4().hex[:8]}"
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
        except Exception as e:
            logger.error(f"Workspace logs directory not writable: {e}")
            return {
                "success": False,
                "error": f"Workspace logs directory not writable: {e}. Check permissions or mount status."
            }

        # Store agent prompt in file for tmux execution with absolute path
        prompt_file = os.path.abspath(f"{workspace}/agent_prompt_{agent_id}.txt")
        with open(prompt_file, 'w') as f:
            f.write(agent_prompt)
        prompt_file_created = prompt_file  # Track for cleanup on failure

        # Run Claude in the calling project's directory, not the orchestrator workspace
        calling_project_dir = os.getcwd()
        claude_executable = os.getenv('CLAUDE_EXECUTABLE', 'npx -y @anthropic-ai/claude-code')
        claude_flags = os.getenv('CLAUDE_FLAGS', '--print --output-format stream-json --verbose --dangerously-skip-permissions --model sonnet')

        # JSONL log file path - unique per agent_id
        log_file = f"{logs_dir}/{agent_id}_stream.jsonl"

        # Escape the prompt for shell and pass as argument (not stdin redirection)
        escaped_prompt = agent_prompt.replace("'", "'\"'\"'")
        # Add tee pipe to capture Claude stream-json output to persistent log
        claude_command = f"cd '{calling_project_dir}' && {claude_executable} {claude_flags} '{escaped_prompt}' | tee '{log_file}'"
        
        # Create the session in the calling project directory
        session_result = create_tmux_session(
            session_name=session_name,
            command=claude_command,
            working_dir=calling_project_dir
        )

        if not session_result["success"]:
            return {
                "success": False,
                "error": f"Failed to create agent session: {session_result['error']}"
            }

        tmux_session_created = session_name  # Track for cleanup on failure

        # Give Claude a moment to start
        time.sleep(2)

        # Check if session is still running
        if not check_tmux_session_exists(session_name):
            # Clean up orphaned prompt file since tmux session failed
            if prompt_file_created and os.path.exists(prompt_file_created):
                try:
                    os.remove(prompt_file_created)
                    logger.info(f"Cleaned up orphaned prompt file: {prompt_file_created}")
                except Exception as cleanup_err:
                    logger.error(f"Failed to remove orphaned prompt file: {cleanup_err}")

            return {
                "success": False,
                "error": "Agent session terminated immediately after creation"
            }
        
        # Update registry with new agent
        agent_data = {
            "id": agent_id,
            "type": agent_type,
            "tmux_session": session_name,
            "parent": parent,
            "depth": 1 if parent == "orchestrator" else 2,
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "progress": 0,
            "last_update": datetime.now().isoformat(),
            "prompt": prompt[:200] + "..." if len(prompt) > 200 else prompt,
            "tracked_files": {
                "prompt_file": prompt_file,
                "log_file": log_file,
                "progress_file": f"{workspace}/progress/{agent_id}_progress.jsonl",
                "findings_file": f"{workspace}/findings/{agent_id}_findings.jsonl",
                "deploy_log": f"{workspace}/logs/deploy_{agent_id}.json"
            }
        }
        
        registry['agents'].append(agent_data)
        registry['total_spawned'] += 1
        registry['active_count'] += 1
        
        # Update hierarchy
        if parent not in registry['agent_hierarchy']:
            registry['agent_hierarchy'][parent] = []
        registry['agent_hierarchy'][parent].append(agent_id)
        
        # Save updated registry
        with open(registry_path, 'w') as f:
            json.dump(registry, f, indent=2)
        registry_updated = True  # Track for cleanup awareness

        # Update global registry (in the same workspace_base as the task)
        workspace_base = get_workspace_base_from_task_workspace(workspace)
        global_reg_path = get_global_registry_path(workspace_base)
        with open(global_reg_path, 'r') as f:
            global_reg = json.load(f)
        
        global_reg['total_agents_spawned'] += 1
        global_reg['active_agents'] += 1
        global_reg['agents'][agent_id] = {
            'task_id': task_id,
            'type': agent_type,
            'parent': parent,
            'started_at': datetime.now().isoformat(),
            'tmux_session': session_name
        }
        
        with open(global_reg_path, 'w') as f:
            json.dump(global_reg, f, indent=2)
        global_registry_updated = True  # Track for cleanup awareness

        # Log successful deployment
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": "agent_deployed",
            "agent_id": agent_id,
            "tmux_session": session_name,
            "command": claude_command[:100] + "...",
            "success": True,
            "session_creation": session_result
        }
        
        with open(f"{workspace}/logs/deploy_{agent_id}.json", 'w') as f:
            json.dump(log_entry, f, indent=2)
        
        return {
            "success": True,
            "agent_id": agent_id,
            "tmux_session": session_name,
            "type": agent_type,
            "parent": parent,
            "task_id": task_id,
            "status": "deployed",
            "workspace": workspace,
            "deployment_method": "tmux session"
        }
        
    except Exception as e:
        logger.error(f"Agent deployment failed: {e}")
        logger.error(f"Cleaning up orphaned resources...")

        # Clean up tmux session if it was created
        if tmux_session_created:
            try:
                subprocess.run(['tmux', 'kill-session', '-t', tmux_session_created],
                             capture_output=True, timeout=5)
                logger.info(f"Killed orphaned tmux session: {tmux_session_created}")
            except Exception as cleanup_err:
                logger.error(f"Failed to kill tmux session: {cleanup_err}")

        # Remove orphaned prompt file
        if prompt_file_created and os.path.exists(prompt_file_created):
            try:
                os.remove(prompt_file_created)
                logger.info(f"Removed orphaned prompt file: {prompt_file_created}")
            except Exception as cleanup_err:
                logger.error(f"Failed to remove prompt file: {cleanup_err}")

        # Rollback registry changes (THIS WILL BE IMPROVED BY file_locking_implementer)
        # For now, log that registry may be corrupted
        if registry_updated or global_registry_updated:
            logger.error(f"Registry was partially updated before failure - may need manual cleanup")

        return {
            "success": False,
            "error": f"Failed to deploy agent: {str(e)}",
            "cleanup_performed": True,
            "resources_cleaned": {
                "tmux_session": tmux_session_created,
                "prompt_file": prompt_file_created
            }
        }


def deploy_cursor_agent(
    task_id: str,
    agent_type: str,
    prompt: str,
    parent: str = "orchestrator"
) -> Dict[str, Any]:
    """
    Deploy a headless agent using cursor-agent for background execution.
    
    Alternative to tmux+claude deployment, using cursor-agent with:
    - Native process management (PID tracking instead of tmux)
    - Stream-JSON output format (structured NDJSON logs)
    - Built-in session management
    - Better tool call tracking
    
    Args:
        task_id: Task ID to deploy agent for
        agent_type: Type of agent (investigator, fixer, etc.)
        prompt: Instructions for the agent
        parent: Parent agent ID
    
    Returns:
        Agent deployment result with cursor-specific metadata
    """
    if not check_cursor_agent_available():
        logger.error("cursor-agent not available for agent deployment")
        return {
            "success": False,
            "error": "cursor-agent is not available - required for cursor backend. Install: curl https://cursor.com/install -fsSL | bash"
        }
    
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
    
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    
    # Load registry
    with open(registry_path, 'r') as f:
        registry = json.load(f)
    
    # Anti-spiral checks
    if registry['active_count'] >= registry['max_concurrent']:
        return {
            "success": False,
            "error": f"Too many active agents ({registry['active_count']}/{registry['max_concurrent']})"
        }
    
    if registry['total_spawned'] >= registry['max_agents']:
        return {
            "success": False,
            "error": f"Max agents reached ({registry['total_spawned']}/{registry['max_agents']})"
        }
    
    # Check for duplicate agents
    existing_agent = find_existing_agent(task_id, agent_type, registry)
    if existing_agent:
        logger.warning(f"Agent type '{agent_type}' already exists for task {task_id}: {existing_agent['id']}")
        return {
            "success": False,
            "error": f"Agent of type '{agent_type}' already running for this task",
            "existing_agent_id": existing_agent['id'],
            "existing_agent_status": existing_agent['status']
        }
    
    # Load global registry for unique ID verification
    workspace_base = get_workspace_base_from_task_workspace(workspace)
    global_reg_path = get_global_registry_path(workspace_base)
    with open(global_reg_path, 'r') as f:
        global_registry = json.load(f)
    
    # Generate unique agent ID
    try:
        agent_id = generate_unique_agent_id(agent_type, registry, global_registry)
    except RuntimeError as e:
        logger.error(f"Failed to generate unique agent ID: {e}")
        return {
            "success": False,
            "error": str(e)
        }
    
    # Calculate agent depth
    depth = 1 if parent == "orchestrator" else 2
    if parent != "orchestrator":
        with open(registry_path, 'r') as f:
            registry = json.load(f)
        for agent in registry['agents']:
            if agent['id'] == parent:
                depth = agent.get('depth', 1) + 1
                break
    
    # Load registry for task context
    with open(registry_path, 'r') as f:
        task_registry = json.load(f)
    
    task_description = task_registry.get('task_description', '')
    max_depth = task_registry.get('max_depth', 5)
    orchestration_prompt = create_orchestration_guidance_prompt(agent_type, task_description, depth, max_depth)
    
    # Build enrichment context
    try:
        enrichment_prompt = format_task_enrichment_prompt(task_registry)
    except Exception as e:
        logger.error(f"Error in format_task_enrichment_prompt: {e}")
        raise
    
    # Detect project context
    client_project_dir = task_registry.get('client_cwd')
    if not client_project_dir:
        workspace_parent = os.path.dirname(workspace)
        if workspace_parent.endswith('.agent-workspace'):
            client_project_dir = os.path.dirname(workspace_parent)
        else:
            client_project_dir = os.getcwd()
    
    project_context = detect_project_context(client_project_dir)
    context_prompt = format_project_context_prompt(project_context)
    
    # Get type-specific requirements
    type_requirements = get_type_specific_requirements(agent_type)
    
    # Create agent prompt (same as tmux version)
    agent_prompt = f"""You are a headless Claude agent in an orchestrator system.

🤖 AGENT IDENTITY:
- Agent ID: {agent_id}
- Agent Type: {agent_type}
- Task ID: {task_id}
- Parent Agent: {parent}
- Depth Level: {depth}
- Workspace: {workspace}

📝 YOUR MISSION:
{prompt}
{enrichment_prompt}
{context_prompt}

{type_requirements}

{orchestration_prompt}

🔗 MCP SELF-REPORTING WITH COORDINATION - You MUST use these MCP functions to report progress:

1. PROGRESS UPDATES (every few minutes):
```
mcp__claude-orchestrator__update_agent_progress
Parameters: 
- task_id: "{task_id}"
- agent_id: "{agent_id}"  
- status: "working" | "blocked" | "completed" | "error"
- message: "Description of current work"
- progress: 0-100 (percentage)

RETURNS: Your update confirmation + comprehensive status of ALL agents for coordination!
```

2. REPORT FINDINGS (whenever you discover something important):
```
mcp__claude-orchestrator__report_agent_finding
Parameters:
- task_id: "{task_id}"
- agent_id: "{agent_id}"
- finding_type: "issue" | "solution" | "insight" | "recommendation"
- severity: "low" | "medium" | "high" | "critical"  
- message: "What you discovered"
- data: {{"any": "additional info"}}

RETURNS: Your finding confirmation + comprehensive status of ALL agents for coordination!
```

3. SPAWN CHILD AGENTS (if you need specialized help):
```
mcp__claude-orchestrator__spawn_child_agent
Parameters:
- task_id: "{task_id}"
- parent_agent_id: "{agent_id}"
- child_agent_type: "investigator" | "builder" | "fixer" | etc
- child_prompt: "Specific task for the child agent"
```

🚨 CRITICAL PROTOCOL:
1. START by calling update_agent_progress with status="working", progress=0
2. REGULARLY update progress every few minutes
3. REPORT key findings as you discover them
4. SPAWN child agents if you need specialized help
5. END by calling update_agent_progress with status="completed", progress=100

You are working independently but can coordinate through the MCP orchestrator system.

BEGIN YOUR WORK NOW!
"""
    
    # Resource tracking for cleanup on failure
    prompt_file_created = None
    process_started = None
    log_file_created = None
    registry_updated = False
    global_registry_updated = False
    
    try:
        # Pre-flight checks
        has_space, free_mb, space_error = check_disk_space(workspace, min_mb=100)
        if not has_space:
            return {
                "success": False,
                "error": space_error
            }
        
        # Create logs directory
        logs_dir = f"{workspace}/logs"
        try:
            os.makedirs(logs_dir, exist_ok=True)
            # Test write access
            test_file = f"{logs_dir}/.write_test_{uuid.uuid4().hex[:8]}"
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
        except Exception as e:
            logger.error(f"Workspace logs directory not writable: {e}")
            return {
                "success": False,
                "error": f"Workspace logs directory not writable: {e}"
            }
        
        # Store agent prompt in file
        prompt_file = os.path.abspath(f"{workspace}/agent_prompt_{agent_id}.txt")
        with open(prompt_file, 'w') as f:
            f.write(agent_prompt)
        prompt_file_created = prompt_file
        
        # Get cursor-agent path and prepare command
        cursor_path = get_cursor_agent_path()
        log_file = f"{logs_dir}/{agent_id}_stream.jsonl"
        log_file_created = log_file
        
        # Prepare cursor-agent flags
        cursor_flags = CURSOR_AGENT_FLAGS.split()
        model = CURSOR_AGENT_MODEL
        
        # Build cursor-agent command
        cmd = [
            cursor_path,
            "-p", agent_prompt,
            "--output-format", "stream-json",
            "--model", model
        ] + cursor_flags
        
        logger.info(f"Deploying cursor-agent: {agent_id}")
        logger.info(f"Command: {' '.join(cmd[:5])}... (prompt truncated)")
        logger.info(f"Working directory: {client_project_dir}")
        logger.info(f"Log file: {log_file}")
        
        # Start cursor-agent as background process
        with open(log_file, 'w') as log_f:
            process = subprocess.Popen(
                cmd,
                cwd=client_project_dir,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # Detach from parent
                preexec_fn=os.setpgrp if hasattr(os, 'setpgrp') else None
            )
        
        process_started = process.pid
        logger.info(f"cursor-agent started with PID: {process.pid}")
        
        # Give process a moment to start
        time.sleep(2)
        
        # Check if process is still running
        try:
            process.poll()
            if process.returncode is not None:
                # Process died immediately
                logger.error(f"cursor-agent terminated immediately with exit code: {process.returncode}")
                
                # Read log file for error details
                error_details = ""
                if os.path.exists(log_file):
                    with open(log_file, 'r') as f:
                        error_details = f.read()[:500]
                
                # Cleanup
                if prompt_file_created and os.path.exists(prompt_file_created):
                    os.remove(prompt_file_created)
                
                return {
                    "success": False,
                    "error": f"cursor-agent terminated immediately (exit code: {process.returncode})",
                    "error_details": error_details
                }
        except Exception as e:
            logger.warning(f"Could not check process status: {e}")
        
        # Update registry with new agent
        agent_data = {
            "id": agent_id,
            "type": agent_type,
            "backend": "cursor",  # Mark as cursor-agent deployment
            "cursor_pid": process.pid,
            "cursor_session_id": None,  # Will be extracted from logs later
            "parent": parent,
            "depth": depth,
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "progress": 0,
            "last_update": datetime.now().isoformat(),
            "prompt": prompt[:200] + "..." if len(prompt) > 200 else prompt,
            "tracked_files": {
                "prompt_file": prompt_file,
                "log_file": log_file,
                "progress_file": f"{workspace}/progress/{agent_id}_progress.jsonl",
                "findings_file": f"{workspace}/findings/{agent_id}_findings.jsonl",
                "deploy_log": f"{workspace}/logs/deploy_{agent_id}.json"
            }
        }
        
        registry['agents'].append(agent_data)
        registry['total_spawned'] += 1
        registry['active_count'] += 1
        
        # Update hierarchy
        if parent not in registry['agent_hierarchy']:
            registry['agent_hierarchy'][parent] = []
        registry['agent_hierarchy'][parent].append(agent_id)
        
        # Save updated registry
        with open(registry_path, 'w') as f:
            json.dump(registry, f, indent=2)
        registry_updated = True
        
        # Update global registry
        with open(global_reg_path, 'r') as f:
            global_reg = json.load(f)
        
        global_reg['total_agents_spawned'] += 1
        global_reg['active_agents'] += 1
        global_reg['agents'][agent_id] = {
            'task_id': task_id,
            'type': agent_type,
            'backend': 'cursor',
            'parent': parent,
            'started_at': datetime.now().isoformat(),
            'cursor_pid': process.pid
        }
        
        with open(global_reg_path, 'w') as f:
            json.dump(global_reg, f, indent=2)
        global_registry_updated = True
        
        # Log successful deployment
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": "agent_deployed",
            "agent_id": agent_id,
            "backend": "cursor",
            "cursor_pid": process.pid,
            "cursor_agent_path": cursor_path,
            "model": model,
            "command": f"{cursor_path} -p [PROMPT] --output-format stream-json --model {model} {' '.join(cursor_flags)}",
            "success": True
        }
        
        with open(f"{workspace}/logs/deploy_{agent_id}.json", 'w') as f:
            json.dump(log_entry, f, indent=2)
        
        return {
            "success": True,
            "agent_id": agent_id,
            "cursor_pid": process.pid,
            "type": agent_type,
            "parent": parent,
            "task_id": task_id,
            "status": "deployed",
            "workspace": workspace,
            "deployment_method": "cursor-agent",
            "model": model,
            "log_file": log_file
        }
        
    except Exception as e:
        logger.error(f"cursor-agent deployment failed: {e}")
        logger.error(f"Cleaning up orphaned resources...")
        
        # Kill process if it was started
        if process_started:
            try:
                os.kill(process_started, 9)  # SIGKILL
                logger.info(f"Killed orphaned cursor-agent process: {process_started}")
            except Exception as cleanup_err:
                logger.error(f"Failed to kill process: {cleanup_err}")
        
        # Remove orphaned files
        if prompt_file_created and os.path.exists(prompt_file_created):
            try:
                os.remove(prompt_file_created)
                logger.info(f"Removed orphaned prompt file: {prompt_file_created}")
            except Exception as cleanup_err:
                logger.error(f"Failed to remove prompt file: {cleanup_err}")
        
        if log_file_created and os.path.exists(log_file_created):
            try:
                os.remove(log_file_created)
                logger.info(f"Removed orphaned log file: {log_file_created}")
            except Exception as cleanup_err:
                logger.error(f"Failed to remove log file: {cleanup_err}")
        
        # Note registry corruption
        if registry_updated or global_registry_updated:
            logger.error(f"Registry was partially updated before failure - may need manual cleanup")
        
        return {
            "success": False,
            "error": f"Failed to deploy cursor-agent: {str(e)}",
            "cleanup_performed": True,
            "resources_cleaned": {
                "cursor_pid": process_started,
                "prompt_file": prompt_file_created,
                "log_file": log_file_created
            }
        }


@mcp.tool
def get_real_task_status(task_id: str) -> Dict[str, Any]:
    """
    Get detailed status of a real task and its agents.
    
    Args:
        task_id: Task ID to query
    
    Returns:
        Complete task status
    """
    # Find the task workspace (may be in client or server location)
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
    
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    
    with open(registry_path, 'r') as f:
        registry = json.load(f)
    
    # Update agent statuses based on tmux sessions
    agents_completed = []
    for agent in registry['agents']:
        if agent['status'] == 'running' and 'tmux_session' in agent:
            # Check if tmux session still exists
            if not check_tmux_session_exists(agent['tmux_session']):
                agent['status'] = 'completed'
                agent['completed_at'] = datetime.now().isoformat()
                registry['active_count'] = max(0, registry['active_count'] - 1)
                registry['completed_count'] = registry.get('completed_count', 0) + 1
                agents_completed.append(agent['id'])
                logger.info(f"Detected agent {agent['id']} completed (tmux session terminated)")
    
    # Save updated registry
    with open(registry_path, 'w') as f:
        json.dump(registry, f, indent=2)
    
    # Update global registry for agents that completed
    if agents_completed:
        try:
            workspace_base = get_workspace_base_from_task_workspace(workspace)
            global_reg_path = get_global_registry_path(workspace_base)
            if os.path.exists(global_reg_path):
                with open(global_reg_path, 'r') as f:
                    global_reg = json.load(f)
                
                for agent_id in agents_completed:
                    if agent_id in global_reg.get('agents', {}):
                        global_reg['agents'][agent_id]['status'] = 'completed'
                        global_reg['agents'][agent_id]['completed_at'] = datetime.now().isoformat()
                        global_reg['active_agents'] = max(0, global_reg.get('active_agents', 0) - 1)
                
                with open(global_reg_path, 'w') as f:
                    json.dump(global_reg, f, indent=2)
                
                logger.info(f"Global registry updated: {len(agents_completed)} agents completed, active agents: {global_reg['active_agents']}")
        except Exception as e:
            logger.error(f"Failed to update global registry for completed agents: {e}")
    
    # Enhanced progress tracking - read JSONL files  
    progress_entries = []
    findings_entries = []
    
    # Read all progress JSONL files
    progress_dir = f"{workspace}/progress"
    if os.path.exists(progress_dir):
        for file in os.listdir(progress_dir):
            if file.endswith('_progress.jsonl'):
                try:
                    with open(f"{progress_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    progress = json.loads(line)
                                    progress_entries.append(progress)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Read all findings JSONL files
    findings_dir = f"{workspace}/findings"
    if os.path.exists(findings_dir):
        for file in os.listdir(findings_dir):
            if file.endswith('_findings.jsonl'):
                try:
                    with open(f"{findings_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    finding = json.loads(line)
                                    findings_entries.append(finding)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Sort by timestamp
    progress_entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    findings_entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    return {
        "success": True,
        "task_id": task_id,
        "description": registry.get('task_description'),
        "status": registry.get('status'),
        "workspace": workspace,
        "agents": {
            "total_spawned": registry.get('total_spawned', 0),
            "active": registry.get('active_count', 0),
            "completed": registry.get('completed_count', 0),
            "agents_list": registry.get('agents', [])
        },
        "hierarchy": registry.get('agent_hierarchy', {}),
        "enhanced_progress": {
            "recent_updates": progress_entries[:10],  # Last 10 progress updates
            "recent_findings": findings_entries[:5],   # Last 5 findings
            "total_progress_entries": len(progress_entries),
            "total_findings": len(findings_entries),
            "progress_frequency": len(progress_entries) / max((registry.get('total_spawned', 1) * 10), 1)  # Updates per agent per 10-min window
        },
        "spiral_status": registry.get('spiral_checks', {}),
        "limits": {
            "max_agents": registry.get('max_agents', 10),
            "max_concurrent": registry.get('max_concurrent', 5),
            "max_depth": registry.get('max_depth', 3)
        }
    }

# ============================================================================
# JSONL Helper Functions for Robust Log Reading
# ============================================================================

def read_jsonl_lines(filepath: str, max_lines: Optional[int] = None) -> List[str]:
    """
    Read JSONL file with robust error handling for incomplete/malformed lines.
    Returns raw text lines (not parsed JSON).

    Args:
        filepath: Path to JSONL file
        max_lines: Maximum number of lines to read (None = all)

    Returns:
        List of text lines
    """
    if not os.path.exists(filepath):
        return []

    try:
        lines = []
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line:  # Skip empty lines
                    lines.append(line)
                    if max_lines and len(lines) >= max_lines:
                        break
        return lines
    except Exception as e:
        logger.warning(f"Error reading JSONL file {filepath}: {e}")
        return []

def tail_jsonl_efficient(filepath: str, n_lines: int) -> List[str]:
    """
    Efficiently read last N lines from JSONL file using reverse seeking.
    Handles large files (GB+) without loading entire file into memory.

    Args:
        filepath: Path to JSONL file
        n_lines: Number of lines to read from end

    Returns:
        List of last N text lines
    """
    if not os.path.exists(filepath):
        return []

    if n_lines <= 0:
        return []

    try:
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            return []

        # For small files, just read all lines
        if file_size < 1024 * 1024:  # < 1MB
            all_lines = read_jsonl_lines(filepath)
            return all_lines[-n_lines:] if len(all_lines) > n_lines else all_lines

        # For large files, seek from end
        # Estimate: avg line ~300 bytes, read slightly more to be safe
        seek_size = min(n_lines * 400, file_size)

        with open(filepath, 'rb') as f:
            f.seek(-seek_size, os.SEEK_END)
            data = f.read().decode('utf-8', errors='ignore')

        # Split into lines and filter
        lines = [line.strip() for line in data.split('\n') if line.strip()]

        # Return last N lines
        return lines[-n_lines:] if len(lines) > n_lines else lines

    except Exception as e:
        logger.warning(f"Error tailing JSONL file {filepath}: {e}")
        return []

def filter_lines_regex(lines: List[str], pattern: Optional[str]) -> tuple[List[str], Optional[str]]:
    """
    Apply regex filter to lines.

    Args:
        lines: List of text lines
        pattern: Regex pattern (None = no filtering)

    Returns:
        Tuple of (filtered_lines, error_message)
        error_message is None if successful, string if regex invalid
    """
    if not pattern:
        return lines, None

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return [], f"Invalid regex pattern: {e}"

    filtered = [line for line in lines if regex.search(line)]
    return filtered, None

def parse_jsonl_lines(lines: List[str]) -> tuple[List[dict], List[dict]]:
    """
    Parse JSONL lines with robust error recovery.
    Skips malformed lines and continues parsing.

    Args:
        lines: List of text lines (each should be valid JSON)

    Returns:
        Tuple of (parsed_objects, parse_errors)
        parse_errors contains info about lines that failed to parse
    """
    parsed = []
    errors = []

    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)
            parsed.append(obj)
        except json.JSONDecodeError as e:
            errors.append({
                "line_number": i + 1,
                "line_preview": line[:100],  # Truncate for safety
                "error": str(e)
            })
            # Continue parsing next lines (don't fail on single bad line)

    return parsed, errors

def format_output_by_type(lines: List[str], format_type: str) -> tuple[Any, Optional[List[dict]]]:
    """
    Format lines according to requested output format.

    Args:
        lines: List of text lines
        format_type: 'text', 'jsonl', or 'parsed'

    Returns:
        Tuple of (formatted_output, parse_errors)
        parse_errors is None unless format_type='parsed'
    """
    if format_type == "text":
        return '\n'.join(lines), None

    elif format_type == "jsonl":
        return '\n'.join(lines), None

    elif format_type == "parsed":
        parsed, errors = parse_jsonl_lines(lines)
        return parsed, errors if errors else None

    else:
        raise ValueError(f"Unknown format type: {format_type}. Must be 'text', 'jsonl', or 'parsed'")

def collect_log_metadata(filepath: str, lines: List[str], filtered_lines: List[str],
                         parse_errors: Optional[List[dict]], source: str) -> dict:
    """
    Collect metadata about the log file and processing.

    Args:
        filepath: Path to log file
        lines: Original lines before filtering
        filtered_lines: Lines after filtering
        parse_errors: Parse errors if format='parsed', None otherwise
        source: 'jsonl_log' or 'tmux_session'

    Returns:
        Metadata dictionary
    """
    metadata = {
        "log_source": source,
        "total_lines": len(lines),
        "returned_lines": len(filtered_lines)
    }

    if os.path.exists(filepath):
        stat = os.stat(filepath)
        metadata["file_path"] = filepath
        metadata["file_size_bytes"] = stat.st_size
        metadata["file_modified_time"] = datetime.fromtimestamp(stat.st_mtime).isoformat()

    # Extract timestamps from first and last lines (if JSONL)
    if filtered_lines:
        try:
            first_obj = json.loads(filtered_lines[0])
            if 'timestamp' in first_obj:
                metadata["first_timestamp"] = first_obj['timestamp']
        except:
            pass

        try:
            last_obj = json.loads(filtered_lines[-1])
            if 'timestamp' in last_obj:
                metadata["last_timestamp"] = last_obj['timestamp']
        except:
            pass

    if parse_errors:
        metadata["parse_errors"] = parse_errors

    return metadata

# ============================================================================
# JSONL Truncation Functions - Prevent Log Bloat
# ============================================================================

# Truncation limits
MAX_LINE_LENGTH = 8192  # 8KB per JSONL line
MAX_TOOL_RESULT_CONTENT = 2048  # 2KB for tool_result.content
MAX_ASSISTANT_TEXT = 4096  # 4KB for assistant text messages

# Aggressive truncation limits (for quick status checks)
AGGRESSIVE_LINE_LENGTH = 1024  # 1KB per line
AGGRESSIVE_TOOL_RESULT = 512  # 512 bytes for tool_result.content

def detect_repetitive_content(lines: List[str]) -> dict:
    """
    Analyze lines for repetitive patterns (e.g., same tool calls repeated).

    Returns:
        Dict with repetition statistics and groups of similar lines
    """
    tool_call_counts = {}
    error_patterns = {}
    status_updates = []

    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)

            # Track tool calls
            if obj.get('type') == 'tool_use':
                tool_name = obj.get('name', 'unknown')
                tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1

            # Track errors
            elif 'error' in obj or obj.get('type') == 'error':
                error_msg = str(obj.get('error', obj.get('message', '')))[:100]
                error_patterns[error_msg] = error_patterns.get(error_msg, 0) + 1

            # Track status updates
            elif obj.get('type') in ['status', 'progress']:
                status_updates.append(i)

        except (json.JSONDecodeError, AttributeError):
            continue

    # Identify highly repetitive tool calls (more than 5 occurrences)
    repetitive_tools = {k: v for k, v in tool_call_counts.items() if v > 5}

    return {
        'tool_call_counts': tool_call_counts,
        'repetitive_tools': repetitive_tools,
        'error_patterns': error_patterns,
        'status_update_indices': status_updates,
        'has_repetition': bool(repetitive_tools) or any(count > 3 for count in error_patterns.values())
    }

def extract_critical_lines(lines: List[str], analysis: dict) -> List[int]:
    """
    Identify indices of critical lines that should be preserved.

    Returns:
        List of line indices that are critical
    """
    critical_indices = set()

    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)
            obj_type = obj.get('type', '')

            # Always keep errors
            if 'error' in obj or obj_type == 'error':
                critical_indices.add(i)

            # Keep status changes (but not all status updates)
            elif obj_type in ['completed', 'failed', 'blocked']:
                critical_indices.add(i)

            # Keep findings/insights
            elif obj_type in ['finding', 'insight', 'recommendation']:
                critical_indices.add(i)

            # Keep first and last occurrence of each unique tool call
            elif obj_type == 'tool_use':
                tool_name = obj.get('name', '')
                # This is simplified - in practice we'd track first/last per tool
                # For now, we'll handle this in the sampling logic
                pass

        except (json.JSONDecodeError, AttributeError):
            continue

    # Always include first and last lines
    if lines:
        critical_indices.add(0)
        critical_indices.add(len(lines) - 1)

    return sorted(list(critical_indices))

def intelligent_sample_lines(lines: List[str], max_bytes: int, analysis: dict) -> tuple[List[str], dict]:
    """
    Intelligently sample lines to fit within max_bytes while preserving critical info.

    Strategy:
    1. Always include critical lines (errors, status changes, findings)
    2. For repetitive content, show first + last + count summary
    3. Sample evenly from remaining lines

    Returns:
        Tuple of (sampled_lines, sampling_stats)
    """
    if not lines:
        return [], {'sampled': False}

    # Calculate current size
    current_size = sum(len(line) for line in lines)
    if current_size <= max_bytes:
        return lines, {'sampled': False, 'original_size': current_size}

    # Get critical line indices
    critical_indices = extract_critical_lines(lines, analysis)
    critical_lines_size = sum(len(lines[i]) for i in critical_indices)

    # If critical lines alone exceed max_bytes, we need aggressive truncation
    if critical_lines_size > max_bytes:
        # Take first N and last N critical lines
        budget_per_end = max_bytes // 2
        result = []
        size = 0

        # Add from beginning
        for i in critical_indices:
            if size + len(lines[i]) > budget_per_end:
                break
            result.append((i, lines[i]))
            size += len(lines[i])

        # Add separator
        separator = json.dumps({
            'type': 'truncation_marker',
            'message': f'... {len(lines) - len(result)} lines omitted ...',
            'reason': 'Critical lines exceeded budget'
        })
        result.append((-1, separator))

        # Add from end
        size = 0
        end_lines = []
        for i in reversed(critical_indices):
            if size + len(lines[i]) > budget_per_end:
                break
            end_lines.insert(0, (i, lines[i]))
            size += len(lines[i])

        result.extend(end_lines)

        return [line for _, line in result], {
            'sampled': True,
            'strategy': 'critical_only',
            'original_lines': len(lines),
            'sampled_lines': len(result),
            'original_size': current_size,
            'final_size': sum(len(l) for _, l in result)
        }

    # Otherwise, smart sampling: critical + evenly sampled non-critical
    remaining_budget = max_bytes - critical_lines_size
    non_critical_indices = [i for i in range(len(lines)) if i not in critical_indices]

    # Sample non-critical lines
    sampled_non_critical = []
    if non_critical_indices and remaining_budget > 0:
        # Calculate how many we can fit
        avg_line_size = sum(len(lines[i]) for i in non_critical_indices) / len(non_critical_indices)
        target_count = min(len(non_critical_indices), int(remaining_budget / avg_line_size))

        # Sample evenly
        if target_count > 0:
            step = len(non_critical_indices) / target_count
            sampled_non_critical = [non_critical_indices[int(i * step)] for i in range(target_count)]

    # Combine and sort
    all_indices = sorted(critical_indices + sampled_non_critical)
    result = []

    for i, idx in enumerate(all_indices):
        result.append(lines[idx])
        # Add gap markers where we skipped lines
        if i < len(all_indices) - 1 and all_indices[i + 1] - idx > 1:
            gap_size = all_indices[i + 1] - idx - 1
            marker = json.dumps({
                'type': 'truncation_marker',
                'message': f'... {gap_size} lines omitted ...'
            })
            result.append(marker)

    final_size = sum(len(line) for line in result)

    return result, {
        'sampled': True,
        'strategy': 'intelligent_sampling',
        'original_lines': len(lines),
        'sampled_lines': len(all_indices),
        'critical_lines': len(critical_indices),
        'non_critical_sampled': len(sampled_non_critical),
        'original_size': current_size,
        'final_size': final_size,
        'compression_ratio': round(final_size / current_size, 3)
    }

def summarize_output(lines: List[str]) -> str:
    """
    Create a summary showing only errors, status changes, and key findings.

    Returns:
        Summary string
    """
    summary_items = []
    errors = []
    status_changes = []
    findings = []
    tool_calls = {}

    for line in lines:
        try:
            obj = json.loads(line)
            obj_type = obj.get('type', '')

            # Collect errors
            if 'error' in obj or obj_type == 'error':
                error_msg = obj.get('error', obj.get('message', 'Unknown error'))
                errors.append(error_msg)

            # Collect status changes
            elif obj_type in ['completed', 'failed', 'blocked', 'status']:
                status = obj.get('status', obj_type)
                message = obj.get('message', '')
                status_changes.append(f"{status}: {message}")

            # Collect findings
            elif obj_type in ['finding', 'insight', 'recommendation']:
                findings.append(obj.get('message', str(obj)))

            # Count tool calls
            elif obj_type == 'tool_use':
                tool_name = obj.get('name', 'unknown')
                tool_calls[tool_name] = tool_calls.get(tool_name, 0) + 1

        except (json.JSONDecodeError, AttributeError):
            continue

    # Build summary
    summary_items.append(f"=== OUTPUT SUMMARY ({len(lines)} total lines) ===\n")

    if errors:
        summary_items.append(f"\nERRORS ({len(errors)}):")
        for i, err in enumerate(errors[:5], 1):  # Show first 5
            summary_items.append(f"  {i}. {err}")
        if len(errors) > 5:
            summary_items.append(f"  ... and {len(errors) - 5} more errors")

    if status_changes:
        summary_items.append(f"\nSTATUS CHANGES ({len(status_changes)}):")
        for i, status in enumerate(status_changes[-5:], 1):  # Show last 5
            summary_items.append(f"  {i}. {status}")

    if findings:
        summary_items.append(f"\nFINDINGS ({len(findings)}):")
        for i, finding in enumerate(findings, 1):
            summary_items.append(f"  {i}. {finding}")

    if tool_calls:
        summary_items.append(f"\nTOOL CALLS:")
        for tool, count in sorted(tool_calls.items(), key=lambda x: -x[1]):
            summary_items.append(f"  - {tool}: {count}x")

    return '\n'.join(summary_items)

def smart_preview_truncate(text: str, max_length: int) -> str:
    """
    Intelligent preview: first N + last M lines.
    Use for: file contents, long outputs.

    Optimized for orchestrator's use case:
    - Main agent doesn't need full file contents
    - Wants to see: what file, rough size, first/last lines
    - Debugging: can always read raw log if needed

    Args:
        text: Text to truncate
        max_length: Maximum length in characters

    Returns:
        Truncated text with marker
    """
    if len(text) <= max_length:
        return text

    lines = text.split('\n')

    # Strategy: Keep first 30 lines + last 10 lines
    # This shows: file header/structure + recent changes
    PREVIEW_HEAD = 30
    PREVIEW_TAIL = 10

    if len(lines) <= PREVIEW_HEAD + PREVIEW_TAIL:
        # Fallback to line-based truncation
        return line_based_truncate(text, max_length)

    head_lines = lines[:PREVIEW_HEAD]
    tail_lines = lines[-PREVIEW_TAIL:]

    removed_lines = len(lines) - (PREVIEW_HEAD + PREVIEW_TAIL)
    removed_chars = len(text) - (sum(len(l) for l in head_lines) + sum(len(l) for l in tail_lines))

    marker = f"\n\n[... TRUNCATED: {removed_lines} lines ({removed_chars} chars) removed ...]\n\n"

    preview = '\n'.join(head_lines) + marker + '\n'.join(tail_lines)

    # If preview still too long, use line-based truncation
    if len(preview) > max_length:
        return line_based_truncate(preview, max_length)

    return preview

def line_based_truncate(text: str, max_length: int) -> str:
    """
    Truncate at line boundaries to preserve readability.
    Use for: code snippets, structured output.

    Args:
        text: Text to truncate
        max_length: Maximum length in characters

    Returns:
        Truncated text with marker
    """
    if len(text) <= max_length:
        return text

    lines = text.split('\n')

    # Try to fit whole lines within max_length
    kept_lines = []
    current_length = 0
    marker_space = 200  # Reserve space for marker

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_length + line_len > max_length - marker_space:
            break
        kept_lines.append(line)
        current_length += line_len

    if len(kept_lines) == len(lines):
        return text  # All fit

    removed_lines = len(lines) - len(kept_lines)
    removed_chars = len(text) - current_length

    marker = f"\n\n[... TRUNCATED: {removed_lines} lines ({removed_chars} chars) removed ...]"
    return '\n'.join(kept_lines) + marker

def simple_truncate(text: str, max_length: int) -> str:
    """
    Simple character-based truncation with marker.
    Use for: assistant text, simple strings.

    Args:
        text: Text to truncate
        max_length: Maximum length in characters

    Returns:
        Truncated text with marker
    """
    if len(text) <= max_length:
        return text

    marker_template = "\n\n[... TRUNCATED: {removed} chars removed ...]"
    # Calculate space needed for marker (with placeholder)
    marker_len = len(marker_template.format(removed=999999))  # Conservative estimate

    removed = len(text) - max_length + marker_len
    truncated = text[:max_length - marker_len]
    return truncated + marker_template.format(removed=removed)

def truncate_coordination_info(coord_data: dict) -> dict:
    """
    Intelligently truncate coordination_info structure to reduce size from ~25KB to ~5KB.

    This function is designed to handle the coordination_info structure returned by
    MCP tools (update_agent_progress, report_agent_finding) which contains:
    - agents_registry: Full details of all agents
    - coordination_data.recent_progress: Last 20 progress updates
    - coordination_data.recent_findings: Last 10 findings

    Strategy:
    - Keep only 3 most recent findings (not 10) → saves ~7KB
    - Keep only 5 most recent progress updates (not 20) → saves ~5KB
    - Summarize agents_registry (counts only, not full details) → saves ~4KB

    Args:
        coord_data: Parsed coordination_info dictionary

    Returns:
        Truncated coordination_info with same structure but reduced data
    """
    import copy

    # Deep copy to avoid mutating original
    truncated = copy.deepcopy(coord_data)

    # Handle coordination_data if present
    if 'coordination_data' in truncated:
        coord = truncated['coordination_data']

        # Truncate recent_findings: keep only 3 most recent (not 10)
        if 'recent_findings' in coord and isinstance(coord['recent_findings'], list):
            if len(coord['recent_findings']) > 3:
                coord['recent_findings'] = coord['recent_findings'][:3]
                coord['findings_truncated'] = True

        # Truncate recent_progress: keep only 5 most recent (not 20)
        if 'recent_progress' in coord and isinstance(coord['recent_progress'], list):
            if len(coord['recent_progress']) > 5:
                coord['recent_progress'] = coord['recent_progress'][:5]
                coord['progress_truncated'] = True

    # Summarize agents_registry: keep counts only, not full details
    if 'agents' in truncated and isinstance(truncated['agents'], list):
        agent_list = truncated['agents']
        if len(agent_list) > 0:
            # Replace full agent list with summary
            truncated['agents_summary'] = {
                'total_count': len(agent_list),
                'by_status': {},
                'by_type': {}
            }

            # Count by status and type
            for agent in agent_list:
                status = agent.get('status', 'unknown')
                agent_type = agent.get('type', 'unknown')

                truncated['agents_summary']['by_status'][status] = \
                    truncated['agents_summary']['by_status'].get(status, 0) + 1
                truncated['agents_summary']['by_type'][agent_type] = \
                    truncated['agents_summary']['by_type'].get(agent_type, 0) + 1

            # Keep only 2 sample agents (first and last) for reference
            truncated['agents'] = [agent_list[0], agent_list[-1]] if len(agent_list) > 1 else agent_list
            truncated['agents_truncated'] = True

    # Mark as truncated for tracking
    truncated['_truncated'] = True

    return truncated

def detect_and_truncate_binary(content: str, max_length: int) -> str:
    """
    Aggressively truncate base64/binary data.

    Args:
        content: Content to check and potentially truncate
        max_length: Maximum length for non-binary content

    Returns:
        Truncated content or summary if binary
    """
    import re

    # Detect base64 pattern (long sequences of base64 chars)
    if len(content) > 200:
        base64_pattern = r'^[A-Za-z0-9+/]{100,}={0,2}$'
        if re.match(base64_pattern, content[:200]):
            return f"[BASE64_DATA: {len(content)} bytes, truncated for log efficiency]"

    # Detect binary indicators
    if len(content) > 500:
        binary_indicators = ['\\x00', 'PNG\\r\\n', 'GIF89', 'JFIF']
        if any(indicator in content[:500] for indicator in binary_indicators):
            return f"[BINARY_DATA: {len(content)} bytes, truncated for log efficiency]"

    # Not binary, use smart preview
    return smart_preview_truncate(content, max_length)

def is_already_truncated(obj: dict) -> bool:
    """
    Check if object was already truncated.
    Prevents re-truncation that loses more data.

    Args:
        obj: Parsed JSON object

    Returns:
        True if already truncated
    """
    # Check for truncation marker flag
    if obj.get('truncated') == True:
        return True

    # Check for truncation text markers (recursive)
    def has_truncation_marker(value):
        if isinstance(value, str):
            return '[... TRUNCATED:' in value or '[BASE64_DATA:' in value or '[BINARY_DATA:' in value
        elif isinstance(value, dict):
            return any(has_truncation_marker(v) for v in value.values())
        elif isinstance(value, list):
            return any(has_truncation_marker(item) for item in value)
        return False

    return has_truncation_marker(obj)

def truncate_json_structure(obj: dict, max_length: int) -> dict:
    """
    Truncate while preserving JSON structure.
    Specifically targets tool_result.content and assistant text bloat.

    Args:
        obj: Parsed JSON object
        max_length: Maximum length for the serialized JSON

    Returns:
        Truncated object that maintains JSON validity
    """
    import copy

    # Check if already truncated
    if is_already_truncated(obj):
        return obj

    # Deep copy to avoid mutating original
    truncated = copy.deepcopy(obj)

    # Handle different message types
    msg_type = truncated.get('type')

    # NEVER truncate error messages
    if msg_type == 'error':
        return truncated

    # NEVER truncate system init messages
    if msg_type == 'system' and truncated.get('subtype') == 'init':
        return truncated

    # Truncate user messages (tool_result content)
    if msg_type == 'user' and 'message' in truncated:
        message = truncated['message']
        if 'content' in message and isinstance(message['content'], list):
            for item in message['content']:
                if isinstance(item, dict) and item.get('type') == 'tool_result':
                    # This is the bloat target!
                    if 'content' in item and isinstance(item['content'], str):
                        original_len = len(item['content'])
                        if original_len > MAX_TOOL_RESULT_CONTENT:
                            # Try to detect and intelligently truncate coordination_info
                            try:
                                parsed_content = json.loads(item['content'])

                                # Check if this is coordination_info structure
                                # It typically has keys like: coordination_info, own_update, own_finding
                                is_coordination = (
                                    isinstance(parsed_content, dict) and
                                    'coordination_info' in parsed_content
                                )

                                if is_coordination:
                                    # Apply intelligent truncation to coordination_info
                                    if 'coordination_info' in parsed_content:
                                        parsed_content['coordination_info'] = truncate_coordination_info(
                                            parsed_content['coordination_info']
                                        )

                                    # Re-serialize with truncated coordination_info
                                    item['content'] = json.dumps(parsed_content)
                                    item['truncated'] = True
                                    item['truncation_type'] = 'intelligent_coordination_info'
                                    item['original_length'] = original_len
                                else:
                                    # Not coordination_info, use existing blind truncation
                                    item['content'] = detect_and_truncate_binary(
                                        item['content'],
                                        MAX_TOOL_RESULT_CONTENT
                                    )
                                    item['truncated'] = True
                                    item['truncation_type'] = 'blind_string'
                                    item['original_length'] = original_len

                            except (json.JSONDecodeError, TypeError, KeyError):
                                # Not JSON or parsing failed, fall back to binary detection
                                item['content'] = detect_and_truncate_binary(
                                    item['content'],
                                    MAX_TOOL_RESULT_CONTENT
                                )
                                item['truncated'] = True
                                item['truncation_type'] = 'blind_string_fallback'
                                item['original_length'] = original_len

    # Truncate assistant messages (long reasoning)
    if msg_type == 'assistant' and 'message' in truncated:
        message = truncated['message']
        if 'content' in message and isinstance(message['content'], list):
            for item in message['content']:
                if isinstance(item, dict) and 'text' in item:
                    original_len = len(item['text'])
                    if original_len > MAX_ASSISTANT_TEXT:
                        item['text'] = line_based_truncate(
                            item['text'],
                            MAX_ASSISTANT_TEXT
                        )
                        item['truncated'] = True
                        item['original_length'] = original_len

    return truncated

def safe_json_truncate(line: str, max_length: int) -> str:
    """
    Truncate JSONL line while preserving JSON validity.
    Main entry point for line truncation.

    Args:
        line: Raw JSONL line
        max_length: Maximum length for the line

    Returns:
        Truncated line (still valid JSON)
    """
    if len(line) <= max_length:
        return line

    try:
        # Parse JSON
        obj = json.loads(line)

        # Truncate content fields (preserves structure)
        truncated_obj = truncate_json_structure(obj, max_length)

        # Re-serialize
        truncated_line = json.dumps(truncated_obj)

        # If STILL too long after smart truncation, aggressive fallback
        if len(truncated_line) > max_length:
            # Last resort: return error marker with metadata
            return json.dumps({
                "type": "truncation_error",
                "error": "Line too large even after content truncation",
                "original_type": obj.get('type'),
                "original_size": len(line),
                "max_allowed": max_length,
                "note": "Check raw log file for full content"
            })

        return truncated_line

    except json.JSONDecodeError as e:
        # Malformed JSON, simple truncate
        logger.warning(f"Malformed JSONL during truncation: {e}")
        return simple_truncate(line, max_length)

@mcp.tool
def get_agent_output(
    task_id: str,
    agent_id: str,
    tail: Optional[int] = None,
    filter: Optional[str] = None,
    format: str = "text",
    include_metadata: bool = False,
    max_bytes: Optional[int] = None,
    aggressive_truncate: bool = False,
    response_format: str = "full",
    recent_lines: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get agent output from persistent JSONL log file with filtering and tail support.
    Falls back to tmux for backward compatibility.

    Args:
        task_id: Task ID containing the agent
        agent_id: Agent ID to get output from
        tail: Number of most recent lines to return (None = all lines)
        filter: Regex pattern to filter output lines (applied before tail)
        format: Output format - "text", "jsonl", or "parsed"
        include_metadata: Include file metadata (size, line count, timestamps)
        max_bytes: Maximum total response size in bytes. If exceeded, intelligently
                   sample lines (first N + last N) while preserving critical info.
                   Default: None (no limit)
        aggressive_truncate: Use aggressive truncation limits (1KB/line, 512B tool_result)
                             instead of standard (8KB/line, 2KB tool_result). Useful for
                             quick status checks. Default: False
        response_format: Response format mode:
                         - "full": Full output with standard/aggressive truncation
                         - "summary": Only errors, status changes, key findings
                         - "compact": Enable aggressive_truncate automatically
                         - "recent": Use efficient tail-based parsing with smart truncation
                         Default: "full"
        recent_lines: Number of recent log lines to parse (for cursor backend).
                      When specified, uses efficient tail-based parsing that:
                      - Reads only last N lines instead of entire file
                      - Applies smart truncation to tool results
                      - Skips thinking blocks (saves tokens)
                      Default: None (read all). Recommended: 50-200 for monitoring.

    Returns:
        Dict with output and metadata
    """
    # Validate format parameter
    if format not in ["text", "jsonl", "parsed"]:
        return {
            "success": False,
            "error": f"Invalid format '{format}'. Must be 'text', 'jsonl', or 'parsed'",
            "agent_id": agent_id
        }

    # Validate response_format parameter
    if response_format not in ["full", "summary", "compact", "recent"]:
        return {
            "success": False,
            "error": f"Invalid response_format '{response_format}'. Must be 'full', 'summary', 'compact', or 'recent'",
            "agent_id": agent_id
        }

    # Apply response_format overrides
    if response_format == "compact":
        aggressive_truncate = True
    elif response_format == "recent":
        # Use recent_lines mode with smart defaults
        if recent_lines is None:
            recent_lines = 100  # Default for recent mode
        aggressive_truncate = True
    elif response_format == "summary":
        # Summary format will be handled later after reading lines
        pass

    # Determine truncation limits based on aggressive_truncate flag
    line_limit = AGGRESSIVE_LINE_LENGTH if aggressive_truncate else MAX_LINE_LENGTH
    tool_result_limit = AGGRESSIVE_TOOL_RESULT if aggressive_truncate else MAX_TOOL_RESULT_CONTENT

    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }

    # Load agent registry
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    try:
        with open(registry_path, 'r') as f:
            registry = json.load(f)
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read agent registry: {e}"
        }

    # Find agent in list
    agent = None
    for a in registry['agents']:
        if a['id'] == agent_id:
            agent = a
            break

    if not agent:
        return {
            "success": False,
            "error": f"Agent {agent_id} not found",
            "agent_id": agent_id
        }

    # Try reading from JSONL log file first
    log_path = f"{workspace}/logs/{agent_id}_stream.jsonl"
    source = "jsonl_log"
    session_status = "unknown"
    
    # Detect backend type for proper parsing
    backend = agent.get('backend', AGENT_BACKEND)  # Default to configured backend (cursor-agent)

    if os.path.exists(log_path):
        try:
            # Special handling for cursor-agent logs
            if backend == 'cursor':
                logger.info(f"Detected cursor-agent log for {agent_id}")

                # Use efficient recent parsing when recent_lines is specified
                if recent_lines is not None and recent_lines > 0:
                    logger.info(f"Using recent parsing mode: last {recent_lines} lines")
                    parsed_result = parse_cursor_stream_jsonl_recent(
                        log_path,
                        recent_lines=recent_lines,
                        include_thinking=False,  # Skip thinking for efficiency
                        aggressive_truncate=aggressive_truncate
                    )

                    if not parsed_result.get('success', True):
                        return {
                            "success": False,
                            "error": parsed_result.get('error', 'Failed to parse cursor log'),
                            "agent_id": agent_id
                        }

                    # Format recent output
                    if format == "parsed" or format == "jsonl":
                        output = {
                            "session_id": parsed_result.get('session_id'),
                            "model": parsed_result.get('model'),
                            "cwd": parsed_result.get('cwd'),
                            "recent_events": parsed_result.get('recent_events', []),
                            "recent_tool_calls": parsed_result.get('recent_tool_calls', []),
                            "recent_messages": parsed_result.get('recent_messages', []),
                            "final_result": parsed_result.get('final_result'),
                            "stats": parsed_result.get('stats', {})
                        }
                    else:  # text format
                        text_parts = []
                        stats = parsed_result.get('stats', {})
                        text_parts.append(f"=== Recent Agent Activity ({stats.get('lines_parsed', 0)}/{stats.get('total_lines', 0)} lines) ===")
                        text_parts.append(f"Session: {parsed_result.get('session_id', 'unknown')}")
                        text_parts.append(f"Model: {parsed_result.get('model', 'unknown')}")
                        text_parts.append("")

                        # Recent messages
                        recent_msgs = parsed_result.get('recent_messages', [])
                        if recent_msgs:
                            text_parts.append(f"=== Recent Messages ({len(recent_msgs)}) ===")
                            for msg in recent_msgs[-3:]:  # Last 3 messages
                                text_parts.append(f"▶ {msg[:300]}{'...' if len(msg) > 300 else ''}")
                            text_parts.append("")

                        # Recent tool calls
                        recent_tools = parsed_result.get('recent_tool_calls', [])
                        if recent_tools:
                            text_parts.append(f"=== Recent Tool Calls ({len(recent_tools)}) ===")
                            for tool in recent_tools[-5:]:  # Last 5 tool calls
                                tool_type = tool.get('tool_type', 'unknown')
                                status = tool.get('status', 'unknown')
                                if tool_type == 'shell':
                                    cmd = tool.get('command', '')[:60]
                                    text_parts.append(f"Shell [{status}]: {cmd}{'...' if len(tool.get('command', '')) > 60 else ''}")
                                elif tool_type == 'edit':
                                    text_parts.append(f"Edit [{status}]: {tool.get('path', 'unknown')}")
                                elif tool_type == 'read':
                                    text_parts.append(f"Read [{status}]: {tool.get('path', 'unknown')}")
                                else:
                                    text_parts.append(f"{tool_type} [{status}]")
                            text_parts.append("")

                        # Final result if exists
                        final = parsed_result.get('final_result')
                        if final:
                            text_parts.append(f"=== Result: {final.get('subtype', 'unknown')} ===")
                            if final.get('is_error'):
                                text_parts.append(f"ERROR: {final.get('result_text', '')[:200]}")
                            text_parts.append(f"Duration: {final.get('duration_ms', 0)}ms")

                        output = '\n'.join(text_parts)

                    return {
                        "success": True,
                        "agent_id": agent_id,
                        "backend": "cursor",
                        "session_id": parsed_result.get('session_id'),
                        "session_status": "completed" if parsed_result.get('final_result') else "running",
                        "output": output,
                        "source": "cursor_stream_json_recent",
                        "format": format,
                        "metadata": {
                            "recent_lines_requested": recent_lines,
                            "total_lines": parsed_result.get('stats', {}).get('total_lines', 0),
                            "lines_parsed": parsed_result.get('stats', {}).get('lines_parsed', 0),
                            "truncation_applied": parsed_result.get('stats', {}).get('truncation_applied', False),
                            "model": parsed_result.get('model')
                        } if include_metadata else None
                    }

                # Full parsing (original behavior)
                parsed_result = parse_cursor_stream_jsonl(log_path, include_thinking=CURSOR_ENABLE_THINKING_LOGS)

                if not parsed_result.get('success', True):  # parse function returns success=False on error
                    return {
                        "success": False,
                        "error": parsed_result.get('error', 'Failed to parse cursor log'),
                        "agent_id": agent_id
                    }

                # Extract cursor session_id and update agent if not already set
                cursor_session_id = parsed_result.get('session_id')
                if cursor_session_id and not agent.get('cursor_session_id'):
                    agent['cursor_session_id'] = cursor_session_id
                    # Update registry with session_id
                    try:
                        registry = read_registry_with_lock(registry_path)
                        for a in registry['agents']:
                            if a['id'] == agent_id:
                                a['cursor_session_id'] = cursor_session_id
                                break
                        write_registry_with_lock(registry_path, registry)
                    except Exception as e:
                        logger.warning(f"Failed to update registry with cursor session_id: {e}")
                
                # Format output based on requested format
                if format == "parsed" or format == "jsonl":
                    # Return rich parsed structure
                    output = {
                        "session_id": parsed_result.get('session_id'),
                        "model": parsed_result.get('model'),
                        "cwd": parsed_result.get('cwd'),
                        "events": parsed_result.get('events', []),
                        "tool_calls": parsed_result.get('tool_calls', []),
                        "assistant_messages": parsed_result.get('assistant_messages', []),
                        "thinking_text": parsed_result.get('thinking_text', ''),
                        "final_result": parsed_result.get('final_result'),
                        "duration_ms": parsed_result.get('duration_ms', 0),
                        "success": parsed_result.get('success', False)
                    }
                else:  # text format
                    # Format as human-readable text
                    text_parts = []
                    text_parts.append(f"=== Cursor Agent Output ===")
                    text_parts.append(f"Session ID: {parsed_result.get('session_id')}")
                    text_parts.append(f"Model: {parsed_result.get('model')}")
                    text_parts.append(f"Duration: {parsed_result.get('duration_ms')}ms")
                    text_parts.append("")
                    
                    # Assistant messages
                    for msg in parsed_result.get('assistant_messages', []):
                        text_parts.append(f"Assistant: {msg}")
                        text_parts.append("")
                    
                    # Tool calls summary
                    tool_calls = parsed_result.get('tool_calls', [])
                    if tool_calls:
                        text_parts.append(f"=== Tool Calls ({len(tool_calls)}) ===")
                        for tool in tool_calls:
                            tool_type = tool.get('tool_type')
                            status = tool.get('status')
                            if tool_type == 'shell':
                                text_parts.append(f"Shell [{status}]: {tool.get('command')}")
                                if status == 'completed':
                                    text_parts.append(f"  Exit: {tool.get('exit_code')}, Time: {tool.get('execution_time_ms')}ms")
                                    if tool.get('stdout'):
                                        text_parts.append(f"  Stdout: {tool.get('stdout')[:200]}")
                            elif tool_type == 'edit':
                                text_parts.append(f"Edit [{status}]: {tool.get('path')}")
                                if status == 'completed':
                                    text_parts.append(f"  +{tool.get('lines_added')} -{tool.get('lines_removed')} lines")
                            elif tool_type == 'read':
                                text_parts.append(f"Read [{status}]: {tool.get('path')}")
                        text_parts.append("")
                    
                    # Final result
                    final = parsed_result.get('final_result')
                    if final:
                        text_parts.append(f"=== Result ===")
                        text_parts.append(f"Status: {final.get('subtype')}")
                        text_parts.append(f"Result: {final.get('result_text', '')[:500]}")
                    
                    output = '\n'.join(text_parts)
                
                return {
                    "success": True,
                    "agent_id": agent_id,
                    "backend": "cursor",
                    "session_id": parsed_result.get('session_id'),
                    "session_status": "completed" if parsed_result.get('success') else "error",
                    "output": output,
                    "source": "cursor_stream_json",
                    "format": format,
                    "metadata": {
                        "duration_ms": parsed_result.get('duration_ms'),
                        "event_count": len(parsed_result.get('events', [])),
                        "tool_call_count": len(parsed_result.get('tool_calls', [])),
                        "model": parsed_result.get('model'),
                        "has_thinking": bool(parsed_result.get('thinking_text'))
                    } if include_metadata else None
                }
            
            # Standard claude/tmux log handling
            # Read lines (with tail if specified)
            if tail and tail > 0:
                lines = tail_jsonl_efficient(log_path, tail)
            else:
                lines = read_jsonl_lines(log_path)

            # Store original line count before filtering
            original_lines = lines.copy()

            # Apply filter if specified
            if filter:
                lines, filter_error = filter_lines_regex(lines, filter)
                if filter_error:
                    return {
                        "success": False,
                        "error": filter_error,
                        "error_type": "invalid_regex",
                        "agent_id": agent_id
                    }

            # Handle summary format early (before truncation)
            if response_format == "summary":
                summary_output = summarize_output(lines)
                return {
                    "success": True,
                    "agent_id": agent_id,
                    "session_status": "unknown",  # Will be determined below if needed
                    "output": summary_output,
                    "source": source,
                    "format": "summary",
                    "metadata": {
                        "total_lines_analyzed": len(lines),
                        "response_format": "summary"
                    }
                }

            # Apply per-line truncation to prevent log bloat
            truncated_lines = []
            truncation_stats = {
                "lines_truncated": 0,
                "bytes_before": 0,
                "bytes_after": 0,
                "aggressive_mode": aggressive_truncate
            }

            for line in lines:
                original_size = len(line)
                truncation_stats["bytes_before"] += original_size

                if original_size > line_limit:
                    truncated_line = safe_json_truncate(line, line_limit)
                    truncated_lines.append(truncated_line)
                    truncation_stats["lines_truncated"] += 1
                    truncation_stats["bytes_after"] += len(truncated_line)
                else:
                    truncated_lines.append(line)
                    truncation_stats["bytes_after"] += original_size

            # Use truncated lines for output
            lines = truncated_lines

            # Apply intelligent sampling if max_bytes specified
            sampling_stats = None
            if max_bytes and max_bytes > 0:
                # Analyze content for repetition
                content_analysis = detect_repetitive_content(lines)

                # Apply intelligent sampling
                lines, sampling_stats = intelligent_sample_lines(lines, max_bytes, content_analysis)

                # Add analysis to truncation stats for metadata
                if sampling_stats and sampling_stats.get('sampled'):
                    truncation_stats['sampling_applied'] = True
                    truncation_stats['content_analysis'] = {
                        'has_repetition': content_analysis.get('has_repetition'),
                        'repetitive_tools': list(content_analysis.get('repetitive_tools', {}).keys())
                    }

            # Format output
            try:
                output, parse_errors = format_output_by_type(lines, format)
            except ValueError as e:
                return {
                    "success": False,
                    "error": str(e),
                    "agent_id": agent_id
                }

            # Determine session status based on tmux
            if 'tmux_session' in agent:
                if check_tmux_session_exists(agent['tmux_session']):
                    session_status = "running"
                else:
                    session_status = "terminated"
            else:
                session_status = "completed"

            # Build response
            response = {
                "success": True,
                "agent_id": agent_id,
                "session_status": session_status,
                "output": output,
                "source": source
            }

            # Add metadata if requested
            if include_metadata:
                metadata = collect_log_metadata(
                    log_path,
                    original_lines,
                    lines,
                    parse_errors,
                    source
                )
                if filter:
                    metadata["filter_pattern"] = filter
                    metadata["matched_lines"] = len(lines)

                # Add truncation statistics
                if truncation_stats["lines_truncated"] > 0 or truncation_stats.get("aggressive_mode"):
                    bytes_saved = truncation_stats["bytes_before"] - truncation_stats["bytes_after"]
                    metadata["truncation_stats"] = {
                        "lines_truncated": truncation_stats["lines_truncated"],
                        "total_lines": len(original_lines),
                        "truncation_ratio": round(truncation_stats["lines_truncated"] / len(original_lines), 3) if len(original_lines) > 0 else 0,
                        "bytes_saved": bytes_saved,
                        "bytes_before": truncation_stats["bytes_before"],
                        "bytes_after": truncation_stats["bytes_after"],
                        "space_savings_percent": round((bytes_saved / truncation_stats["bytes_before"]) * 100, 1) if truncation_stats["bytes_before"] > 0 else 0,
                        "max_line_length": line_limit,
                        "max_tool_result_content": tool_result_limit,
                        "aggressive_mode": aggressive_truncate
                    }
                    # Add content analysis if sampling was applied
                    if truncation_stats.get("sampling_applied"):
                        metadata["truncation_stats"]["content_analysis"] = truncation_stats["content_analysis"]

                # Add sampling statistics if intelligent sampling was applied
                if sampling_stats and sampling_stats.get('sampled'):
                    metadata["sampling_stats"] = sampling_stats
                    metadata["max_bytes_limit"] = max_bytes

                # Add response format info
                metadata["response_format"] = response_format
                if aggressive_truncate:
                    metadata["aggressive_truncate"] = True

                response["metadata"] = metadata

            # Keep tmux_session field for backward compatibility
            if 'tmux_session' in agent:
                response["tmux_session"] = agent['tmux_session']

            return response

        except Exception as e:
            logger.warning(f"Error reading JSONL log {log_path}: {e}, falling back to tmux")
            # Fall through to tmux fallback

    # Fallback to tmux (backward compatibility)
    source = "tmux_session"

    if 'tmux_session' not in agent:
        return {
            "success": False,
            "error": f"Agent {agent_id} has no JSONL log and no tmux session",
            "agent_id": agent_id
        }

    session_name = agent['tmux_session']

    if not check_tmux_session_exists(session_name):
        return {
            "success": True,
            "agent_id": agent_id,
            "session_status": "terminated",
            "output": "" if format != "parsed" else [],
            "source": source,
            "tmux_session": session_name
        }

    # Get tmux output
    tmux_output = get_tmux_session_output(session_name)

    # Split into lines for processing
    lines = [line for line in tmux_output.split('\n') if line.strip()]

    # Apply filter if specified
    if filter:
        lines, filter_error = filter_lines_regex(lines, filter)
        if filter_error:
            return {
                "success": False,
                "error": filter_error,
                "error_type": "invalid_regex",
                "agent_id": agent_id
            }

    # Apply tail if specified
    if tail and tail > 0:
        lines = lines[-tail:]

    # Format output (tmux output is text, not JSONL)
    if format == "text" or format == "jsonl":
        output = '\n'.join(lines)
    elif format == "parsed":
        # Try to parse as JSONL, but don't fail if it's not
        parsed = []
        for line in lines:
            try:
                parsed.append(json.loads(line))
            except:
                # Not valid JSON, include as-is
                parsed.append({"text": line, "source": "tmux_unparsed"})
        output = parsed
    else:
        output = '\n'.join(lines)

    response = {
        "success": True,
        "agent_id": agent_id,
        "tmux_session": session_name,
        "session_status": "running",
        "output": output,
        "source": source
    }

    # Add metadata if requested
    if include_metadata:
        metadata = {
            "log_source": source,
            "total_lines": len(tmux_output.split('\n')),
            "returned_lines": len(lines)
        }
        if filter:
            metadata["filter_pattern"] = filter
            metadata["matched_lines"] = len(lines)
        response["metadata"] = metadata

    return response

@mcp.tool
def kill_real_agent(task_id: str, agent_id: str, reason: str = "Manual termination") -> Dict[str, Any]:
    """
    Terminate a real running agent (tmux session or cursor-agent process).
    
    Automatically detects backend type and terminates appropriately:
    - tmux backend: Kills tmux session
    - cursor backend: Kills process by PID
    
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
        # Detect backend type
        backend = agent.get('backend', AGENT_BACKEND)  # Default to configured backend (cursor-agent)
        
        if backend == 'cursor':
            # Cursor-agent: Kill by PID
            cursor_pid = agent.get('cursor_pid')
            if not cursor_pid:
                return {
                    "success": False,
                    "error": f"Agent {agent_id} is cursor backend but has no PID"
                }
            
            killed = False
            try:
                os.kill(cursor_pid, 9)  # SIGKILL
                killed = True
                logger.info(f"Killed cursor-agent process {cursor_pid} for agent {agent_id}")
            except ProcessLookupError:
                logger.warning(f"cursor-agent process {cursor_pid} not found (already dead)")
                killed = True  # Consider it killed if not found
            except PermissionError:
                logger.error(f"Permission denied to kill cursor-agent process {cursor_pid}")
                return {
                    "success": False,
                    "error": f"Permission denied to kill process {cursor_pid}"
                }
            except Exception as e:
                logger.error(f"Failed to kill cursor-agent process {cursor_pid}: {e}")
                return {
                    "success": False,
                    "error": f"Failed to kill process: {e}"
                }
            
            cleanup_result = {
                "cursor_process_killed": killed,
                "cursor_pid": cursor_pid
            }
            
        else:
            # Claude/tmux backend: Kill tmux session
            session_name = agent.get('tmux_session')

            # Perform comprehensive resource cleanup using cleanup_agent_resources
            cleanup_result = cleanup_agent_resources(
                workspace=workspace,
                agent_id=agent_id,
                agent_data=agent,
                keep_logs=True  # Archive logs instead of deleting
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
    keep_logs: bool = True
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
        if session_name:
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

                            import shutil
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

def get_minimal_coordination_info(task_id: str) -> Dict[str, Any]:
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

    return {
        "success": True,
        "task_id": task_id,
        "agent_counts": {
            "total_spawned": registry.get('total_spawned', 0),
            "active": registry.get('active_count', 0),
            "completed": registry.get('completed_count', 0)
        },
        "recent_findings": recent_findings
    }

def validate_agent_completion(workspace: str, agent_id: str, agent_type: str, message: str, registry: Dict[str, Any]) -> Dict[str, Any]:
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
        import glob
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


@mcp.tool
def update_agent_progress(task_id: str, agent_id: str, status: str, message: str, progress: int = 0) -> Dict[str, Any]:
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
    
    # Update registry
    with open(registry_path, 'r') as f:
        registry = json.load(f)
    
    # Find and update agent
    agent_found = None
    previous_status = None
    for agent in registry['agents']:
        if agent['id'] == agent_id:
            previous_status = agent.get('status')
            agent['last_update'] = datetime.now().isoformat()
            agent['status'] = status
            agent['progress'] = progress
            agent_found = agent
            break

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
    active_statuses = ['running', 'working', 'blocked']
    terminal_statuses = ['completed', 'terminated', 'error', 'failed']
    
    if previous_status in active_statuses and status in terminal_statuses:
        # Agent transitioned from active to terminal state
        registry['active_count'] = max(0, registry.get('active_count', 0) - 1)
        registry['completed_count'] = registry.get('completed_count', 0) + 1
        logger.info(f"Agent {agent_id} transitioned from {previous_status} to {status}. Active count: {registry['active_count']}")

        # AUTOMATIC RESOURCE CLEANUP: Free computing resources on terminal status
        # This ensures tmux sessions are killed, file handles closed, and prompt files cleaned up
        try:
            cleanup_result = cleanup_agent_resources(
                workspace=workspace,
                agent_id=agent_id,
                agent_data=agent_found,
                keep_logs=True  # Archive logs instead of deleting for post-mortem analysis
            )
            logger.info(f"Auto-cleanup for {agent_id}: tmux_killed={cleanup_result.get('tmux_session_killed')}, "
                       f"prompt_deleted={cleanup_result.get('prompt_file_deleted')}, "
                       f"logs_archived={cleanup_result.get('log_files_archived')}, "
                       f"no_zombies={cleanup_result.get('verified_no_zombies')}")

            # Store cleanup result in agent record for observability
            if agent_found:
                agent_found['auto_cleanup_result'] = cleanup_result
                agent_found['auto_cleanup_timestamp'] = datetime.now().isoformat()
        except Exception as e:
            logger.error(f"Auto-cleanup failed for {agent_id}: {e}")
            if agent_found:
                agent_found['auto_cleanup_error'] = str(e)
                agent_found['auto_cleanup_timestamp'] = datetime.now().isoformat()

    with open(registry_path, 'w') as f:
        json.dump(registry, f, indent=2)
    
    # UPDATE GLOBAL REGISTRY: Sync the global registry's active agent count
    try:
        workspace_base = get_workspace_base_from_task_workspace(workspace)
        global_reg_path = get_global_registry_path(workspace_base)
        if os.path.exists(global_reg_path):
            with open(global_reg_path, 'r') as f:
                global_reg = json.load(f)
            
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
                
                with open(global_reg_path, 'w') as f:
                    json.dump(global_reg, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to update global registry: {e}")
    
    # Get minimal status for coordination (prevents log bloat)
    minimal_status = get_minimal_coordination_info(task_id)

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

@mcp.tool  
def report_agent_finding(task_id: str, agent_id: str, finding_type: str, severity: str, message: str, data: dict = None) -> Dict[str, Any]:
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
    minimal_status = get_minimal_coordination_info(task_id)

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

@mcp.tool
def spawn_child_agent(task_id: str, parent_agent_id: str, child_agent_type: str, child_prompt: str) -> Dict[str, Any]:
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
    return deploy_headless_agent.fn(task_id, child_agent_type, child_prompt, parent_agent_id)

@mcp.resource("tasks://list")  
def list_real_tasks() -> str:
    """List all real tasks."""
    ensure_workspace()
    
    global_reg_path = f"{WORKSPACE_BASE}/registry/GLOBAL_REGISTRY.json"
    if not os.path.exists(global_reg_path):
        return json.dumps({"tasks": [], "message": "No tasks found"})
    
    with open(global_reg_path, 'r') as f:
        global_reg = json.load(f)
    
    return json.dumps(global_reg, indent=2)

@mcp.resource("task://{task_id}/status")
def get_task_resource(task_id: str) -> str:
    """Get task details as resource."""
    result = get_real_task_status(task_id)
    return json.dumps(result, indent=2)

@mcp.resource("task://{task_id}/progress-timeline")  
def get_task_progress_timeline(task_id: str) -> str:
    """Get comprehensive progress timeline for a task."""
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"error": f"Task {task_id} not found in any workspace location"}, indent=2)
    
    all_progress = []
    all_findings = []
    
    # Read all progress files
    progress_dir = f"{workspace}/progress"
    if os.path.exists(progress_dir):
        for file in os.listdir(progress_dir):
            if file.endswith('_progress.jsonl'):
                try:
                    with open(f"{progress_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    all_progress.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Read all findings files
    findings_dir = f"{workspace}/findings" 
    if os.path.exists(findings_dir):
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
    
    # Sort by timestamp
    all_progress.sort(key=lambda x: x.get('timestamp', ''))
    all_findings.sort(key=lambda x: x.get('timestamp', ''))
    
    # Create combined timeline
    timeline = []
    for progress in all_progress:
        timeline.append({**progress, "entry_type": "progress"})
    for finding in all_findings:
        timeline.append({**finding, "entry_type": "finding"})
    
    timeline.sort(key=lambda x: x.get('timestamp', ''))
    
    return json.dumps({
        "task_id": task_id,
        "timeline": timeline,
        "summary": {
            "total_progress_entries": len(all_progress),
            "total_findings": len(all_findings),
            "timeline_span": {
                "start": timeline[0]["timestamp"] if timeline else None,
                "end": timeline[-1]["timestamp"] if timeline else None
            },
            "agents_active": len(set(entry.get("agent_id") for entry in timeline if entry.get("agent_id")))
        }
    }, indent=2)

def startup_registry_validation():
    """
    Run registry validation on MCP server startup.

    This automatically repairs any zombie agents or count mismatches
    that may have accumulated from previous crashes or race conditions.
    """
    logger.info("Running startup registry validation...")

    try:
        # Find all task registries
        workspace_base = WORKSPACE_BASE
        registries_to_check = []

        workspace_path = Path(workspace_base)
        for task_dir in workspace_path.glob('TASK-*'):
            registry_file = task_dir / 'AGENT_REGISTRY.json'
            if registry_file.exists():
                registries_to_check.append(str(registry_file))

        if not registries_to_check:
            logger.info("No task registries found - skipping validation")
            return

        logger.info(f"Found {len(registries_to_check)} registries to validate")

        # Validate and repair each registry
        total_zombies = 0
        total_corrections = 0

        for registry_path in registries_to_check:
            try:
                result = validate_and_repair_registry(registry_path, dry_run=False)
                if result['success']:
                    if result['zombies_terminated'] > 0 or result['count_corrected']:
                        total_zombies += result['zombies_terminated']
                        if result['count_corrected']:
                            total_corrections += 1
                        logger.info(f"Repaired {registry_path}: {result['summary']}")
                else:
                    logger.warning(f"Failed to repair {registry_path}: {result.get('error')}")
            except Exception as e:
                logger.error(f"Error validating {registry_path}: {e}")
                continue

        if total_zombies > 0 or total_corrections > 0:
            logger.info(f"Startup validation complete: terminated {total_zombies} zombies, "
                       f"corrected {total_corrections} registries")
        else:
            logger.info("Startup validation complete: all registries healthy")

    except Exception as e:
        logger.error(f"Startup validation failed: {e}")
        # Don't crash the server if validation fails
        pass

if __name__ == "__main__":
    # Run startup validation before serving
    startup_registry_validation()
    mcp.run()