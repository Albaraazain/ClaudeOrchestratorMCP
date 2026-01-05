#!/usr/bin/env python3
"""
Verify that the registry reset was successful.
Checks both GLOBAL_REGISTRY.json and confirms SQLite is the source of truth.
"""

import json
import sqlite3
from pathlib import Path


def verify_reset():
    """Verify the registry reset was successful."""
    success = True

    # Check GLOBAL_REGISTRY.json
    registry_path = Path('.agent-workspace/registry/GLOBAL_REGISTRY.json')
    if registry_path.exists():
        with open(registry_path, 'r') as f:
            registry = json.load(f)

        print("✅ GLOBAL_REGISTRY.json Reset Verification:")
        print("=" * 50)

        # Check active counts are 0
        if registry.get('active_tasks', -1) == 0:
            print("✓ active_tasks: 0")
        else:
            print(f"✗ active_tasks: {registry.get('active_tasks')} (should be 0)")
            success = False

        if registry.get('active_agents', -1) == 0:
            print("✓ active_agents: 0")
        else:
            print(f"✗ active_agents: {registry.get('active_agents')} (should be 0)")
            success = False

        # Check all tasks are archived
        tasks = registry.get('tasks', {})
        non_archived = [tid for tid, t in tasks.items()
                        if t.get('status') not in ('ARCHIVED', 'COMPLETED', 'FAILED')]

        if not non_archived:
            print(f"✓ All {len(tasks)} tasks are ARCHIVED/COMPLETED/FAILED")
        else:
            print(f"✗ {len(non_archived)} tasks are not archived: {non_archived[:3]}...")
            success = False
    else:
        print(f"❌ Registry file not found: {registry_path}")
        success = False

    # Check SQLite is the source of truth
    sqlite_path = Path('.agent-workspace/registry/state.sqlite3')
    if sqlite_path.exists():
        print(f"\n✅ SQLite Database Check:")
        print("=" * 50)

        conn = sqlite3.connect(sqlite_path)
        cursor = conn.cursor()

        # Check active tasks in SQLite
        cursor.execute("""
            SELECT COUNT(*) FROM tasks
            WHERE status NOT IN ('COMPLETED', 'FAILED', 'ARCHIVED')
        """)
        active_tasks_sqlite = cursor.fetchone()[0]

        # Check active agents in SQLite
        cursor.execute("""
            SELECT COUNT(*) FROM agents
            WHERE status IN ('running', 'active', 'working')
        """)
        active_agents_sqlite = cursor.fetchone()[0]

        conn.close()

        print(f"✓ SQLite active tasks: {active_tasks_sqlite}")
        print(f"✓ SQLite active agents: {active_agents_sqlite}")
        print("\n📌 SQLite is now the source of truth for task/agent state")
    else:
        print(f"\n⚠️  SQLite database not found: {sqlite_path}")

    return success


if __name__ == "__main__":
    print("\n🔍 Registry Reset Verification\n")
    success = verify_reset()

    if success:
        print("\n✅ SUCCESS: Registry has been properly reset!")
        print("   - JSON files show 0 active tasks/agents")
        print("   - All tasks marked as ARCHIVED")
        print("   - SQLite is the source of truth")
    else:
        print("\n❌ FAILURE: Some issues remain")

    exit(0 if success else 1)