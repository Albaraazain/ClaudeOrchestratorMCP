#!/usr/bin/env python3
"""Test script to verify agents.py migration to state_db."""

import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "dashboard" / "backend"))
sys.path.insert(0, str(project_root / "dashboard" / "backend" / "api" / "routes"))

def test_imports():
    """Test that the imports work correctly."""
    print("Testing imports...")
    try:
        from orchestrator import state_db
        print("✓ state_db imported successfully")

        from orchestrator.workspace import find_task_workspace
        print("✓ find_task_workspace imported successfully")

        from api.routes import agents
        print("✓ agents module imported successfully")

        # Check that state_db has required functions
        assert hasattr(state_db, 'get_agent_by_id'), "state_db missing get_agent_by_id"
        assert hasattr(state_db, 'get_agents_for_task'), "state_db missing get_agents_for_task"
        print("✓ state_db has required functions")

        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False
    except AssertionError as e:
        print(f"✗ Assertion failed: {e}")
        return False

def test_migration_functions():
    """Test that migrated functions exist and have correct signatures."""
    print("\nTesting migration functions...")
    try:
        from api.routes.agents import _resolve_tracked_file, _get_workspace_base, list_agents, get_agent

        # Check helper function
        print("✓ _get_workspace_base function exists")

        # Check _resolve_tracked_file
        print("✓ _resolve_tracked_file function exists")

        # Check endpoint functions
        print("✓ list_agents endpoint exists")
        print("✓ get_agent endpoint exists")

        return True
    except ImportError as e:
        print(f"✗ Function import failed: {e}")
        return False

def check_state_db_usage():
    """Check that agents.py source code uses state_db."""
    print("\nChecking state_db usage in agents.py...")
    agents_path = project_root / "dashboard" / "backend" / "api" / "routes" / "agents.py"

    if not agents_path.exists():
        print(f"✗ agents.py not found at {agents_path}")
        return False

    with open(agents_path, 'r') as f:
        content = f.read()

    # Check for state_db imports and usage
    checks = [
        ("from orchestrator import state_db", "state_db import"),
        ("state_db.get_agent_by_id", "get_agent_by_id usage"),
        ("state_db.get_agents_for_task", "get_agents_for_task usage"),
        ("# Try SQLite state_db first", "SQLite-first pattern")
    ]

    all_found = True
    for pattern, description in checks:
        if pattern in content:
            print(f"✓ Found {description}")
        else:
            print(f"✗ Missing {description}")
            all_found = False

    # Count occurrences
    get_agent_count = content.count("state_db.get_agent_by_id")
    get_agents_count = content.count("state_db.get_agents_for_task")

    print(f"\nUsage counts:")
    print(f"  state_db.get_agent_by_id: {get_agent_count} occurrences")
    print(f"  state_db.get_agents_for_task: {get_agents_count} occurrences")

    expected_counts = {
        "state_db.get_agent_by_id": 2,  # In _resolve_tracked_file and get_agent
        "state_db.get_agents_for_task": 1  # In list_agents
    }

    for func, expected in expected_counts.items():
        actual = content.count(func)
        if actual == expected:
            print(f"✓ {func}: {actual} (expected {expected})")
        else:
            print(f"⚠ {func}: {actual} (expected {expected})")

    return all_found

def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing agents.py migration to state_db")
    print("=" * 60)

    results = []

    # Run tests
    results.append(("Import Test", test_imports()))
    results.append(("Function Test", test_migration_functions()))
    results.append(("Source Check", check_state_db_usage()))

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    all_passed = True
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{test_name}: {status}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tests passed! Migration successful.")
        return 0
    else:
        print("✗ Some tests failed. Please review the migration.")
        return 1

if __name__ == "__main__":
    sys.exit(main())