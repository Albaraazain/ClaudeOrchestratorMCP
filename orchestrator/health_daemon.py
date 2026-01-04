"""
Active Health Monitoring Daemon for Orchestrator Agents.

This module provides proactive health monitoring for all active agents,
detecting dead/zombie agents and automatically marking them as failed.
Unlike passive checks, this runs continuously in the background.
"""

import os
import json
import time
import logging
import threading
import subprocess
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from pathlib import Path

from .registry import LockedRegistryFile
from .workspace import find_task_workspace, get_workspace_base_from_task_workspace, get_global_registry_path

logger = logging.getLogger(__name__)

# Agent statuses
AGENT_TERMINAL_STATUSES = {'completed', 'failed', 'error', 'terminated', 'killed'}
AGENT_ACTIVE_STATUSES = {'running', 'working', 'blocked'}

# Health check configuration
DEFAULT_SCAN_INTERVAL = 30  # seconds between health scans
STUCK_AGENT_THRESHOLD = 300  # 5 minutes without log activity = stuck
LOG_CHECK_INTERVAL = 60  # check log files every 60 seconds


class HealthDaemon:
    """Background daemon that continuously monitors agent health."""

    def __init__(self, workspace_base: str, scan_interval: int = DEFAULT_SCAN_INTERVAL):
        """
        Initialize the health monitoring daemon.

        Args:
            workspace_base: Base workspace directory (.agent-workspace)
            scan_interval: Seconds between health scans
        """
        self.workspace_base = os.path.abspath(workspace_base)
        self.scan_interval = scan_interval
        self.daemon_thread = None
        self.stop_event = threading.Event()
        self.monitored_tasks = set()  # Task IDs being monitored
        self.last_log_check = {}  # Track last log modification times
        self.is_running = False

        logger.info(f"HealthDaemon initialized for workspace: {self.workspace_base}")

    def start(self):
        """Start the health monitoring daemon in a background thread."""
        if self.is_running:
            logger.warning("HealthDaemon already running")
            return

        self.stop_event.clear()
        self.daemon_thread = threading.Thread(target=self._daemon_loop, daemon=True)
        self.daemon_thread.start()
        self.is_running = True
        logger.info("HealthDaemon started")

    def stop(self, timeout: int = 5):
        """
        Stop the health monitoring daemon.

        Args:
            timeout: Seconds to wait for daemon to stop
        """
        if not self.is_running:
            return

        logger.info("Stopping HealthDaemon...")
        self.stop_event.set()

        if self.daemon_thread:
            self.daemon_thread.join(timeout)
            if self.daemon_thread.is_alive():
                logger.warning("HealthDaemon thread did not stop gracefully")

        self.is_running = False
        logger.info("HealthDaemon stopped")

    def register_task(self, task_id: str):
        """
        Register a task for health monitoring.

        Args:
            task_id: Task ID to monitor
        """
        self.monitored_tasks.add(task_id)
        logger.info(f"Registered task {task_id} for health monitoring")

    def unregister_task(self, task_id: str):
        """
        Unregister a task from health monitoring.

        Args:
            task_id: Task ID to stop monitoring
        """
        self.monitored_tasks.discard(task_id)
        # Clean up last log check entries
        agents_to_remove = [k for k in self.last_log_check if k.startswith(f"{task_id}:")]
        for key in agents_to_remove:
            del self.last_log_check[key]
        logger.info(f"Unregistered task {task_id} from health monitoring")

    def get_status(self) -> Dict[str, Any]:
        """
        Get current daemon status.

        Returns:
            Dict with daemon running status, monitored tasks, and stats.
        """
        return {
            "running": self.is_running,
            "scan_interval": self.scan_interval,
            "monitored_tasks_count": len(self.monitored_tasks),
            "monitored_tasks": list(self.monitored_tasks),
            "workspace_base": self.workspace_base
        }

    def trigger_scan(self) -> bool:
        """
        Trigger an immediate health scan of all monitored tasks.

        Returns:
            True if scan was triggered, False if daemon not running.
        """
        if not self.is_running:
            logger.warning("Cannot trigger scan - daemon not running")
            return False

        logger.info("Manual health scan triggered")
        for task_id in list(self.monitored_tasks):
            try:
                self._scan_task_health(task_id)
            except Exception as e:
                logger.error(f"Error scanning task {task_id}: {e}")
        return True

    def _daemon_loop(self):
        """Main daemon loop that continuously monitors health."""
        logger.info("HealthDaemon loop started")

        # Track global registry cleanup interval (every 5 scans = ~2.5 minutes)
        scan_count = 0
        GLOBAL_CLEANUP_INTERVAL = 5

        while not self.stop_event.is_set():
            try:
                # Scan all registered tasks
                for task_id in list(self.monitored_tasks):
                    try:
                        self._scan_task_health(task_id)
                    except Exception as e:
                        logger.error(f"Error scanning task {task_id}: {e}")

                # Periodically clean up dead agents from global registry
                scan_count += 1
                if scan_count >= GLOBAL_CLEANUP_INTERVAL:
                    scan_count = 0
                    try:
                        self._cleanup_global_registry()
                    except Exception as e:
                        logger.error(f"Error during global registry cleanup: {e}")

                # Wait for next scan interval
                self.stop_event.wait(self.scan_interval)

            except Exception as e:
                logger.error(f"Critical error in health daemon loop: {e}")
                time.sleep(5)  # Brief recovery pause

        logger.info("HealthDaemon loop stopped")

    def _scan_task_health(self, task_id: str):
        """
        Scan health of all agents in a task.

        Args:
            task_id: Task ID to scan
        """
        workspace = find_task_workspace(task_id, self.workspace_base)
        if not workspace:
            logger.warning(f"Task {task_id} workspace not found, unregistering")
            self.unregister_task(task_id)
            return

        registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")
        if not os.path.exists(registry_path):
            logger.warning(f"Registry not found for task {task_id}, unregistering")
            self.unregister_task(task_id)
            return

        # Track agents that need status updates
        agents_to_fail = []

        try:
            # Read registry to get active agents
            with LockedRegistryFile(registry_path) as (registry, f):
                for agent in registry.get('agents', []):
                    if agent['status'] not in AGENT_ACTIVE_STATUSES:
                        continue

                    agent_id = agent['id']
                    health_status = self._check_agent_health(agent, workspace)

                    if not health_status['healthy']:
                        logger.warning(f"Agent {agent_id} unhealthy: {health_status['reason']}")
                        agents_to_fail.append({
                            'agent': agent,
                            'reason': health_status['reason'],
                            'details': health_status.get('details', {})
                        })

        except Exception as e:
            logger.error(f"Error reading registry for task {task_id}: {e}")
            return

        # Mark unhealthy agents as failed
        if agents_to_fail:
            self._mark_agents_failed(task_id, workspace, agents_to_fail)

    def _check_agent_health(self, agent_info: Dict[str, Any], workspace: str) -> Dict[str, Any]:
        """
        Check health of a single agent.

        Args:
            agent_info: Agent information from registry
            workspace: Task workspace path

        Returns:
            Health status dict with 'healthy' bool and 'reason' if unhealthy
        """
        agent_id = agent_info['id']

        # 1. Check tmux session exists
        if 'tmux_session' in agent_info:
            session_name = agent_info['tmux_session']
            if not self._check_tmux_session_exists(session_name):
                return {
                    'healthy': False,
                    'reason': 'tmux_session_dead',
                    'details': {'session_name': session_name}
                }

        # 2. Check Claude process if PID is tracked
        if 'claude_pid' in agent_info:
            pid = agent_info['claude_pid']
            if not self._check_process_alive(pid):
                return {
                    'healthy': False,
                    'reason': 'claude_process_dead',
                    'details': {'pid': pid}
                }

        # 3. Check Cursor process if PID is tracked
        if 'cursor_pid' in agent_info:
            pid = agent_info['cursor_pid']
            if not self._check_process_alive(pid):
                return {
                    'healthy': False,
                    'reason': 'cursor_process_dead',
                    'details': {'pid': pid}
                }

        # 4. Check for stuck agents (no log activity)
        log_file = os.path.join(workspace, 'logs', f'{agent_id}_stream.jsonl')
        if os.path.exists(log_file):
            last_modified = os.path.getmtime(log_file)
            current_time = time.time()

            # Track last known modification time
            cache_key = f"{workspace}:{agent_id}"

            if cache_key in self.last_log_check:
                # Check if log hasn't changed for too long
                if last_modified == self.last_log_check[cache_key]['mtime']:
                    time_since_activity = current_time - self.last_log_check[cache_key]['first_seen']
                    if time_since_activity > STUCK_AGENT_THRESHOLD:
                        return {
                            'healthy': False,
                            'reason': 'agent_stuck',
                            'details': {
                                'last_activity': datetime.fromtimestamp(last_modified).isoformat(),
                                'stuck_duration_seconds': int(time_since_activity)
                            }
                        }
                else:
                    # Log was modified, update tracking
                    self.last_log_check[cache_key] = {
                        'mtime': last_modified,
                        'first_seen': current_time
                    }
            else:
                # First time checking this agent's log
                self.last_log_check[cache_key] = {
                    'mtime': last_modified,
                    'first_seen': current_time
                }

        return {'healthy': True}

    def _check_tmux_session_exists(self, session_name: str) -> bool:
        """
        Check if a tmux session exists.

        Args:
            session_name: Name of tmux session

        Returns:
            True if session exists, False otherwise
        """
        try:
            result = subprocess.run(
                ['tmux', 'has-session', '-t', session_name],
                capture_output=True,
                timeout=2
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _check_process_alive(self, pid: int) -> bool:
        """
        Check if a process is alive by PID.

        Args:
            pid: Process ID

        Returns:
            True if process exists, False otherwise
        """
        try:
            # Send signal 0 (no-op) to check if process exists
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    def _mark_agents_failed(self, task_id: str, workspace: str, failed_agents: List[Dict[str, Any]]):
        """
        Mark unhealthy agents as failed in registry.
        Also triggers phase enforcement check if all phase agents are now done.

        Args:
            task_id: Task ID
            workspace: Task workspace path
            failed_agents: List of agents to mark as failed with reasons
        """
        registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")
        pending_phase_check = None  # Will be set if phase needs enforcement check

        try:
            # Update local registry
            with LockedRegistryFile(registry_path) as (registry, f):
                for failed_info in failed_agents:
                    agent = failed_info['agent']
                    agent_id = agent['id']

                    # Find and update agent in registry
                    for reg_agent in registry.get('agents', []):
                        if reg_agent['id'] == agent_id:
                            # Mark as failed
                            reg_agent['status'] = 'failed'
                            reg_agent['failed_at'] = datetime.now().isoformat()
                            reg_agent['failure_reason'] = f"Health check failed: {failed_info['reason']}"
                            reg_agent['failure_details'] = failed_info.get('details', {})

                            # Update counters
                            if reg_agent.get('status') in AGENT_ACTIVE_STATUSES:
                                registry['active_count'] = max(0, registry.get('active_count', 0) - 1)
                                registry['failed_count'] = registry.get('failed_count', 0) + 1

                            logger.info(f"Marked agent {agent_id} as failed: {failed_info['reason']}")
                            break

                # ===== AUTOMATIC PHASE ENFORCEMENT =====
                # Check if ALL agents in current phase are now in terminal state
                # This mirrors the logic in update_agent_progress
                phases = registry.get('phases', [])
                current_phase_idx = registry.get('current_phase_index', 0)

                if current_phase_idx < len(phases):
                    current_phase = phases[current_phase_idx]

                    # Only auto-trigger if phase is ACTIVE (not already in review)
                    if current_phase.get('status') == 'ACTIVE':
                        terminal_statuses = {'completed', 'failed', 'error', 'terminated', 'killed'}

                        # Count phase agents
                        phase_agents = [a for a in registry.get('agents', [])
                                        if a.get('phase_index') == current_phase_idx]
                        completed_phase_agents = [a for a in phase_agents
                                                  if a.get('status') == 'completed']
                        failed_phase_agents = [a for a in phase_agents
                                              if a.get('status') in terminal_statuses - {'completed'}]

                        logger.info(f"Phase {current_phase_idx} health check: "
                                   f"{len(completed_phase_agents)}/{len(phase_agents)} completed, "
                                   f"{len(failed_phase_agents)} failed")

                        # All agents in terminal state?
                        if len(phase_agents) > 0 and len(completed_phase_agents) + len(failed_phase_agents) == len(phase_agents):
                            # AUTO-SUBMIT PHASE FOR REVIEW
                            current_phase['status'] = 'AWAITING_REVIEW'
                            current_phase['auto_submitted_at'] = datetime.now().isoformat()
                            current_phase['auto_submitted_reason'] = (
                                f"All {len(phase_agents)} agents completed/terminated "
                                f"(health daemon detected)"
                            )

                            # Store pending review info for spawning reviewers
                            pending_phase_check = {
                                'task_id': task_id,
                                'phase_index': current_phase_idx,
                                'phase_name': current_phase.get('name', f'Phase {current_phase_idx + 1}'),
                                'completed_agents': len(completed_phase_agents),
                                'failed_agents': len(failed_phase_agents),
                                'workspace': workspace
                            }

                            logger.info(f"PHASE-ENFORCEMENT (health daemon): Phase {current_phase_idx} "
                                       f"({current_phase.get('name')}) auto-submitted for review")

                # Write back atomically
                f.seek(0)
                f.write(json.dumps(registry, indent=2))
                f.truncate()

            # Update global registry
            self._update_global_registry(workspace, failed_agents)

            # ===== CHECK FOR STALLED REVIEWS =====
            # If any failed agents are reviewers, check if review can be finalized with partial verdicts
            reviewer_agent_ids = [f['agent']['id'] for f in failed_agents if 'reviewer' in f['agent'].get('type', '').lower()]
            if reviewer_agent_ids:
                self._check_stalled_reviews(task_id, workspace, reviewer_agent_ids)

            # ===== SPAWN PHASE REVIEWERS (outside lock) =====
            if pending_phase_check:
                self._trigger_phase_review(pending_phase_check)

        except Exception as e:
            logger.error(f"Failed to mark agents as failed: {e}")

    def _trigger_phase_review(self, pending_review: Dict[str, Any]):
        """
        Trigger agentic phase review by spawning reviewer agents.
        This is called after phase auto-completion is detected.

        Args:
            pending_review: Dict with task_id, phase_index, phase_name, etc.
        """
        try:
            # Import here to avoid circular import
            from real_mcp_server import _auto_spawn_phase_reviewers

            logger.info(f"PHASE-ENFORCEMENT: Spawning reviewers for phase {pending_review['phase_index']}")

            result = _auto_spawn_phase_reviewers(
                task_id=pending_review['task_id'],
                phase_index=pending_review['phase_index'],
                phase_name=pending_review['phase_name'],
                completed_agents=pending_review['completed_agents'],
                failed_agents=pending_review['failed_agents'],
                workspace=pending_review['workspace']
            )

            logger.info(f"PHASE-ENFORCEMENT: Reviewer spawn result: {result}")

        except Exception as e:
            logger.error(f"PHASE-ENFORCEMENT: Failed to spawn reviewers: {e}")

    def _update_global_registry(self, workspace: str, failed_agents: List[Dict[str, Any]]):
        """
        Update global registry for failed agents.

        Args:
            workspace: Task workspace path
            failed_agents: List of failed agents
        """
        try:
            workspace_base = get_workspace_base_from_task_workspace(workspace)
            global_reg_path = get_global_registry_path(workspace_base)

            if not os.path.exists(global_reg_path):
                return

            with LockedRegistryFile(global_reg_path) as (global_reg, gf):
                for failed_info in failed_agents:
                    agent_id = failed_info['agent']['id']

                    if agent_id in global_reg.get('agents', {}):
                        global_reg['agents'][agent_id]['status'] = 'failed'
                        global_reg['agents'][agent_id]['failed_at'] = datetime.now().isoformat()
                        global_reg['agents'][agent_id]['failure_reason'] = f"Health check: {failed_info['reason']}"
                        global_reg['active_agents'] = max(0, global_reg.get('active_agents', 0) - 1)

                gf.seek(0)
                gf.write(json.dumps(global_reg, indent=2))
                gf.truncate()

            logger.info(f"Updated global registry for {len(failed_agents)} failed agents")

        except Exception as e:
            logger.error(f"Failed to update global registry: {e}")

    def _cleanup_global_registry(self):
        """
        Scan global registry and clean up agents with dead tmux sessions.

        This is called periodically by the daemon loop to ensure the global
        registry stays accurate even for agents that crash without reporting.
        """
        global_reg_path = get_global_registry_path(self.workspace_base)

        if not os.path.exists(global_reg_path):
            return

        # Get list of running tmux sessions
        try:
            result = subprocess.run(
                ['tmux', 'list-sessions', '-F', '#{session_name}'],
                capture_output=True,
                text=True,
                timeout=5
            )
            running_sessions = set(result.stdout.strip().split('\n')) if result.returncode == 0 else set()
        except Exception as e:
            logger.warning(f"Failed to list tmux sessions for cleanup: {e}")
            return

        cleaned_count = 0
        active_statuses = {'running', 'working', 'blocked'}
        terminal_statuses = {'completed', 'failed', 'error', 'terminated', 'killed'}

        try:
            with LockedRegistryFile(global_reg_path) as (global_reg, gf):
                agents = global_reg.get('agents', {})

                for agent_id, agent_data in agents.items():
                    status = agent_data.get('status')
                    tmux_session = agent_data.get('tmux_session')

                    # Skip if already in terminal state
                    if status in terminal_statuses:
                        continue

                    # Check if tmux session is dead
                    if tmux_session and tmux_session not in running_sessions:
                        # Mark as failed
                        previous_status = agent_data.get('status')
                        agent_data['status'] = 'failed'
                        agent_data['failed_at'] = datetime.now().isoformat()
                        agent_data['failure_reason'] = f'Health daemon: tmux session dead ({tmux_session})'

                        # Decrement active_agents
                        if previous_status is None or previous_status in active_statuses:
                            global_reg['active_agents'] = max(0, global_reg.get('active_agents', 0) - 1)

                        cleaned_count += 1
                        logger.info(f"Daemon cleanup: agent {agent_id} marked failed (dead tmux: {tmux_session})")

                    # Handle agents with no status or no tmux session tracked
                    elif status is None or (status in active_statuses and not tmux_session):
                        agent_data['status'] = 'failed'
                        agent_data['failed_at'] = datetime.now().isoformat()
                        agent_data['failure_reason'] = 'Health daemon: no tmux session tracked'
                        global_reg['active_agents'] = max(0, global_reg.get('active_agents', 0) - 1)
                        cleaned_count += 1
                        logger.info(f"Daemon cleanup: agent {agent_id} marked failed (no tmux session)")

                if cleaned_count > 0:
                    gf.seek(0)
                    gf.write(json.dumps(global_reg, indent=2))
                    gf.truncate()
                    logger.info(f"Global registry daemon cleanup: {cleaned_count} dead agents cleaned, active_agents now: {global_reg.get('active_agents', 0)}")

        except Exception as e:
            logger.error(f"Global registry daemon cleanup failed: {e}")

    def _check_stalled_reviews(self, task_id: str, workspace: str, dead_reviewer_ids: List[str]):
        """
        Check if any reviews are stalled due to dead reviewers and finalize with partial verdicts.

        This is called when the health daemon detects that reviewer agents have died.
        If a review has some verdicts submitted and all remaining reviewers are dead,
        we finalize the review with the partial verdicts available.

        Args:
            task_id: Task ID
            workspace: Task workspace path
            dead_reviewer_ids: List of reviewer agent IDs that were just marked as failed
        """
        registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")

        try:
            with LockedRegistryFile(registry_path) as (registry, f):
                reviews = registry.get('reviews', [])
                modified = False

                for review in reviews:
                    # Only check in-progress reviews
                    if review.get('status') != 'in_progress':
                        continue

                    review_id = review.get('id')
                    verdicts = review.get('verdicts', [])
                    reviewers = review.get('reviewers', [])

                    if not reviewers:
                        continue

                    # Get all reviewer agent IDs for this review
                    reviewer_agent_ids = [r.get('agent_id') for r in reviewers]
                    submitted_reviewer_ids = [v.get('reviewer_agent_id') for v in verdicts]

                    # Find reviewers that haven't submitted yet
                    pending_reviewer_ids = [rid for rid in reviewer_agent_ids if rid not in submitted_reviewer_ids]

                    if not pending_reviewer_ids:
                        # All submitted - this shouldn't happen but just in case
                        continue

                    # Check if any of the dead reviewers are in this review's pending list
                    dead_in_this_review = [rid for rid in pending_reviewer_ids if rid in dead_reviewer_ids]

                    if not dead_in_this_review:
                        # The dead reviewers aren't part of this review
                        continue

                    # Check if ALL pending reviewers are now dead (check registry for all agents)
                    all_pending_dead = True
                    for pending_id in pending_reviewer_ids:
                        # Check if this pending reviewer is dead
                        for agent in registry.get('agents', []):
                            if agent.get('id') == pending_id:
                                if agent.get('status') not in {'failed', 'error', 'terminated', 'killed'}:
                                    all_pending_dead = False
                                break

                    if all_pending_dead and len(verdicts) > 0:
                        # We have partial verdicts and all remaining reviewers are dead
                        # Finalize with what we have
                        logger.warning(f"Review {review_id} has stalled - {len(verdicts)}/{len(reviewer_agent_ids)} "
                                      f"verdicts submitted, {len(pending_reviewer_ids)} reviewers dead. "
                                      f"Finalizing with partial verdicts.")

                        # Aggregate partial verdicts
                        approved_count = sum(1 for v in verdicts if v.get('verdict') == 'approved')
                        rejected_count = sum(1 for v in verdicts if v.get('verdict') == 'rejected')
                        needs_revision_count = sum(1 for v in verdicts if v.get('verdict') == 'needs_revision')

                        # Collect all findings
                        all_findings = []
                        for v in verdicts:
                            all_findings.extend(v.get('findings', []))

                        # Determine final outcome (simple majority from submitted verdicts)
                        if rejected_count > approved_count and rejected_count > needs_revision_count:
                            final_outcome = 'REJECTED'
                        elif needs_revision_count > approved_count:
                            final_outcome = 'REJECTED'  # Treat needs_revision as rejection
                        elif approved_count > 0:
                            final_outcome = 'APPROVED'
                        else:
                            final_outcome = 'REJECTED'  # Default to rejection if unclear

                        # Update review record
                        review['status'] = 'completed'
                        review['partial_verdict'] = True
                        review['dead_reviewers'] = pending_reviewer_ids
                        review['final_outcome'] = final_outcome
                        review['final_verdict'] = {
                            'approved_count': approved_count,
                            'rejected_count': rejected_count,
                            'needs_revision_count': needs_revision_count,
                            'total_expected': len(reviewer_agent_ids),
                            'total_submitted': len(verdicts),
                            'outcome': final_outcome,
                            'aggregated_findings': all_findings
                        }
                        review['completed_at'] = datetime.now().isoformat()
                        review['completion_reason'] = 'Partial verdict finalization - remaining reviewers dead'

                        # Update phase status based on outcome
                        phase_index = review.get('phase_index')
                        if phase_index is not None and phase_index < len(registry.get('phases', [])):
                            phase = registry['phases'][phase_index]

                            if final_outcome == 'APPROVED':
                                phase['status'] = 'APPROVED'
                                phase['approved_at'] = datetime.now().isoformat()
                                phase['approval_type'] = 'partial_verdict'
                                logger.info(f"Phase {phase_index} APPROVED via partial verdict "
                                           f"({approved_count}/{len(verdicts)} approved)")
                            else:
                                phase['status'] = 'REJECTED'
                                phase['rejected_at'] = datetime.now().isoformat()
                                phase['rejection_type'] = 'partial_verdict'
                                phase['rejection_findings'] = [f for f in all_findings
                                                               if f.get('type') == 'blocker' or
                                                               f.get('severity') in ['critical', 'high']]
                                logger.info(f"Phase {phase_index} REJECTED via partial verdict "
                                           f"({rejected_count + needs_revision_count}/{len(verdicts)} rejected/needs_revision)")

                        modified = True

                    elif len(verdicts) == 0 and all_pending_dead:
                        # All reviewers dead and none submitted - this is a critical failure
                        logger.error(f"Review {review_id} CRITICAL: All {len(reviewer_agent_ids)} reviewers died "
                                    f"without submitting ANY verdicts!")

                        review['status'] = 'failed'
                        review['failed_at'] = datetime.now().isoformat()
                        review['failure_reason'] = 'All reviewers died without submitting verdicts'
                        review['dead_reviewers'] = pending_reviewer_ids

                        # Mark phase as needing manual intervention
                        phase_index = review.get('phase_index')
                        if phase_index is not None and phase_index < len(registry.get('phases', [])):
                            phase = registry['phases'][phase_index]
                            phase['status'] = 'ESCALATED'
                            phase['escalated_at'] = datetime.now().isoformat()
                            phase['escalation_reason'] = 'All reviewers crashed - manual review required'
                            logger.warning(f"Phase {phase_index} ESCALATED - all reviewers crashed")

                        modified = True

                if modified:
                    f.seek(0)
                    f.write(json.dumps(registry, indent=2))
                    f.truncate()
                    logger.info(f"Stalled review check completed - registry updated")

        except Exception as e:
            logger.error(f"Error checking stalled reviews: {e}")


# Global daemon instance
_daemon_instance = None
_daemon_lock = threading.Lock()


def get_health_daemon(workspace_base: str) -> HealthDaemon:
    """
    Get or create the global health daemon instance.

    Args:
        workspace_base: Base workspace directory

    Returns:
        HealthDaemon instance
    """
    global _daemon_instance

    with _daemon_lock:
        if _daemon_instance is None:
            _daemon_instance = HealthDaemon(workspace_base)
            _daemon_instance.start()
        return _daemon_instance


def register_task_for_monitoring(task_id: str, workspace_base: str):
    """
    Register a task for health monitoring.

    Args:
        task_id: Task ID to monitor
        workspace_base: Base workspace directory
    """
    daemon = get_health_daemon(workspace_base)
    daemon.register_task(task_id)


def unregister_task_from_monitoring(task_id: str, workspace_base: str):
    """
    Unregister a task from health monitoring.

    Args:
        task_id: Task ID to stop monitoring
        workspace_base: Base workspace directory
    """
    daemon = get_health_daemon(workspace_base)
    daemon.unregister_task(task_id)


def stop_health_daemon():
    """Stop the global health daemon if running."""
    global _daemon_instance

    with _daemon_lock:
        if _daemon_instance:
            _daemon_instance.stop()
            _daemon_instance = None