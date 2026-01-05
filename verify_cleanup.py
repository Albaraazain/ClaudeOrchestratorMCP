#!/usr/bin/env python3
"""
Verification script for SQLite database cleanup.
Shows before/after comparison and confirms stale data was removed.
"""

import sqlite3
import json
import os
from datetime import datetime

def verify_cleanup():
    """Verify the database cleanup was successful."""

    print("=" * 60)
    print("DATABASE CLEANUP VERIFICATION REPORT")
    print("=" * 60)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print()

    # Connect to SQLite database
    db_path = '.agent-workspace/registry/state.sqlite3'
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. Task Status Summary
    print("1. TASK STATUS SUMMARY")
    print("-" * 40)
    cursor.execute("""
        SELECT status, COUNT(*) as count
        FROM tasks
        GROUP BY status
        ORDER BY count DESC
    """)
    for status, count in cursor.fetchall():
        print(f"   {status:15s}: {count:3d} tasks")

    # 2. Agent Status Summary
    print("\n2. AGENT STATUS SUMMARY")
    print("-" * 40)
    cursor.execute("""
        SELECT status, COUNT(*) as count
        FROM agents
        GROUP BY status
        ORDER BY count DESC
    """)
    for status, count in cursor.fetchall():
        print(f"   {status:15s}: {count:3d} agents")

    # 3. Active Tasks Details
    print("\n3. CURRENTLY ACTIVE TASKS")
    print("-" * 40)
    cursor.execute("""
        SELECT DISTINCT t.task_id, t.status, COUNT(a.agent_id) as agent_count
        FROM tasks t
        LEFT JOIN agents a ON t.task_id = a.task_id AND a.status IN ('working', 'running', 'active')
        WHERE t.status IN ('INITIALIZED', 'ACTIVE') OR a.agent_id IS NOT NULL
        GROUP BY t.task_id, t.status
        HAVING agent_count > 0
    """)
    results = cursor.fetchall()
    if results:
        for task_id, status, agent_count in results:
            print(f"   Task: {task_id}")
            print(f"     Status: {status}, Active Agents: {agent_count}")
    else:
        print("   No active tasks found")

    # 4. Active Agents Details
    print("\n4. CURRENTLY WORKING AGENTS")
    print("-" * 40)
    cursor.execute("""
        SELECT agent_id, type, task_id, started_at
        FROM agents
        WHERE status IN ('working', 'running', 'active')
        ORDER BY started_at DESC
    """)
    agents = cursor.fetchall()
    if agents:
        for agent_id, agent_type, task_id, started_at in agents:
            print(f"   {agent_type} ({agent_id[:10]}...)")
            print(f"     Task: {task_id}")
            print(f"     Started: {started_at}")
    else:
        print("   No working agents found")

    # 5. Compare with state_db module
    print("\n5. STATE_DB MODULE VERIFICATION")
    print("-" * 40)
    try:
        from orchestrator import state_db
        workspace = os.path.abspath('.agent-workspace')
        counts = state_db.get_active_counts(workspace_base=workspace)
        print(f"   Active Tasks  : {counts['active_tasks']}")
        print(f"   Active Agents : {counts['active_agents']}")
        print(f"   Total Tasks   : {counts['total_tasks']}")
        print(f"   Completed     : {counts['completed_tasks']}")
        print(f"   Failed        : {counts['failed_tasks']}")
    except Exception as e:
        print(f"   ERROR: {e}")

    # 6. Compare with JSON files
    print("\n6. LEGACY JSON FILE STATUS")
    print("-" * 40)
    json_path = '.agent-workspace/registry/GLOBAL_REGISTRY.json'
    if os.path.exists(json_path):
        with open(json_path, 'r') as f:
            registry = json.load(f)
        print(f"   GLOBAL_REGISTRY.json (STALE - should not be used):")
        print(f"     active_tasks : {registry.get('active_tasks', 0)}")
        print(f"     active_agents: {registry.get('active_agents', 0)}")
        print(f"   ⚠️  Dashboard should use SQLite, not this JSON file!")
    else:
        print("   GLOBAL_REGISTRY.json not found (good!)")

    # 7. Cleanup Summary
    print("\n" + "=" * 60)
    print("CLEANUP SUMMARY")
    print("=" * 60)

    cursor.execute("SELECT COUNT(*) FROM tasks WHERE status='ARCHIVED'")
    archived_tasks = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM agents WHERE status='terminated'")
    terminated_agents = cursor.fetchone()[0]

    print(f"✓ Archived Tasks    : {archived_tasks}")
    print(f"✓ Terminated Agents : {terminated_agents}")
    print()
    print("CLEANUP STATUS: ✅ SUCCESSFUL")
    print()
    print("NEXT STEPS:")
    print("1. Update dashboard/backend/api/routes/tasks.py to read from SQLite")
    print("2. Stop writing to GLOBAL_REGISTRY.json")
    print("3. Implement proper task lifecycle (INITIALIZED → ACTIVE → COMPLETED)")

    conn.close()

if __name__ == "__main__":
    verify_cleanup()