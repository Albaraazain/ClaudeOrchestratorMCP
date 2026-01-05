"""
Test fixtures for state_db testing.

Provides sample data structures for testing reconciliation and state management.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List


def create_sample_task_workspace(base_dir: str, task_id: str) -> str:
    """
    Create a complete task workspace with AGENT_REGISTRY.json and progress files.

    Args:
        base_dir: Base directory for workspace
        task_id: Task ID to create workspace for

    Returns:
        Path to created task workspace
    """
    task_workspace = os.path.join(base_dir, task_id)
    os.makedirs(task_workspace, exist_ok=True)
    progress_dir = os.path.join(task_workspace, "progress")
    os.makedirs(progress_dir, exist_ok=True)

    return task_workspace


def create_agent_registry(task_workspace: str, task_data: Dict[str, Any]) -> str:
    """
    Create AGENT_REGISTRY.json file with sample data.

    Args:
        task_workspace: Path to task workspace
        task_data: Task data dictionary

    Returns:
        Path to created registry file
    """
    registry_path = os.path.join(task_workspace, "AGENT_REGISTRY.json")
    with open(registry_path, "w") as f:
        json.dump(task_data, f, indent=2)
    return registry_path


def create_progress_jsonl(task_workspace: str, agent_id: str, progress_entries: List[Dict[str, Any]]) -> str:
    """
    Create a progress JSONL file for an agent.

    Args:
        task_workspace: Path to task workspace
        agent_id: Agent ID
        progress_entries: List of progress entry dictionaries

    Returns:
        Path to created progress file
    """
    progress_file = os.path.join(task_workspace, "progress", f"{agent_id}_progress.jsonl")

    with open(progress_file, "w") as f:
        for entry in progress_entries:
            f.write(json.dumps(entry) + "\n")

    return progress_file


def get_sample_task_with_phases() -> Dict[str, Any]:
    """
    Get a sample task with multiple phases and agents.

    Returns:
        Complete task data structure
    """
    base_time = datetime.now()

    return {
        "task_id": "TASK-20260104-150000-sample01",
        "workspace": "/workspace/TASK-20260104-150000-sample01",
        "workspace_base": "/workspace",
        "task_description": "Implement comprehensive state management system",
        "status": "ACTIVE",
        "priority": "P0",
        "client_cwd": "/Users/test/project",
        "created_at": base_time.isoformat(),
        "updated_at": base_time.isoformat(),
        "current_phase_index": 1,
        "phases": [
            {
                "id": "phase-investigation",
                "name": "Investigation",
                "status": "COMPLETED",
                "created_at": (base_time - timedelta(hours=2)).isoformat(),
                "started_at": (base_time - timedelta(hours=2)).isoformat(),
                "completed_at": (base_time - timedelta(hours=1)).isoformat(),
            },
            {
                "id": "phase-implementation",
                "name": "Implementation",
                "status": "ACTIVE",
                "created_at": (base_time - timedelta(hours=1)).isoformat(),
                "started_at": (base_time - timedelta(hours=1)).isoformat(),
            },
            {
                "id": "phase-testing",
                "name": "Testing",
                "status": "PENDING",
                "created_at": base_time.isoformat(),
            }
        ],
        "agents": [
            # Phase 0 agents (Investigation - completed)
            {
                "id": "investigator-001",
                "agent_id": "investigator-001",
                "type": "investigator",
                "tmux_session": "tmux-investigator-001",
                "parent": "orchestrator",
                "depth": 1,
                "phase_index": 0,
                "status": "completed",
                "progress": 100,
                "prompt": "Investigate the existing state management implementation",
                "started_at": (base_time - timedelta(hours=2)).isoformat(),
                "completed_at": (base_time - timedelta(hours=1, minutes=30)).isoformat(),
            },
            {
                "id": "analyzer-001",
                "agent_id": "analyzer-001",
                "type": "analyzer",
                "tmux_session": "tmux-analyzer-001",
                "parent": "orchestrator",
                "depth": 1,
                "phase_index": 0,
                "status": "completed",
                "progress": 100,
                "prompt": "Analyze requirements for new state system",
                "started_at": (base_time - timedelta(hours=2)).isoformat(),
                "completed_at": (base_time - timedelta(hours=1, minutes=15)).isoformat(),
            },
            # Phase 1 agents (Implementation - active)
            {
                "id": "builder-001",
                "agent_id": "builder-001",
                "type": "builder",
                "tmux_session": "tmux-builder-001",
                "parent": "orchestrator",
                "depth": 1,
                "phase_index": 1,
                "status": "working",
                "progress": 75,
                "prompt": "Implement SQLite state database",
                "started_at": (base_time - timedelta(hours=1)).isoformat(),
            },
            {
                "id": "builder-002",
                "agent_id": "builder-002",
                "type": "builder",
                "tmux_session": "tmux-builder-002",
                "parent": "orchestrator",
                "depth": 1,
                "phase_index": 1,
                "status": "working",
                "progress": 60,
                "prompt": "Update dashboard API to use SQLite",
                "started_at": (base_time - timedelta(hours=1)).isoformat(),
            },
            {
                "id": "reviewer-001",
                "agent_id": "reviewer-001",
                "type": "reviewer",
                "tmux_session": "tmux-reviewer-001",
                "parent": "orchestrator",
                "depth": 1,
                "phase_index": 1,
                "status": "blocked",
                "progress": 30,
                "prompt": "Review implementation for correctness",
                "started_at": (base_time - timedelta(minutes=45)).isoformat(),
            },
        ]
    }


def get_progress_entries_for_agent(agent_id: str, status_sequence: List[tuple]) -> List[Dict[str, Any]]:
    """
    Generate progress entries for an agent following a status sequence.

    Args:
        agent_id: Agent ID
        status_sequence: List of (status, progress, message) tuples

    Returns:
        List of progress entry dictionaries
    """
    base_time = datetime.now()
    entries = []

    for i, (status, progress, message) in enumerate(status_sequence):
        timestamp = (base_time - timedelta(minutes=len(status_sequence) - i)).isoformat()
        entries.append({
            "timestamp": timestamp,
            "agent_id": agent_id,
            "status": status,
            "progress": progress,
            "message": message,
        })

    return entries


def get_sample_progress_sequences() -> Dict[str, List[tuple]]:
    """
    Get sample progress sequences for different agent scenarios.

    Returns:
        Dictionary mapping scenario names to status sequences
    """
    return {
        "normal_completion": [
            ("running", 0, "Starting agent"),
            ("working", 25, "Analyzing codebase"),
            ("working", 50, "Implementing solution"),
            ("working", 75, "Testing changes"),
            ("completed", 100, "Task completed successfully"),
        ],
        "blocked_then_resolved": [
            ("running", 0, "Starting agent"),
            ("working", 30, "Making progress"),
            ("blocked", 30, "Waiting for dependency"),
            ("blocked", 30, "Still blocked on external resource"),
            ("working", 60, "Dependency resolved, continuing"),
            ("working", 90, "Finalizing implementation"),
            ("completed", 100, "Completed after resolving blockers"),
        ],
        "failure_scenario": [
            ("running", 0, "Starting agent"),
            ("working", 20, "Initial setup"),
            ("working", 40, "Processing data"),
            ("error", 40, "Encountered critical error"),
            ("failed", 40, "Failed to complete task"),
        ],
        "long_running": [
            ("running", 0, "Initializing"),
            ("working", 10, "Step 1 of 10 completed"),
            ("working", 20, "Step 2 of 10 completed"),
            ("working", 30, "Step 3 of 10 completed"),
            ("working", 40, "Step 4 of 10 completed"),
            ("working", 50, "Step 5 of 10 completed"),
            ("working", 60, "Step 6 of 10 completed"),
            ("working", 70, "Step 7 of 10 completed"),
            ("working", 80, "Step 8 of 10 completed"),
            ("working", 90, "Step 9 of 10 completed"),
            ("completed", 100, "All steps completed"),
        ],
    }


def create_complex_task_scenario(base_dir: str) -> Dict[str, Any]:
    """
    Create a complex multi-phase task scenario with various agent states.

    Args:
        base_dir: Base directory for workspace

    Returns:
        Dictionary with task_id, workspace path, and summary statistics
    """
    task_data = get_sample_task_with_phases()
    task_id = task_data["task_id"]

    # Create workspace structure
    task_workspace = create_sample_task_workspace(base_dir, task_id)

    # Update workspace paths in task data
    task_data["workspace"] = task_workspace
    task_data["workspace_base"] = base_dir

    # Create AGENT_REGISTRY.json
    create_agent_registry(task_workspace, task_data)

    # Create progress files for each agent
    progress_sequences = get_sample_progress_sequences()

    # Completed agents (phase 0)
    create_progress_jsonl(
        task_workspace,
        "investigator-001",
        get_progress_entries_for_agent("investigator-001", progress_sequences["normal_completion"])
    )

    create_progress_jsonl(
        task_workspace,
        "analyzer-001",
        get_progress_entries_for_agent("analyzer-001", progress_sequences["normal_completion"])
    )

    # Active agents (phase 1)
    create_progress_jsonl(
        task_workspace,
        "builder-001",
        get_progress_entries_for_agent("builder-001", progress_sequences["long_running"][:8])  # 75% progress
    )

    create_progress_jsonl(
        task_workspace,
        "builder-002",
        get_progress_entries_for_agent("builder-002", progress_sequences["long_running"][:7])  # 60% progress
    )

    create_progress_jsonl(
        task_workspace,
        "reviewer-001",
        get_progress_entries_for_agent("reviewer-001", progress_sequences["blocked_then_resolved"][:4])  # Blocked
    )

    return {
        "task_id": task_id,
        "workspace": task_workspace,
        "statistics": {
            "total_phases": 3,
            "completed_phases": 1,
            "active_phases": 1,
            "total_agents": 5,
            "completed_agents": 2,
            "active_agents": 2,
            "blocked_agents": 1,
        }
    }


def create_edge_case_scenarios(base_dir: str) -> Dict[str, str]:
    """
    Create various edge case scenarios for testing.

    Args:
        base_dir: Base directory for workspaces

    Returns:
        Dictionary mapping scenario names to workspace paths
    """
    scenarios = {}

    # Scenario 1: Empty task with no agents
    empty_task_id = "TASK-empty-001"
    empty_workspace = create_sample_task_workspace(base_dir, empty_task_id)
    create_agent_registry(empty_workspace, {
        "task_id": empty_task_id,
        "workspace": empty_workspace,
        "workspace_base": base_dir,
        "status": "INITIALIZED",
        "agents": []
    })
    scenarios["empty_task"] = empty_workspace

    # Scenario 2: Task with malformed progress files
    malformed_task_id = "TASK-malformed-001"
    malformed_workspace = create_sample_task_workspace(base_dir, malformed_task_id)
    create_agent_registry(malformed_workspace, {
        "task_id": malformed_task_id,
        "workspace": malformed_workspace,
        "workspace_base": base_dir,
        "status": "ACTIVE",
        "agents": [{
            "id": "agent-malformed",
            "agent_id": "agent-malformed",
            "type": "worker",
            "status": "working",
            "progress": 50
        }]
    })

    # Create malformed progress file
    progress_file = os.path.join(malformed_workspace, "progress", "agent-malformed_progress.jsonl")
    with open(progress_file, "w") as f:
        f.write('{"timestamp": "2024-01-01T00:00:00", "status": "working", "progress": 25}\n')
        f.write('INVALID JSON HERE\n')
        f.write('{"corrupted": true\n')  # Incomplete JSON
        f.write('\n')  # Empty line
        f.write('{"timestamp": "2024-01-01T00:01:00", "status": "working", "progress": 50}\n')

    scenarios["malformed_progress"] = malformed_workspace

    # Scenario 3: Task with very large number of agents
    large_task_id = "TASK-large-001"
    large_workspace = create_sample_task_workspace(base_dir, large_task_id)
    large_agents = []

    for i in range(100):
        large_agents.append({
            "id": f"agent-{i:03d}",
            "agent_id": f"agent-{i:03d}",
            "type": "worker",
            "phase_index": i // 20,  # 20 agents per phase
            "status": ["working", "completed", "failed", "blocked"][i % 4],
            "progress": (i * 10) % 101
        })

    create_agent_registry(large_workspace, {
        "task_id": large_task_id,
        "workspace": large_workspace,
        "workspace_base": base_dir,
        "status": "ACTIVE",
        "current_phase_index": 2,
        "agents": large_agents
    })

    # Create progress files for first 10 agents
    for i in range(10):
        agent_id = f"agent-{i:03d}"
        create_progress_jsonl(
            large_workspace,
            agent_id,
            [{"timestamp": datetime.now().isoformat(), "status": "working", "progress": i * 10}]
        )

    scenarios["large_task"] = large_workspace

    return scenarios


if __name__ == "__main__":
    # Example usage for manual testing
    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Creating test scenarios in: {temp_dir}")

        # Create complex scenario
        complex_scenario = create_complex_task_scenario(temp_dir)
        print(f"\nCreated complex task: {complex_scenario['task_id']}")
        print(f"Workspace: {complex_scenario['workspace']}")
        print(f"Statistics: {complex_scenario['statistics']}")

        # Create edge cases
        edge_cases = create_edge_case_scenarios(temp_dir)
        print(f"\nCreated edge case scenarios:")
        for name, path in edge_cases.items():
            print(f"  - {name}: {path}")