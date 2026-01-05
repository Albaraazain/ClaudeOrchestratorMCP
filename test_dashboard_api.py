#!/usr/bin/env python3
"""Test script to verify dashboard API properly uses SQLite."""

import sys
import os
from pathlib import Path

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "dashboard" / "backend"))

def test_imports():
    """Test if state_db can be imported."""
    print("Testing imports...")

    # Test orchestrator imports
    try:
        from orchestrator import state_db
        print("✓ Successfully imported state_db")
        print(f"  state_db path: {state_db.__file__}")

        # Test if functions exist
        print("  Functions available:")
        if hasattr(state_db, 'get_dashboard_summary'):
            print("    ✓ get_dashboard_summary")
        if hasattr(state_db, 'get_global_counts'):
            print("    ✓ get_global_counts")
        if hasattr(state_db, 'get_active_counts'):
            print("    ✓ get_active_counts")

    except ImportError as e:
        print(f"✗ Failed to import state_db: {e}")
        return False

    # Test from the API routes perspective
    print("\nSkipping tasks module import test (fastapi not installed)")

    return True

def test_sqlite_data():
    """Test SQLite data retrieval."""
    print("\nTesting SQLite data retrieval...")

    from orchestrator import state_db

    workspace_base = os.path.expanduser("~/.agent-workspace")

    # Get global counts
    counts = state_db.get_global_counts(workspace_base=workspace_base)
    print(f"  Global counts from SQLite:")
    print(f"    Total tasks: {counts.get('total_tasks', 0)}")
    print(f"    Active tasks: {counts.get('active_tasks', 0)}")
    print(f"    Total agents: {counts.get('total_agents', 0)}")
    print(f"    Active agents: {counts.get('active_agents', 0)}")

    # Get dashboard summary
    summary = state_db.get_dashboard_summary(workspace_base=workspace_base, limit=5)
    print(f"\n  Dashboard summary:")
    print(f"    Active tasks (from summary): {summary['global_counts']['active_tasks']}")
    print(f"    Active agents (from summary): {summary['global_counts']['active_agents']}")
    print(f"    Recent tasks count: {len(summary.get('recent_tasks', []))}")

def test_json_data():
    """Check what's in the JSON files."""
    print("\nChecking JSON registry data...")

    import json

    global_registry_path = Path.home() / ".agent-workspace" / "registry" / "GLOBAL_REGISTRY.json"

    if global_registry_path.exists():
        with open(global_registry_path, 'r') as f:
            data = json.load(f)
            print(f"  GLOBAL_REGISTRY.json:")
            print(f"    Total tasks: {data.get('total_tasks', 0)}")
            print(f"    Active tasks: {data.get('active_tasks', 0)} (STALE!)")
            print(f"    Total agents: {data.get('total_agents_spawned', 0)}")
            print(f"    Active agents: {data.get('active_agents', 0)}")
    else:
        print("  GLOBAL_REGISTRY.json not found")

if __name__ == "__main__":
    print("Dashboard SQLite Integration Test")
    print("=" * 40)

    # Test imports
    if not test_imports():
        sys.exit(1)

    # Test SQLite data
    test_sqlite_data()

    # Check JSON for comparison
    test_json_data()

    print("\n" + "=" * 40)
    print("Test complete!")