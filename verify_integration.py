#!/usr/bin/env python3
"""
Integration verification script for SQLite migration.
Checks that all components are properly using SQLite instead of JSON.
"""

import os
import json
from orchestrator import state_db

def main():
    workspace = os.path.abspath('.agent-workspace')
    print("=" * 70)
    print("SQLite Integration Verification Report")
    print("=" * 70)

    # 1. Check state_db functions
    print("\n1. STATE_DB MODULE CHECK:")
    required_functions = [
        'get_all_tasks', 'get_active_counts', 'update_task_status',
        'record_progress', 'get_dashboard_summary', 'cleanup_stale_agents'
    ]
    for func in required_functions:
        has_func = hasattr(state_db, func)
        print(f"   - {func}: {'✅' if has_func else '❌'}")

    # 2. Check SQLite database
    print("\n2. SQLITE DATABASE STATUS:")
    state_db.ensure_db(workspace)
    counts = state_db.get_active_counts(workspace_base=workspace)
    print(f"   - Active tasks: {counts['active_tasks']}")
    print(f"   - Active agents: {counts['active_agents']}")
    print(f"   - Total tasks: {counts['total_tasks']}")
    print(f"   - Completed tasks: {counts['completed_tasks']}")

    # 3. Check JSON registry status
    print("\n3. JSON REGISTRY STATUS (should be reset):")
    registry_path = os.path.join(workspace, 'registry', 'GLOBAL_REGISTRY.json')
    if os.path.exists(registry_path):
        with open(registry_path, 'r') as f:
            data = json.load(f)
            print(f"   - JSON active_tasks: {data.get('active_tasks', 'N/A')}")
            print(f"   - JSON active_agents: {data.get('active_agents', 'N/A')}")
    else:
        print("   - GLOBAL_REGISTRY.json not found")

    # 4. Check imports in key files
    print("\n4. FILE IMPORT CHECK:")
    files_to_check = [
        ('real_mcp_server.py', 'import orchestrator.state_db'),
        ('dashboard/backend/api/routes/tasks.py', 'from orchestrator import state_db')
    ]

    for filepath, import_str in files_to_check:
        if os.path.exists(filepath):
            with open(filepath, 'r') as f:
                content = f.read()
                has_import = import_str in content
                print(f"   - {filepath}: {'✅ imports state_db' if has_import else '❌ missing import'}")
        else:
            print(f"   - {filepath}: ❌ file not found")

    # 5. Check zombie agents
    print("\n5. ZOMBIE AGENT CHECK:")
    summary = state_db.get_dashboard_summary(workspace_base=workspace, limit=100)
    zombie_count = 0
    current_task_agents = 0

    for agent in summary.get('active_agents', []):
        if agent['task_id'] == 'TASK-20260104-222601-e1e90e50':
            current_task_agents += 1
        else:
            zombie_count += 1
            print(f"   - Zombie: {agent['agent_id']} from {agent['task_id'][:20]}... ({agent['status']})")

    print(f"   - Current task agents: {current_task_agents}")
    if zombie_count == 0:
        print("   ✅ No zombie agents found")
    else:
        print(f"   ❌ Total zombie agents: {zombie_count}")

    # 6. Final verdict
    print("\n" + "=" * 70)
    print("FINAL VERDICT:")

    issues = []
    if counts['active_agents'] > 10:  # More than expected for current task
        issues.append("SQLite has stale agent counts")
    if data.get('active_tasks', 0) > 0 or data.get('active_agents', 0) > 0:
        issues.append("JSON registry not fully reset")
    if zombie_count > 0:
        issues.append(f"{zombie_count} zombie agents need cleanup")

    if not issues:
        print("✅ INTEGRATION SUCCESSFUL - SQLite is the single source of truth")
    else:
        print("❌ INTEGRATION INCOMPLETE - Issues found:")
        for issue in issues:
            print(f"   - {issue}")

    print("=" * 70)

if __name__ == '__main__':
    main()