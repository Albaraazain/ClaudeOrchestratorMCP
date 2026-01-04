"""
Registry Operations Module for Claude Orchestrator.

This module handles all registry-related operations including:
- File locking for atomic registry access
- Agent registration and status updates
- Global registry management

Author: Claude Code Orchestrator Project
License: MIT
"""

import json
import os
import fcntl
import errno
import time
import logging
import uuid
import shutil
from enum import Enum
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Callable

# Re-export configuration variables - these will be set by the main server
WORKSPACE_BASE: str = ""
DEFAULT_MAX_CONCURRENT: int = 20

logger = logging.getLogger(__name__)


# ============================================================================
# VERSION LOCKING EXCEPTIONS
# ============================================================================

class StaleVersionError(Exception):
    """
    Exception raised when an operation is attempted with an outdated version number.

    This implements optimistic locking - the operation was based on stale state
    that has since been modified by another process.

    Attributes:
        expected: The version number the caller expected
        actual: The current version number in the registry
    """

    def __init__(self, expected: int, actual: int):
        self.expected = expected
        self.actual = actual
        super().__init__(f"Version mismatch: expected {expected}, got {actual}")


# ============================================================================
# PHASE STATUS ENUM (8-state machine)
# ============================================================================

class PhaseStatus(str, Enum):
    """
    Phase status enum defining the 8 possible states in the phase lifecycle.

    State Machine Flow:
        PENDING → ACTIVE → AWAITING_REVIEW → UNDER_REVIEW → APPROVED → (next phase)
                                                        ↓
                                                    REJECTED → REVISING → AWAITING_REVIEW

        Any state can transition to ESCALATED when human intervention is needed.

    States:
        PENDING: Phase not yet started, waiting for previous phase to complete
        ACTIVE: Currently executing - agents are working on this phase
        AWAITING_REVIEW: All phase work done, waiting for review to be scheduled
        UNDER_REVIEW: Review agent has been spawned and is actively reviewing
        APPROVED: Review passed, phase is complete and next phase can start
        REJECTED: Review failed, phase needs revision (will transition to REVISING)
        REVISING: Making fixes after rejection, agents working on corrections
        ESCALATED: Requires human intervention - automated process cannot proceed
    """
    PENDING = "pending"
    ACTIVE = "active"
    AWAITING_REVIEW = "awaiting_review"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVISING = "revising"
    ESCALATED = "escalated"


# Valid phase status transitions (from_status -> list of valid to_statuses)
VALID_PHASE_TRANSITIONS: Dict[PhaseStatus, List[PhaseStatus]] = {
    PhaseStatus.PENDING: [PhaseStatus.ACTIVE, PhaseStatus.ESCALATED],
    PhaseStatus.ACTIVE: [PhaseStatus.AWAITING_REVIEW, PhaseStatus.ESCALATED],
    PhaseStatus.AWAITING_REVIEW: [PhaseStatus.UNDER_REVIEW, PhaseStatus.ESCALATED],
    PhaseStatus.UNDER_REVIEW: [PhaseStatus.APPROVED, PhaseStatus.REJECTED, PhaseStatus.ESCALATED],
    PhaseStatus.APPROVED: [],  # Terminal state - no transitions allowed
    PhaseStatus.REJECTED: [PhaseStatus.REVISING, PhaseStatus.ESCALATED],
    PhaseStatus.REVISING: [PhaseStatus.AWAITING_REVIEW, PhaseStatus.ESCALATED],
    PhaseStatus.ESCALATED: [PhaseStatus.PENDING, PhaseStatus.ACTIVE, PhaseStatus.REVISING],  # Human can reset
}


__all__ = [
    # Version Locking
    'StaleVersionError',
    'atomic_check_version',
    'version_guarded_update',
    # Phase Schema
    'PhaseStatus',
    'VALID_PHASE_TRANSITIONS',
    'create_phase',
    'get_phase_by_id',
    'get_current_phase',
    'get_next_phase',
    'is_valid_phase_transition',
    # Phase-Agent Binding
    'validate_agent_phase',
    'get_phase_agents',
    'mark_phase_agents_completed',
    # Phase Transition Functions (MIT-002)
    'AGENT_TERMINAL_STATUSES',
    'AGENT_ACTIVE_STATUSES',
    'check_phase_completion',
    'atomic_check_and_transition_phase',
    'try_advance_to_review',
    'advance_phase',
    'get_previous_phase_handover',
    # Registry Operations
    'LockedRegistryFile',
    'atomic_add_agent',
    'atomic_update_agent_status',
    'atomic_increment_counts',
    'atomic_decrement_active_count',
    'atomic_mark_agents_completed',
    'get_global_registry_path',
    'read_registry_with_lock',
    'write_registry_with_lock',
    'ensure_global_registry',
    'configure_registry',
]


def configure_registry(workspace_base: str, max_concurrent: int = 20) -> None:
    """
    Configure registry module with workspace settings.

    This must be called before using registry functions.

    Args:
        workspace_base: Base directory for workspaces
        max_concurrent: Maximum concurrent agents allowed
    """
    global WORKSPACE_BASE, DEFAULT_MAX_CONCURRENT
    WORKSPACE_BASE = workspace_base
    DEFAULT_MAX_CONCURRENT = max_concurrent
    logger.debug(f"Registry configured: workspace={workspace_base}, max_concurrent={max_concurrent}")


# ============================================================================
# PHASE SCHEMA HELPER FUNCTIONS
# ============================================================================

def create_phase(name: str, order: int) -> Dict[str, Any]:
    """
    Create a new phase structure with all required fields.

    Args:
        name: Human-readable name (e.g., "Investigation", "Implementation")
        order: 1-based order of this phase in the sequence

    Returns:
        Dict with phase structure ready to be added to registry['phases']

    Example:
        >>> phase = create_phase("Investigation", 1)
        >>> phase
        {
            'id': 'phase-abc123...',
            'name': 'Investigation',
            'order': 1,
            'status': 'pending',
            'started_at': None,
            'completed_at': None,
            'review': None
        }
    """
    return {
        "id": f"phase-{uuid.uuid4().hex[:12]}",
        "name": name,
        "order": order,
        "status": PhaseStatus.PENDING.value,
        "started_at": None,
        "completed_at": None,
        "review": None
    }


