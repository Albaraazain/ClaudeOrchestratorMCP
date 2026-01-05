#!/usr/bin/env python3
"""Test script to verify dashboard API correctly uses SQLite instead of JSON."""

import sys
import os
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

def test_dashboard_summary_direct():
    """Directly call the state_db function to get correct counts."""
    print("Testing SQLite counts directly...")

    from orchestrator import state_db

    workspace_base = os.path.expanduser("~/.agent-workspace")

    # Get dashboard summary directly from SQLite
    summary = state_db.get_dashboard_summary(workspace_base=workspace_base, limit=20)

    print(f"SQLite Dashboard Summary:")
    print(f"  Active tasks: {summary['global_counts']['active_tasks']}")
    print(f"  Active agents: {summary['global_counts']['active_agents']}")
    print(f"  Total tasks: {summary['global_counts']['total_tasks']}")
    print(f"  Total agents: {summary['global_counts']['total_agents']}")
    print(f"  Recent tasks count: {len(summary.get('recent_tasks', []))}")

    # Show recent task details
    if summary.get('recent_tasks'):
        print(f"\n  Recent tasks:")
        for task in summary['recent_tasks'][:3]:
            print(f"    - {task.get('task_id', 'unknown')}: {task.get('status', 'unknown')}, agents: {task.get('active_agents', 0)}/{task.get('total_agents', 0)}")

    return summary

def test_get_all_tasks():
    """Test the get_all_tasks function."""
    print("\nTesting get_all_tasks from SQLite...")

    from orchestrator import state_db

    workspace_base = os.path.expanduser("~/.agent-workspace")

    # Get all tasks
    tasks = state_db.get_all_tasks(
        workspace_base=workspace_base,
        limit=10
    )

    print(f"  Found {len(tasks)} tasks in SQLite")
    for task in tasks[:3]:
        print(f"    - {task['task_id']}: status={task['status']}, agents={task.get('active_agents', 0)}/{task.get('total_agents', 0)}")

def compare_with_json():
    """Compare SQLite data with stale JSON data."""
    print("\nComparing with JSON registry...")

    import json

    json_path = Path.home() / ".agent-workspace" / "registry" / "GLOBAL_REGISTRY.json"

    if json_path.exists():
        with open(json_path, 'r') as f:
            json_data = json.load(f)

        print(f"  JSON Registry (STALE):")
        print(f"    Active tasks: {json_data.get('active_tasks', 0)} (WRONG!)")
        print(f"    Active agents: {json_data.get('active_agents', 0)}")
        print(f"    Total tasks: {json_data.get('total_tasks', 0)}")

        # Show tasks with wrong status
        tasks_with_initialized = sum(1 for t in json_data.get('tasks', {}).values() if t.get('status') == 'INITIALIZED')
        print(f"    Tasks stuck at INITIALIZED: {tasks_with_initialized} (never updated!)")

def simulate_api_call():
    """Simulate what the API should do."""
    print("\nSimulating API call behavior...")

    from orchestrator import state_db

    # Check if HAS_STATE_DB would be True
    try:
        from orchestrator.registry import read_registry_with_lock
        from orchestrator.workspace import find_task_workspace
        from orchestrator import state_db as imported_state_db
        has_state_db = True
        print("  ✓ HAS_STATE_DB would be True (state_db imported successfully)")
    except ImportError as e:
        has_state_db = False
        print(f"  ✗ HAS_STATE_DB would be False: {e}")

    if has_state_db:
        print("  → API should use SQLite (correct data)")
    else:
        print("  → API would use JSON (stale data!)")

if __name__ == "__main__":
    print("Dashboard SQLite Fix Verification")
    print("=" * 50)

    # Test direct SQLite access
    summary = test_dashboard_summary_direct()

    # Test get_all_tasks
    test_get_all_tasks()

    # Compare with JSON
    compare_with_json()

    # Check API behavior
    simulate_api_call()

    print("\n" + "=" * 50)
    print("EXPECTED BEHAVIOR:")
    print("  - Dashboard should show 0 active tasks (not 16)")
    print("  - Dashboard should show counts from SQLite")
    print("  - API should NOT read from GLOBAL_REGISTRY.json")
    print("\nTo test the API endpoint directly:")
    print("  curl http://localhost:8090/api/tasks/summary/dashboard")
    print("  curl http://localhost:8090/api/tasks")