"""
Workspace Management Module for Claude Orchestrator

Handles workspace directory structure, task workspace discovery,
disk space checks, and write access validation.
"""

import os
import json
import shutil
import uuid
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

# WORKSPACE_BASE: Set via CLAUDE_ORCHESTRATOR_WORKSPACE env var to control where task workspaces are created
# Example: export CLAUDE_ORCHESTRATOR_WORKSPACE=/Users/yourname/Developer/Projects/yourproject/.agent-workspace
# Default: Uses ~/.claude-orchestrator/workspaces/ so it works from ANY directory
# (Previous default was os.path.abspath('.agent-workspace') which only worked when running from server directory)
def _get_default_workspace_base() -> str:
    """Get the default workspace base directory.

    Uses ~/.claude-orchestrator/workspaces/ as a global location that works from any directory.
    This solves the issue where the MCP server's CWD != client's project directory.
    """
    home = os.path.expanduser('~')
    default_workspace = os.path.join(home, '.claude-orchestrator', 'workspaces')
    os.makedirs(default_workspace, exist_ok=True)
    return default_workspace

WORKSPACE_BASE = os.getenv('CLAUDE_ORCHESTRATOR_WORKSPACE', _get_default_workspace_base())
DEFAULT_MAX_CONCURRENT = int(os.getenv('CLAUDE_ORCHESTRATOR_MAX_CONCURRENT', '20'))

# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Constants
    'WORKSPACE_BASE',
    'DEFAULT_MAX_CONCURRENT',
    # Functions
    'find_task_workspace',
    'get_workspace_base_from_task_workspace',
    'get_global_registry_path',
    'ensure_global_registry',
    'ensure_workspace',
    'check_disk_space',
    'test_write_access',
    'resolve_workspace_variables',
]


# ============================================================================
# WORKSPACE PATH FUNCTIONS
# ============================================================================

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
        WORKSPACE_BASE,  # Default: ~/.claude-orchestrator/workspaces/
    ]

    # Also check the global home directory location (for tasks created before fix)
    home = os.path.expanduser('~')
    global_workspace = os.path.join(home, '.claude-orchestrator', 'workspaces')
    if global_workspace not in potential_registry_locations and os.path.isdir(global_workspace):
        potential_registry_locations.append(global_workspace)

    # Also check common project locations for backwards compatibility
    # with tasks created using client_cwd or old default behavior
    # NOTE: os.getcwd() returns MCP server's directory, not client's project
    # This is a best-effort fallback that may not find tasks from other projects
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


# ============================================================================
# WORKSPACE INITIALIZATION
# ============================================================================

def ensure_global_registry(workspace_base: str = None):
    """
    Ensure global registry exists at the specified workspace base.

    Handles edge cases:
    - File doesn't exist -> creates new
    - File is empty (0 bytes) -> recreates
    - File has invalid JSON -> recreates with backup

    Args:
        workspace_base: Optional workspace base directory. If not provided, uses WORKSPACE_BASE.
    """
    if workspace_base is None:
        workspace_base = WORKSPACE_BASE

    os.makedirs(f"{workspace_base}/registry", exist_ok=True)
    global_reg_path = get_global_registry_path(workspace_base)

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

    needs_creation = False

    if not os.path.exists(global_reg_path):
        needs_creation = True
        logger.info(f"Global registry does not exist, creating: {global_reg_path}")
    elif os.path.getsize(global_reg_path) == 0:
        # File exists but is empty (corrupt)
        needs_creation = True
        logger.warning(f"Global registry is empty (corrupt), recreating: {global_reg_path}")
    else:
        # File exists and has content - verify it's valid JSON
        try:
            with open(global_reg_path, 'r') as f:
                json.load(f)
        except json.JSONDecodeError as e:
            # Invalid JSON - backup and recreate
            backup_path = f"{global_reg_path}.corrupt.{datetime.now().strftime('%Y%m%d%H%M%S')}"
            try:
                shutil.copy2(global_reg_path, backup_path)
                logger.warning(f"Global registry has invalid JSON, backed up to {backup_path}")
            except Exception as backup_error:
                logger.error(f"Failed to backup corrupt registry: {backup_error}")
            needs_creation = True
            logger.warning(f"Global registry has invalid JSON, recreating: {global_reg_path}")

    if needs_creation:
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


# ============================================================================
# PRE-FLIGHT CHECKS
# ============================================================================

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
# WORKSPACE VARIABLE RESOLUTION
# ============================================================================

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
    import re

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
        r'\$WORKSPACE_FOLDER',          # $WORKSPACE_FOLDER
        r'\{workspaceFolder\}',         # {workspaceFolder}
    ]

    resolved = path
    for pattern in patterns:
        resolved = re.sub(pattern, actual_workspace, resolved, flags=re.IGNORECASE)

    # Log if resolution occurred
    if resolved != path:
        logger.debug(f"Resolved workspace variable: {path} -> {resolved}")

    return resolved