def get_phase_by_id(registry: Dict[str, Any], phase_id: str) -> Optional[Dict[str, Any]]:
    """
    Find a phase by its ID in the registry.

    Args:
        registry: Registry dict (must contain 'phases' array)
        phase_id: Phase ID to search for (e.g., 'phase-abc123')

    Returns:
        Phase dict if found, None otherwise

    Note:
        Returns the actual dict from registry, so modifications will persist
        if registry is later written back to file.
    """
    phases = registry.get("phases", [])
    for phase in phases:
        if phase.get("id") == phase_id:
            return phase
    logger.debug(f"Phase {phase_id} not found in registry")
    return None


def get_current_phase(registry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Get the currently active phase from registry.

    Uses the 'current_phase_id' field to efficiently locate the active phase
    without scanning the entire phases array.

    Args:
        registry: Registry dict (must contain 'current_phase_id' and 'phases')

    Returns:
        Current phase dict if found, None if no current phase is set

    Note:
        If current_phase_id points to a non-existent phase (data corruption),
        returns None and logs a warning.
    """
    current_phase_id = registry.get("current_phase_id")
    if not current_phase_id:
        logger.debug("No current_phase_id set in registry")
        return None

    phase = get_phase_by_id(registry, current_phase_id)
    if not phase:
        logger.warning(
            f"current_phase_id '{current_phase_id}' points to non-existent phase. "
            "Registry may be corrupted."
        )
    return phase


def get_next_phase(registry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Get the next phase after the current one, based on order.

    Finds the phase with the lowest order that is greater than
    the current phase's order. Returns None if current phase is
    the last one or if no current phase exists.

    Args:
        registry: Registry dict (must contain 'phases' and 'current_phase_id')

    Returns:
        Next phase dict if exists, None if current is last or no current phase

    Example:
        If current phase has order=2, and phases have orders [1, 2, 3, 4],
        returns the phase with order=3.
    """
    current = get_current_phase(registry)
    if not current:
        # No current phase - return first pending phase
        phases = registry.get("phases", [])
        pending_phases = [
            p for p in phases
            if p.get("status") == PhaseStatus.PENDING.value
        ]
        if pending_phases:
            # Return phase with lowest order
            pending_phases.sort(key=lambda p: p.get("order", float('inf')))
            return pending_phases[0]
        return None

    current_order = current.get("order", 0)
    phases = registry.get("phases", [])

    # Find phases with higher order
    next_phases = [p for p in phases if p.get("order", 0) > current_order]

    if not next_phases:
        logger.debug(f"No phase after order {current_order}")
        return None

    # Return the one with smallest order (immediately next)
    next_phases.sort(key=lambda p: p.get("order", float('inf')))
    return next_phases[0]


def is_valid_phase_transition(
    from_status: str,
    to_status: str
) -> bool:
    """
    Check if a phase status transition is valid according to the state machine.

    Args:
        from_status: Current status (as string value, e.g., 'pending')
        to_status: Target status (as string value, e.g., 'active')

    Returns:
        True if transition is valid, False otherwise

    Example:
        >>> is_valid_phase_transition('pending', 'active')
        True
        >>> is_valid_phase_transition('pending', 'approved')
        False
    """
    try:
        from_enum = PhaseStatus(from_status)
        to_enum = PhaseStatus(to_status)
    except ValueError:
        logger.warning(f"Invalid phase status: from={from_status}, to={to_status}")
        return False

    valid_targets = VALID_PHASE_TRANSITIONS.get(from_enum, [])
    return to_enum in valid_targets


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

    Version Tracking Usage:
        with LockedRegistryFile(registry_path) as (registry, f):
            # Get initial version when lock acquired
            initial_version = registry.get('version', 0)

            # Modify registry...
            registry['agents'].append(agent_data)

            # Increment version before write (CRITICAL for optimistic locking)
            registry['version'] = initial_version + 1

            f.seek(0)
            f.write(json.dumps(registry, indent=2))
            f.truncate()

    Features:
    - Exclusive lock (LOCK_EX) blocks other processes until released
    - Automatic unlock on context exit (even if exception occurs)
    - Handles lock acquisition failures with retries
    - Thread-safe and process-safe
    - Captures initial version on entry for optimistic locking checks
    - version_on_entry property exposes the version read when lock was acquired
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
        self._version_on_entry: int = 0

    @property
    def version_on_entry(self) -> int:
        """
        Get the version number that was read when the lock was acquired.

        This is useful for callers who need to know the version for
        optimistic locking without reading the registry again.

        Returns:
            The version number at lock acquisition time (0 if no version field exists)
        """
        return self._version_on_entry

    def __enter__(self) -> Tuple[Dict[str, Any], Any]:
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

            # Capture version on entry for optimistic locking
            self._version_on_entry = self.registry.get('version', 0)

            logger.debug(
                f"Registry locked and loaded: {self.path} (version={self._version_on_entry})"
            )
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
# VERSION-BASED OPTIMISTIC LOCKING OPERATIONS
# ============================================================================

def atomic_check_version(registry_path: str, expected_version: int) -> Tuple[bool, int]:
    """
    Atomically check if registry version matches expected value.

    This function acquires a lock, reads the current version, and compares
    it against the expected version. Used for pre-flight checks before
    making decisions based on registry state.

    Args:
        registry_path: Path to the registry JSON file
        expected_version: The version number the caller expects

    Returns:
        Tuple of (matches: bool, current_version: int)
        - matches is True if current version equals expected_version
        - current_version is the actual version in the registry

    Raises:
        TimeoutError: If lock cannot be acquired
        FileNotFoundError: If registry doesn't exist

    Example:
        # Read registry, make decision, then verify before acting
        registry = read_registry_with_lock(registry_path)
        expected = registry.get('version', 0)
        # ... some logic that takes time ...
        matches, current = atomic_check_version(registry_path, expected)
        if not matches:
            # Registry was modified - re-read and retry decision
            pass
    """
    with LockedRegistryFile(registry_path) as (registry, f):
        current_version = registry.get('version', 0)
        matches = (current_version == expected_version)

        logger.debug(
            f"Version check: expected={expected_version}, "
            f"current={current_version}, matches={matches}"
        )

        return matches, current_version


def version_guarded_update(
    registry_path: str,
    expected_version: int,
    updater: Callable[[Dict[str, Any]], Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Execute a registry update only if the version matches expected value.

    This implements optimistic locking - the update will only proceed if no
    other process has modified the registry since we read it. The version
    is automatically incremented on successful update.

    Args:
        registry_path: Path to the registry JSON file
        expected_version: The version the caller expects (from their last read)
        updater: Callable that takes registry dict and returns modified dict.
                 This function is called INSIDE the lock, so it should be fast.
                 The updater should NOT modify the 'version' field - that's
                 handled automatically.

    Returns:
        Dict with:
        - success: bool - True if update was applied
        - new_version: int - The new version after update (if success)
        - error: str - Error message (if not success)
        - current_version: int - The actual version when checked

    Raises:
        TimeoutError: If lock cannot be acquired
        FileNotFoundError: If registry doesn't exist

    Example:
        def add_agent_to_registry(reg: dict) -> dict:
            reg['agents'].append(new_agent)
            reg['active_count'] += 1
            return reg

        result = version_guarded_update(
            registry_path,
            expected_version=5,
            updater=add_agent_to_registry
        )
        if result['success']:
            print(f"Updated to version {result['new_version']}")
        else:
            print(f"Stale: expected 5, got {result['current_version']}")
    """
    with LockedRegistryFile(registry_path) as (registry, f):
        current_version = registry.get('version', 0)

        # Check version match
        if current_version != expected_version:
            logger.warning(
                f"Version guard failed: expected={expected_version}, "
                f"current={current_version}"
            )
            return {
                'success': False,
                'error': 'STALE_VERSION',
                'expected_version': expected_version,
                'current_version': current_version
            }

        # Version matches - apply the update
        try:
            updated_registry = updater(registry)
        except Exception as e:
            logger.error(f"Updater function raised exception: {e}")
            return {
                'success': False,
                'error': f'UPDATER_ERROR: {str(e)}',
                'current_version': current_version
            }

        # Increment version after successful update
        new_version = current_version + 1
        updated_registry['version'] = new_version

        # Write back atomically
        f.seek(0)
        f.write(json.dumps(updated_registry, indent=2))
        f.truncate()

        logger.info(
            f"Version-guarded update succeeded: {current_version} -> {new_version}"
        )

        return {
            'success': True,
            'new_version': new_version,
            'previous_version': current_version
        }


# ============================================================================
# ATOMIC REGISTRY OPERATIONS
# ============================================================================

def atomic_add_agent(
    registry_path: str,
    agent_data: Dict[str, Any],
    parent: str,
    phase_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Atomically add agent to registry with proper count updates.

    Args:
        registry_path: Path to task registry JSON
        agent_data: Agent metadata dict to append
        parent: Parent agent ID for hierarchy tracking
        phase_id: Optional phase ID to bind this agent to (MIT-003 phase binding)

    Returns:
        Dict with:
        - success: bool - Always True on successful completion
        - version: int - The new registry version after this update
        - agent_id: str - The ID of the added agent
        - total_spawned: int - Total agents spawned after update
        - active_count: int - Active agents after update
        - phase_id: str or None - The phase this agent is bound to

    Raises:
        TimeoutError: If lock cannot be acquired
        FileNotFoundError: If registry doesn't exist
        ValueError: If phase_id is specified but phase doesn't exist
    """
    with LockedRegistryFile(registry_path) as (registry, f):
        # Validate and bind phase_id if provided (MIT-003)
        if phase_id is not None:
            phases = registry.get('phases', [])
            phase_exists = any(p.get('id') == phase_id for p in phases)
            if not phase_exists:
                raise ValueError(f"Phase '{phase_id}' not found in registry. Cannot bind agent.")
            agent_data['phase_id'] = phase_id
            logger.debug(f"Agent {agent_data.get('id')} bound to phase {phase_id}")

        # Add agent to list
        registry['agents'].append(agent_data)

        # Increment counters
        registry['total_spawned'] += 1
        registry['active_count'] += 1

        # Update hierarchy
        if parent not in registry['agent_hierarchy']:
            registry['agent_hierarchy'][parent] = []
        registry['agent_hierarchy'][parent].append(agent_data['id'])

        # Increment version for optimistic locking
        current_version = registry.get('version', 0)
        new_version = current_version + 1
        registry['version'] = new_version

        # Write back to file
        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.info(
            f"Atomically added agent {agent_data['id']} to registry. "
            f"Total: {registry['total_spawned']}, Active: {registry['active_count']}, "
            f"Version: {new_version}, Phase: {phase_id or 'unbound'}"
        )

        return {
            'success': True,
            'version': new_version,
            'agent_id': agent_data['id'],
            'total_spawned': registry['total_spawned'],
            'active_count': registry['active_count'],
            'phase_id': phase_id
        }


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
        Dict with:
        - success: bool - True on successful update
        - version: int - The new registry version after this update
        - agent_id: str - The agent ID that was updated
        - previous_status: str - The status before update
        - new_status: str - The status after update
        - active_count: int - Active agents after update

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

        # Increment version for optimistic locking
        current_version = registry.get('version', 0)
        new_version = current_version + 1
        registry['version'] = new_version

        # Write back
        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.info(
            f"Atomically updated agent {agent_id}: {previous_status} -> {status}. "
            f"Active: {registry['active_count']}, Version: {new_version}"
        )

        return {
            'success': True,
            'version': new_version,
            'agent_id': agent_id,
            'previous_status': previous_status,
            'new_status': status,
            'active_count': registry['active_count']
        }


def atomic_increment_counts(registry_path: str, active: int = 0, total: int = 0) -> Dict[str, Any]:
    """
    Atomically increment registry counters.

    Args:
        registry_path: Path to registry JSON
        active: Amount to increment active_count by
        total: Amount to increment total_spawned by

    Returns:
        Dict with:
        - success: bool - Always True on completion
        - version: int - The new registry version after this update
        - active_count: int - Active count after increment
        - total_spawned: int - Total spawned after increment
    """
    with LockedRegistryFile(registry_path) as (registry, f):
        registry['active_count'] = registry.get('active_count', 0) + active
        registry['total_spawned'] = registry.get('total_spawned', 0) + total

        # Increment version for optimistic locking
        current_version = registry.get('version', 0)
        new_version = current_version + 1
        registry['version'] = new_version

        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.debug(
            f"Atomically incremented counts: +{active} active, +{total} total, "
            f"version: {new_version}"
        )

        return {
            'success': True,
            'version': new_version,
            'active_count': registry['active_count'],
            'total_spawned': registry['total_spawned']
        }


def atomic_decrement_active_count(registry_path: str, amount: int = 1) -> Dict[str, Any]:
    """
    Atomically decrement active agent count.

    Args:
        registry_path: Path to registry JSON
        amount: Amount to decrement by (default 1)

    Returns:
        Dict with:
        - success: bool - Always True on completion
        - version: int - The new registry version after this update
        - active_count: int - Active count after decrement
    """
    with LockedRegistryFile(registry_path) as (registry, f):
        registry['active_count'] = max(0, registry.get('active_count', 0) - amount)

        # Increment version for optimistic locking
        current_version = registry.get('version', 0)
        new_version = current_version + 1
        registry['version'] = new_version

        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.debug(
            f"Atomically decremented active_count by {amount}, version: {new_version}"
        )

        return {
            'success': True,
            'version': new_version,
            'active_count': registry['active_count']
        }


def atomic_mark_agents_completed(
    registry_path: str,
    agent_ids: List[str]
) -> Dict[str, Any]:
    """
    Atomically mark multiple agents as completed (for auto-cleanup).

    Args:
        registry_path: Path to task registry JSON
        agent_ids: List of agent IDs to mark as completed

    Returns:
        Dict with:
        - success: bool - True on completion
        - version: int - The new registry version after this update
        - marked_count: int - Number of agents actually marked as completed
        - active_count: int - Active count after update
        - completed_count: int - Completed count after update
    """
    if not agent_ids:
        return {
            'success': True,
            'version': 0,  # No change made
            'marked_count': 0,
            'active_count': 0,
            'completed_count': 0
        }

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

        # Increment version for optimistic locking
        current_version = registry.get('version', 0)
        new_version = current_version + 1
        registry['version'] = new_version

        # Write back
        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.info(
            f"Atomically marked {marked_count} agents as completed. "
            f"Active: {registry['active_count']}, Version: {new_version}"
        )

        return {
            'success': True,
            'version': new_version,
            'marked_count': marked_count,
            'active_count': registry['active_count'],
            'completed_count': registry['completed_count']
        }


# ============================================================================
# GLOBAL REGISTRY OPERATIONS
# ============================================================================

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


def ensure_global_registry(workspace_base: str = None) -> None:
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


# ============================================================================
# PHASE-AGENT BINDING OPERATIONS
# ============================================================================

def validate_agent_phase(registry: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
    """
    Validate that an agent can still operate (is bound to the current active phase).

    This function checks if an agent's phase binding is still valid. An agent
    should only be able to perform work if:
    1. It has no phase_id (unbound agent, legacy behavior)
    2. Its phase_id matches the current active phase
    3. Its phase_id matches a phase in REVISING state (allowed to continue work)

    Args:
        registry: The loaded registry dictionary
        agent_id: Agent ID to validate

    Returns:
        Dict with:
        - valid: bool - True if agent can continue operating
        - error: str - Error message if not valid (None if valid)
        - agent_phase: str or None - The phase ID the agent is bound to
        - current_phase: str or None - The current active phase ID
        - reason: str - Explanation of validation result
    """
    # Find agent
    agent = None
    for a in registry.get('agents', []):
        if a.get('id') == agent_id:
            agent = a
            break

    if not agent:
        return {
            'valid': False,
            'error': f'Agent {agent_id} not found in registry',
            'agent_phase': None,
            'current_phase': None,
            'reason': 'agent_not_found'
        }

    agent_phase_id = agent.get('phase_id')

    # Unbound agents (no phase_id) are always valid - legacy compatibility
    if agent_phase_id is None:
        return {
            'valid': True,
            'error': None,
            'agent_phase': None,
            'current_phase': None,
            'reason': 'unbound_agent'
        }

    # Find current active phase
    phases = registry.get('phases', [])
    current_phase = None
    agent_phase = None

    for phase in phases:
        if phase.get('status') in ['active', 'revising']:
            current_phase = phase
        if phase.get('id') == agent_phase_id:
            agent_phase = phase

    if not agent_phase:
        return {
            'valid': False,
            'error': f'Agent bound to non-existent phase {agent_phase_id}',
            'agent_phase': agent_phase_id,
            'current_phase': current_phase.get('id') if current_phase else None,
            'reason': 'phase_not_found'
        }

    # Check if agent's phase is current or in revising state
    phase_status = agent_phase.get('status')

    if phase_status in ['active', 'revising']:
        return {
            'valid': True,
            'error': None,
            'agent_phase': agent_phase_id,
            'current_phase': current_phase.get('id') if current_phase else None,
            'reason': 'phase_active'
        }

    # Agent's phase is not active - check if it was completed
    if phase_status == 'approved':
        return {
            'valid': False,
            'error': f'Agent phase {agent_phase_id} has been approved - agent work is complete',
            'agent_phase': agent_phase_id,
            'current_phase': current_phase.get('id') if current_phase else None,
            'reason': 'phase_completed'
        }

    return {
        'valid': False,
        'error': f'Agent phase {agent_phase_id} is in state {phase_status} - cannot operate',
        'agent_phase': agent_phase_id,
        'current_phase': current_phase.get('id') if current_phase else None,
        'reason': f'phase_state_{phase_status}'
    }


def get_phase_agents(registry: Dict[str, Any], phase_id: str) -> List[Dict[str, Any]]:
    """
    Get all agents bound to a specific phase.

    Args:
        registry: The loaded registry dictionary
        phase_id: Phase ID to get agents for

    Returns:
        List of agent data dicts that are bound to the specified phase.
        Empty list if no agents are bound to this phase.
    """
    phase_agents = []

    for agent in registry.get('agents', []):
        if agent.get('phase_id') == phase_id:
            phase_agents.append(agent)

    logger.debug(f"Found {len(phase_agents)} agents bound to phase {phase_id}")
    return phase_agents


def mark_phase_agents_completed(
    registry_path: str,
    phase_id: str
) -> Dict[str, Any]:
    """
    Mark all agents in a phase as 'phase_completed' status.

    Used when a phase transitions to APPROVED. All agents bound to that phase
    should be marked as 'phase_completed' to indicate their work is done as
    part of phase completion (different from individual agent completion).

    Args:
        registry_path: Path to the registry JSON file
        phase_id: Phase ID whose agents should be marked

    Returns:
        Dict with:
        - success: bool - True if operation completed
        - phase_id: str - The phase that was processed
        - agents_marked: int - Number of agents marked as phase_completed
        - agent_ids: List[str] - IDs of agents that were marked
        - version: int - New registry version after update

    Raises:
        TimeoutError: If lock cannot be acquired
        FileNotFoundError: If registry doesn't exist
    """
    with LockedRegistryFile(registry_path) as (registry, f):
        marked_agents = []
        completed_at = datetime.now().isoformat()

        for agent in registry.get('agents', []):
            if agent.get('phase_id') == phase_id:
                # Only mark if agent is still in an active state
                if agent.get('status') in ['running', 'working', 'blocked']:
                    agent['status'] = 'phase_completed'
                    agent['phase_completed_at'] = completed_at
                    marked_agents.append(agent['id'])
                    logger.debug(f"Marked agent {agent['id']} as phase_completed")

        # Update active count
        if marked_agents:
            registry['active_count'] = max(
                0,
                registry.get('active_count', 0) - len(marked_agents)
            )
            registry['completed_count'] = registry.get('completed_count', 0) + len(marked_agents)

        # Increment version
        current_version = registry.get('version', 0)
        new_version = current_version + 1
        registry['version'] = new_version

        # Write back
        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.info(
            f"Marked {len(marked_agents)} agents as phase_completed for phase {phase_id}. "
            f"Active: {registry['active_count']}, Version: {new_version}"
        )

        return {
            'success': True,
            'phase_id': phase_id,
            'agents_marked': len(marked_agents),
            'agent_ids': marked_agents,
            'version': new_version
        }


# ============================================================================
# PHASE TRANSITION FUNCTIONS (MIT-002: Atomic Phase Transitions)
# ============================================================================
#
# These functions implement atomic phase transitions per RACE_CONDITION_CATALOG.md.
# Key principle: Decision AND state change happen inside the same lock acquisition.
#

# Terminal agent statuses (agent work is done)
AGENT_TERMINAL_STATUSES = {'completed', 'failed', 'error', 'terminated', 'phase_completed'}

# Active agent statuses (agent still working)
AGENT_ACTIVE_STATUSES = {'running', 'working', 'blocked'}


def check_phase_completion(registry: Dict[str, Any], phase_id: str) -> Dict[str, Any]:
    """
    Check if all agents in a phase are in terminal state.

    This function inspects the registry to determine if all agents bound to
    a specific phase have completed their work (reached terminal status).
    Terminal states: completed, failed, error, terminated, phase_completed

    Args:
        registry: Registry dict (already loaded, typically within a lock)
        phase_id: Phase ID to check completion for

    Returns:
        Dict with completion status:
            {
                "all_complete": bool,       # True if all agents done
                "total_agents": int,        # Number of agents in phase
                "completed_agents": int,    # Number of agents in terminal state
                "pending_agents": List[str],  # Agent IDs still working
                "reason": str               # Human-readable explanation
            }
    """
    phase_agents = [
        a for a in registry.get('agents', [])
        if a.get('phase_id') == phase_id
    ]

    total = len(phase_agents)
    pending = []
    completed_count = 0

    for agent in phase_agents:
        status = agent.get('status', '')
        if status in AGENT_TERMINAL_STATUSES:
            completed_count += 1
        else:
            pending.append(agent.get('id', 'unknown'))

    all_complete = (total > 0 and completed_count == total)

    if total == 0:
        reason = "No agents in phase"
    elif all_complete:
        reason = f"All {total} agents completed"
    else:
        reason = f"{completed_count}/{total} agents complete, {len(pending)} still working"

    logger.debug(f"Phase completion check for {phase_id}: {reason}")

    return {
        "all_complete": all_complete,
        "total_agents": total,
        "completed_agents": completed_count,
        "pending_agents": pending,
        "reason": reason
    }


def atomic_check_and_transition_phase(
    registry_path: str,
    phase_id: str,
    expected_status: str,
    new_status: str,
    additional_updates: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Atomically check phase status and transition if it matches expected status.

    This is the core atomic transition function per MIT-002 in RACE_CONDITION_CATALOG.md.
    The decision AND state change happen INSIDE the lock to prevent race conditions.

    This prevents race conditions where:
    - Agent A completes while we're checking phase completion
    - Review submission happens based on stale state
    - Multiple orchestrators try to advance the same phase

    Args:
        registry_path: Path to registry file
        phase_id: Phase to transition
        expected_status: Status the phase must currently be in
        new_status: Status to transition to
        additional_updates: Optional dict to merge into phase (e.g., completed_at, review)

    Returns:
        Dict with result:
            {
                "success": bool,           # True if no errors occurred
                "transitioned": bool,      # True if transition actually happened
                "reason": str,             # Explanation of result
                "old_status": str,         # Status before (if phase found)
                "new_version": int         # Registry version after update
            }

    Raises:
        FileNotFoundError: If registry file doesn't exist
        TimeoutError: If lock cannot be acquired
    """
    logger.debug(f"Atomic phase transition: {phase_id} from {expected_status} to {new_status}")

    with LockedRegistryFile(registry_path) as (registry, f):
        # Find the phase
        phases = registry.get('phases', [])
        phase = None
        for p in phases:
            if p.get('id') == phase_id:
                phase = p
                break

        if phase is None:
            logger.warning(f"Phase {phase_id} not found in registry")
            return {
                "success": False,
                "transitioned": False,
                "reason": f"Phase {phase_id} not found",
                "old_status": None,
                "new_version": registry.get('version', 0)
            }

        old_status = phase.get('status', '')

        # Check if current status matches expected
        if old_status != expected_status:
            logger.info(
                f"Phase transition skipped: expected {expected_status}, "
                f"found {old_status}"
            )
            return {
                "success": True,  # Not an error, just a mismatch
                "transitioned": False,
                "reason": f"Status mismatch: expected '{expected_status}', found '{old_status}'",
                "old_status": old_status,
                "new_version": registry.get('version', 0)
            }

        # Validate the transition
        if not is_valid_phase_transition(old_status, new_status):
            logger.warning(
                f"Invalid phase transition attempted: {old_status} -> {new_status}"
            )
            return {
                "success": False,
                "transitioned": False,
                "reason": f"Invalid transition: '{old_status}' -> '{new_status}'",
                "old_status": old_status,
                "new_version": registry.get('version', 0)
            }

        # Perform the transition - INSIDE the lock
        phase['status'] = new_status
        phase['status_updated_at'] = datetime.now().isoformat()

        # Apply additional updates if provided
        if additional_updates:
            for key, value in additional_updates.items():
                phase[key] = value

        # Increment version for optimistic locking
        registry['version'] = registry.get('version', 0) + 1
        new_version = registry['version']

        # Write back atomically
        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.info(
            f"Phase {phase_id} transitioned: {old_status} -> {new_status} "
            f"(version={new_version})"
        )

        return {
            "success": True,
            "transitioned": True,
            "reason": f"Transitioned from '{old_status}' to '{new_status}'",
            "old_status": old_status,
            "new_version": new_version
        }


def try_advance_to_review(
    registry_path: str,
    phase_id: str,
    deploy_review_agent_fn: Optional[Callable[[str, str, str], Any]] = None,
    task_workspace: Optional[str] = None
) -> Dict[str, Any]:
    """
    Attempt to advance a phase from ACTIVE to AWAITING_REVIEW.

    This is a convenience function that combines:
    1. Check if all phase agents are complete
    2. If so, atomically transition to AWAITING_REVIEW
    3. If deploy_review_agent_fn is provided, trigger review agent deployment

    The check AND transition happen in the same lock to prevent race conditions
    (e.g., agent completing while we're checking phase completion).

    Args:
        registry_path: Path to registry file
        phase_id: Phase to attempt advancing
        deploy_review_agent_fn: Optional callback to deploy a review agent.
                               Called with (task_id, phase_id, workspace) when
                               phase successfully transitions to AWAITING_REVIEW.
                               The callback should spawn the review agent and return
                               deployment info (agent_id, review_id, etc).
        task_workspace: Optional workspace path, passed to deploy_review_agent_fn.
                       Required if deploy_review_agent_fn is provided.

    Returns:
        Dict with result:
            {
                "success": bool,           # True if no errors
                "advanced": bool,          # True if actually advanced to review
                "completion_check": Dict,  # Result of check_phase_completion()
                "reason": str,             # Explanation
                "new_version": int,        # Registry version after update (if advanced)
                "review_triggered": bool,  # True if review agent was triggered
                "review_deployment": Any   # Result from deploy_review_agent_fn (if called)
            }
    """
    logger.debug(f"Attempting to advance phase {phase_id} to review")

    with LockedRegistryFile(registry_path) as (registry, f):
        # First, find the phase and check its status
        phases = registry.get('phases', [])
        phase = None
        for p in phases:
            if p.get('id') == phase_id:
                phase = p
                break

        if phase is None:
            return {
                "success": False,
                "advanced": False,
                "completion_check": None,
                "reason": f"Phase {phase_id} not found",
                "new_version": registry.get('version', 0),
                "review_triggered": False,
                "review_deployment": None
            }

        current_status = phase.get('status', '')

        # Must be in ACTIVE status to advance to review
        if current_status != PhaseStatus.ACTIVE.value:
            return {
                "success": True,
                "advanced": False,
                "completion_check": None,
                "reason": f"Phase not in ACTIVE status (current: {current_status})",
                "new_version": registry.get('version', 0),
                "review_triggered": False,
                "review_deployment": None
            }

        # Check if all agents are complete - INSIDE the lock
        completion = check_phase_completion(registry, phase_id)

        if not completion['all_complete']:
            return {
                "success": True,
                "advanced": False,
                "completion_check": completion,
                "reason": completion['reason'],
                "new_version": registry.get('version', 0),
                "review_triggered": False,
                "review_deployment": None
            }

        # All agents complete - transition to AWAITING_REVIEW
        phase['status'] = PhaseStatus.AWAITING_REVIEW.value
        phase['status_updated_at'] = datetime.now().isoformat()
        phase['agents_completed_at'] = datetime.now().isoformat()

        # Extract task_id from registry for callback (save for use after lock release)
        task_id = registry.get('task_id', '')

        # Increment version
        registry['version'] = registry.get('version', 0) + 1
        new_version = registry['version']

        # Write back atomically
        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.info(
            f"Phase {phase_id} advanced to AWAITING_REVIEW "
            f"({completion['total_agents']} agents complete, version={new_version})"
        )

        # Save values needed after lock release
        saved_completion = completion
        saved_new_version = new_version
        saved_task_id = task_id

    # Trigger review agent deployment AFTER releasing lock
    # This prevents holding the lock while spawning agents
    review_triggered = False
    review_deployment = None

    if deploy_review_agent_fn is not None and task_workspace is not None:
        try:
            logger.info(
                f"Triggering review agent deployment for phase {phase_id} "
                f"(task={saved_task_id}, workspace={task_workspace})"
            )
            review_deployment = deploy_review_agent_fn(saved_task_id, phase_id, task_workspace)
            review_triggered = True
            logger.info(f"Review agent deployment triggered: {review_deployment}")
        except Exception as e:
            logger.error(f"Failed to trigger review agent deployment: {e}")
            review_deployment = {"error": str(e)}
    elif deploy_review_agent_fn is not None and task_workspace is None:
        logger.warning(
            f"deploy_review_agent_fn provided but task_workspace is None. "
            f"Cannot trigger review agent for phase {phase_id}"
        )

    return {
        "success": True,
        "advanced": True,
        "completion_check": saved_completion,
        "reason": f"Advanced to review: {saved_completion['reason']}",
        "new_version": saved_new_version,
        "review_triggered": review_triggered,
        "review_deployment": review_deployment
    }


def advance_phase(
    registry_path: str,
    from_phase_id: str,
    to_phase_id: str,
    task_workspace: Optional[str] = None,
    handover: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Advance from one phase to the next after review approval.

    This function performs multiple coordinated updates atomically:
    1. Marks from_phase as APPROVED
    2. Marks all agents in from_phase as 'phase_completed'
    3. Activates to_phase (PENDING -> ACTIVE)
    4. Updates current_phase_id pointer
    5. Creates and saves handover document if task_workspace is provided

    All updates happen within a single lock acquisition to prevent race conditions.

    Args:
        registry_path: Path to registry file
        from_phase_id: Phase being completed (must be in APPROVED-able state)
        to_phase_id: Phase to activate next
        task_workspace: Optional path to task workspace for handover storage.
                       If provided, a handover document will be created and saved.
        handover: Optional handover data dict. If not provided and task_workspace
                  is set, handover will be auto-generated from phase findings.
                  Can be a dict matching HandoverDocument fields.

    Returns:
        Dict with result:
            {
                "success": bool,              # True if phase advanced
                "reason": str,                # Explanation
                "agents_marked": int,         # Number of agents marked phase_completed
                "from_phase_status": str,     # Final status of from_phase
                "to_phase_status": str,       # Final status of to_phase
                "new_version": int,           # Registry version after update
                "handover_path": str or None  # Path to saved handover document
            }
    """
    logger.debug(f"Advancing from phase {from_phase_id} to {to_phase_id}")

    with LockedRegistryFile(registry_path) as (registry, f):
        phases = registry.get('phases', [])

        # Find both phases
        from_phase = None
        to_phase = None
        for p in phases:
            if p.get('id') == from_phase_id:
                from_phase = p
            elif p.get('id') == to_phase_id:
                to_phase = p

        # Validate phases exist
        if from_phase is None:
            return {
                "success": False,
                "reason": f"From phase {from_phase_id} not found",
                "agents_marked": 0,
                "from_phase_status": None,
                "to_phase_status": None,
                "new_version": registry.get('version', 0)
            }

        if to_phase is None:
            return {
                "success": False,
                "reason": f"To phase {to_phase_id} not found",
                "agents_marked": 0,
                "from_phase_status": from_phase.get('status'),
                "to_phase_status": None,
                "new_version": registry.get('version', 0)
            }

        from_status = from_phase.get('status', '')
        to_status = to_phase.get('status', '')

        # Validate from_phase can be approved
        # It should be UNDER_REVIEW or already approved statuses
        approvable_statuses = {
            PhaseStatus.UNDER_REVIEW.value,
            PhaseStatus.AWAITING_REVIEW.value  # Allow direct approval in some cases
        }
        if from_status not in approvable_statuses:
            return {
                "success": False,
                "reason": f"From phase not in approvable state (current: {from_status})",
                "agents_marked": 0,
                "from_phase_status": from_status,
                "to_phase_status": to_status,
                "new_version": registry.get('version', 0)
            }

        # Validate to_phase is PENDING
        if to_status != PhaseStatus.PENDING.value:
            return {
                "success": False,
                "reason": f"To phase not in PENDING state (current: {to_status})",
                "agents_marked": 0,
                "from_phase_status": from_status,
                "to_phase_status": to_status,
                "new_version": registry.get('version', 0)
            }

        timestamp = datetime.now().isoformat()

        # 1. Mark from_phase as APPROVED
        from_phase['status'] = PhaseStatus.APPROVED.value
        from_phase['status_updated_at'] = timestamp
        from_phase['approved_at'] = timestamp

        # 2. Mark all agents in from_phase as 'phase_completed'
        agents_marked = 0
        phase_findings = []
        for agent in registry.get('agents', []):
            if agent.get('phase_id') == from_phase_id:
                if agent.get('status') in AGENT_ACTIVE_STATUSES:
                    agent['status'] = 'phase_completed'
                    agent['completed_at'] = timestamp
                    agents_marked += 1
                # Collect findings for auto-generation if needed
                if agent.get('findings'):
                    phase_findings.extend(agent.get('findings', []))

        # Update active count for marked agents
        registry['active_count'] = max(0, registry.get('active_count', 0) - agents_marked)

        # 3. Activate to_phase
        to_phase['status'] = PhaseStatus.ACTIVE.value
        to_phase['status_updated_at'] = timestamp
        to_phase['started_at'] = timestamp

        # 4. Update current_phase_id pointer
        registry['current_phase_id'] = to_phase_id

        # 5. Store handover_path in from_phase if task_workspace provided
        handover_path = None
        from_phase_name = from_phase.get('name', 'Unknown Phase')
        if task_workspace:
            # Import handover module here to avoid circular import
            try:
                from . import handover as handover_module
                handover_path = handover_module.get_handover_path(task_workspace, from_phase_id)
                from_phase['handover_path'] = handover_path
                logger.debug(f"Set handover_path for phase {from_phase_id}: {handover_path}")
            except ImportError as e:
                logger.warning(f"Could not import handover module: {e}")

        # Increment version
        registry['version'] = registry.get('version', 0) + 1
        new_version = registry['version']

        # Write back atomically
        f.seek(0)
        f.write(json.dumps(registry, indent=2))
        f.truncate()

        logger.info(
            f"Phase advanced: {from_phase_id} (APPROVED) -> {to_phase_id} (ACTIVE), "
            f"{agents_marked} agents marked, version={new_version}"
        )

    # 6. Create and save handover document AFTER releasing registry lock
    # This prevents holding the lock while doing file I/O for handover
    if task_workspace and handover_path:
        try:
            from . import handover as handover_module

            # Create or use provided handover
            if handover:
                # Use provided handover data
                if isinstance(handover, dict):
                    handover_doc = handover_module.HandoverDocument(
                        phase_id=from_phase_id,
                        phase_name=from_phase_name,
                        created_at=timestamp,
                        summary=handover.get('summary', ''),
                        key_findings=handover.get('key_findings', []),
                        blockers=handover.get('blockers', []),
                        recommendations=handover.get('recommendations', []),
                        artifacts=handover.get('artifacts', []),
                        metrics=handover.get('metrics', {})
                    )
                else:
                    handover_doc = handover
            else:
                # Auto-generate handover from phase findings
                handover_doc = handover_module.HandoverDocument(
                    phase_id=from_phase_id,
                    phase_name=from_phase_name,
                    created_at=timestamp,
                    summary=f"Phase '{from_phase_name}' completed with {agents_marked} agents marked as done.",
                    key_findings=phase_findings[:20],  # Limit to 20 findings
                    blockers=[],
                    recommendations=[],
                    artifacts=[],
                    metrics={
                        'agents_marked': agents_marked,
                        'total_findings': len(phase_findings)
                    }
                )

            # Save handover document
            save_result = handover_module.save_handover(task_workspace, handover_doc)
            if save_result.get('success'):
                logger.info(f"Saved handover document: {handover_path}")
            else:
                logger.warning(f"Failed to save handover: {save_result.get('error')}")
                handover_path = None  # Clear path if save failed

        except ImportError as e:
            logger.warning(f"Could not import handover module for saving: {e}")
            handover_path = None
        except Exception as e:
            logger.error(f"Error creating/saving handover: {e}")
            handover_path = None

    return {
        "success": True,
        "reason": f"Advanced from {from_phase_id} to {to_phase_id}",
        "agents_marked": agents_marked,
        "from_phase_status": PhaseStatus.APPROVED.value,
        "to_phase_status": PhaseStatus.ACTIVE.value,
        "new_version": new_version,
        "handover_path": handover_path
    }


def get_previous_phase_handover(
    task_workspace: str,
    registry: Dict[str, Any],
    current_phase_id: str
) -> Optional[Dict[str, Any]]:
    """
    Get handover from the previous phase based on phase order from registry.

    This function uses the registry to find the previous phase (order - 1)
    and loads its handover document if it exists.

    Args:
        task_workspace: Path to task workspace directory
        registry: Registry dict (already loaded)
        current_phase_id: ID of the current phase (to find the one before it)

    Returns:
        Dict with handover data if found, None otherwise:
            {
                "success": bool,
                "handover": HandoverDocument or None,
                "previous_phase_id": str or None,
                "previous_phase_name": str or None,
                "handover_path": str or None,
                "reason": str
            }

    Example:
        >>> registry = read_registry_with_lock(registry_path)
        >>> result = get_previous_phase_handover(
        ...     '/workspace/TASK-123',
        ...     registry,
        ...     'phase-def456'  # Current phase
        ... )
        >>> if result['success'] and result['handover']:
        ...     print(f"Previous phase summary: {result['handover'].summary}")
    """
    logger.debug(f"Getting previous phase handover for current phase {current_phase_id}")

    phases = registry.get('phases', [])

    if not phases:
        logger.debug("No phases in registry")
        return {
            "success": False,
            "handover": None,
            "previous_phase_id": None,
            "previous_phase_name": None,
            "handover_path": None,
            "reason": "No phases in registry"
        }

    # Find current phase and its order
    current_phase = None
    for phase in phases:
        if phase.get('id') == current_phase_id:
            current_phase = phase
            break

    if not current_phase:
        logger.warning(f"Current phase {current_phase_id} not found in registry")
        return {
            "success": False,
            "handover": None,
            "previous_phase_id": None,
            "previous_phase_name": None,
            "handover_path": None,
            "reason": f"Current phase {current_phase_id} not found"
        }

    current_order = current_phase.get('order', 0)

    # Find previous phase (order - 1)
    previous_phase = None
    for phase in phases:
        if phase.get('order') == current_order - 1:
            previous_phase = phase
            break

    if not previous_phase:
        logger.debug(f"No previous phase found (current order: {current_order})")
        return {
            "success": True,
            "handover": None,
            "previous_phase_id": None,
            "previous_phase_name": None,
            "handover_path": None,
            "reason": "This is the first phase, no previous handover exists"
        }

    previous_phase_id = previous_phase.get('id')
    previous_phase_name = previous_phase.get('name', 'Unknown')

    # Check if previous phase has a handover_path stored
    handover_path = previous_phase.get('handover_path')

    if not handover_path:
        logger.debug(f"Previous phase {previous_phase_id} has no handover_path set")
        return {
            "success": True,
            "handover": None,
            "previous_phase_id": previous_phase_id,
            "previous_phase_name": previous_phase_name,
            "handover_path": None,
            "reason": f"Previous phase '{previous_phase_name}' has no handover document"
        }

    # Load handover from file
    try:
        from . import handover as handover_module

        handover_doc = handover_module.load_handover(task_workspace, previous_phase_id)

        if handover_doc:
            logger.info(f"Loaded handover from previous phase {previous_phase_id}")
            return {
                "success": True,
                "handover": handover_doc,
                "previous_phase_id": previous_phase_id,
                "previous_phase_name": previous_phase_name,
                "handover_path": handover_path,
                "reason": f"Loaded handover from phase '{previous_phase_name}'"
            }
        else:
            logger.warning(f"Handover file exists but could not be parsed: {handover_path}")
            return {
                "success": True,
                "handover": None,
                "previous_phase_id": previous_phase_id,
                "previous_phase_name": previous_phase_name,
                "handover_path": handover_path,
                "reason": f"Handover file exists but could not be parsed"
            }

    except ImportError as e:
        logger.warning(f"Could not import handover module: {e}")
        return {
            "success": False,
            "handover": None,
            "previous_phase_id": previous_phase_id,
            "previous_phase_name": previous_phase_name,
            "handover_path": handover_path,
            "reason": f"Failed to import handover module: {e}"
        }
    except Exception as e:
        logger.error(f"Error loading handover: {e}")
        return {
            "success": False,
            "handover": None,
            "previous_phase_id": previous_phase_id,
            "previous_phase_name": previous_phase_name,
            "handover_path": handover_path,
            "reason": f"Error loading handover: {e}"
        }


# ============================================================================
# REGISTRY HEALTH CHECK AND VALIDATION
# ============================================================================

def registry_health_check(
    registry_path: str,
    list_all_tmux_sessions_fn=None
) -> Dict[str, Any]:
    """
    Compare registry state against actual tmux sessions to detect discrepancies.

    Args:
        registry_path: Path to AGENT_REGISTRY.json
        list_all_tmux_sessions_fn: Function to list tmux sessions (dependency injection)

    Returns:
        Health report with discrepancies and recommendations
    """
    try:
        # Get actual tmux sessions
        if list_all_tmux_sessions_fn is None:
            from .deployment import list_all_tmux_sessions
            list_all_tmux_sessions_fn = list_all_tmux_sessions

        tmux_result = list_all_tmux_sessions_fn()
        if not tmux_result['success']:
            return {
                'success': False,
                'error': f"Failed to list tmux sessions: {tmux_result.get('error')}",
                'healthy': False
            }

        actual_sessions = set(tmux_result['sessions'].keys())

        # Load registry with file locking
        with open(registry_path, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
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
        zombie_agents = []
        orphan_sessions = []

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


def generate_health_recommendations(
    zombie_agents: List[Dict],
    orphan_sessions: List[str],
    count_mismatch: bool
) -> List[Dict[str, str]]:
    """Generate actionable recommendations based on health check results."""
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


def validate_and_repair_registry(
    registry_path: str,
    dry_run: bool = False,
    list_all_tmux_sessions_fn=None
) -> Dict[str, Any]:
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
        list_all_tmux_sessions_fn: Function to list tmux sessions (dependency injection)

    Returns:
        Repair report with changes made
    """
    try:
        # Get actual tmux sessions
        if list_all_tmux_sessions_fn is None:
            from .deployment import list_all_tmux_sessions
            list_all_tmux_sessions_fn = list_all_tmux_sessions

        tmux_result = list_all_tmux_sessions_fn()
        if not tmux_result['success']:
            return {
                'success': False,
                'error': f"Failed to list tmux sessions: {tmux_result.get('error')}",
                'changes_made': 0
            }

        actual_sessions = set(tmux_result['sessions'].keys())

        # Acquire exclusive lock for modification
        with open(registry_path, 'r+') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

            registry = json.load(f)

            changes = {
                'zombies_terminated': [],
                'orphans_found': [],
                'count_corrected': False,
                'old_active_count': registry.get('active_count', 0),
                'new_active_count': 0
            }

            active_statuses = {'running', 'working', 'blocked'}
            actual_active_count = 0

            for agent in registry.get('agents', []):
                agent_status = agent.get('status')
                tmux_session = agent.get('tmux_session')

                if agent_status in active_statuses:
                    if tmux_session and tmux_session in actual_sessions:
                        actual_active_count += 1
                    else:
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

            registry_sessions = {
                agent.get('tmux_session')
                for agent in registry.get('agents', [])
                if agent.get('tmux_session')
            }

            for session in actual_sessions:
                if session not in registry_sessions:
                    changes['orphans_found'].append(session)

            if registry.get('active_count', 0) != actual_active_count:
                changes['count_corrected'] = True
                changes['new_active_count'] = actual_active_count
                if not dry_run:
                    registry['active_count'] = actual_active_count
            else:
                changes['new_active_count'] = actual_active_count

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
