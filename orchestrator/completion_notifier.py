#!/usr/bin/env python3
"""
Agent Completion Notifier

This script is called when a Claude agent's tmux session exits.
It immediately updates the registry based on the stream log's result marker.

Usage:
    python3 completion_notifier.py <task_id> <agent_id> <workspace> <log_file>

Called automatically by the agent's tmux command chain when Claude exits.
"""

import json
import os
import sys
import logging
from datetime import datetime
from pathlib import Path

# Setup logging to stderr (stdout may interfere with tmux)
logging.basicConfig(
    level=logging.INFO,
    format='[completion_notifier] %(levelname)s: %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Import registry handling
sys.path.insert(0, str(Path(__file__).parent.parent))
from orchestrator.registry import LockedRegistryFile

TERMINAL_STATUSES = {'completed', 'failed', 'error', 'terminated', 'killed'}
ACTIVE_STATUSES = {'running', 'working', 'blocked'}


def read_last_jsonl_entry(path: str) -> dict | None:
    """Read the last valid JSON object from a JSONL file."""
    try:
        if not os.path.exists(path):
            return None

        with open(path, 'rb') as f:
            # Seek to end, read last 4KB
            f.seek(0, 2)
            file_size = f.tell()
            if file_size == 0:
                return None

            read_size = min(4096, file_size)
            f.seek(-read_size, 2)
            last_chunk = f.read().decode('utf-8', errors='ignore')

        lines = [l.strip() for l in last_chunk.split('\n') if l.strip()]
        for line in reversed(lines):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        return None
    except Exception as e:
        logger.error(f"Error reading {path}: {e}")
        return None


def update_agent_completion(task_id: str, agent_id: str, workspace: str, log_file: str) -> bool:
    """
    Update agent status based on stream log completion marker.

    Returns True if successfully updated, False otherwise.
    """
    registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")

    if not os.path.exists(registry_path):
        logger.error(f"Registry not found: {registry_path}")
        return False

    # Read stream log for completion marker
    last_entry = read_last_jsonl_entry(log_file)

    if not last_entry:
        logger.warning(f"No entries in log file: {log_file}")
        # Still mark as completed since tmux session exited
        new_status = 'completed'
        completion_reason = 'tmux_session_exited_no_log'
        result_msg = ''
    elif last_entry.get('type') == 'result':
        is_error = last_entry.get('is_error', False)
        result_msg = last_entry.get('result', '')[:200]

        if is_error:
            new_status = 'failed'
            completion_reason = f'stream_log_error: {result_msg}'
        else:
            new_status = 'completed'
            completion_reason = 'stream_log_result_marker'
    else:
        # No result marker but session ended
        new_status = 'completed'
        completion_reason = 'tmux_session_exited'
        result_msg = ''

    timestamp = datetime.now().isoformat()

    try:
        with LockedRegistryFile(registry_path) as (registry, f):
            agent_found = False

            for agent in registry.get('agents', []):
                if agent.get('id') == agent_id:
                    agent_found = True
                    prev_status = agent.get('status', '')

                    # Skip if already terminal
                    if prev_status in TERMINAL_STATUSES:
                        logger.info(f"Agent {agent_id} already in terminal state: {prev_status}")
                        return True

                    # Update agent
                    agent['status'] = new_status
                    agent['last_update'] = timestamp
                    agent['completion_reason'] = completion_reason

                    if result_msg:
                        agent['stream_result'] = result_msg

                    if new_status == 'completed':
                        agent['completed_at'] = timestamp
                        agent['progress'] = 100
                        registry['completed_count'] = registry.get('completed_count', 0) + 1
                    else:
                        agent['failed_at'] = timestamp
                        agent['failure_reason'] = completion_reason
                        registry['failed_count'] = registry.get('failed_count', 0) + 1

                    # Decrement active count
                    if prev_status in ACTIVE_STATUSES:
                        registry['active_count'] = max(0, registry.get('active_count', 0) - 1)

                    logger.info(f"Agent {agent_id}: {prev_status} -> {new_status}")
                    break

            if not agent_found:
                logger.warning(f"Agent {agent_id} not found in registry")
                return False

            # Write back
            f.seek(0)
            f.write(json.dumps(registry, indent=2))
            f.truncate()

        logger.info(f"Successfully updated agent {agent_id} to {new_status}")
        return True

    except Exception as e:
        logger.error(f"Failed to update registry: {e}")
        return False


def main():
    if len(sys.argv) != 5:
        print(f"Usage: {sys.argv[0]} <task_id> <agent_id> <workspace> <log_file>", file=sys.stderr)
        sys.exit(1)

    task_id = sys.argv[1]
    agent_id = sys.argv[2]
    workspace = sys.argv[3]
    log_file = sys.argv[4]

    logger.info(f"Processing completion for agent {agent_id} (task: {task_id})")

    success = update_agent_completion(task_id, agent_id, workspace, log_file)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
