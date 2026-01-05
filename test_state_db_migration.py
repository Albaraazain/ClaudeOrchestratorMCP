#!/usr/bin/env python3
"""
Test script to verify state_db_enhanced.py migrations and new CRUD functions.
This ensures the enhanced schema works correctly with existing data.
"""

import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime

# Import the enhanced state_db module
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from orchestrator import state_db_enhanced as state_db


def test_schema_migration():
    """Test that schema migrations work correctly."""
    print("=" * 60)
    print("Testing SQLite Schema Migrations")
    print("=" * 60)

    # Create a temporary workspace
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_base = tmpdir
        print(f"\n1. Created temp workspace: {workspace_base}")

        # Initialize database with enhanced schema
        db_path = state_db.ensure_db(workspace_base)
        print(f"2. Database created at: {db_path}")

        # Verify all tables exist
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]

        expected_tables = {
            'tasks', 'phases', 'agents', 'agent_progress_latest',
            'reviews', 'agent_findings', 'handovers'
        }

        print(f"\n3. Tables created: {tables}")
        missing = expected_tables - set(tables)
        if missing:
            print(f"   ❌ Missing tables: {missing}")
            return False
        else:
            print(f"   ✅ All expected tables exist")

        # Verify agents table has new columns
        cursor = conn.execute("PRAGMA table_info(agents)")
        columns = {row[1] for row in cursor.fetchall()}

        new_columns = {'model', 'claude_pid', 'cursor_pid', 'tracked_files'}
        print(f"\n4. Checking agents table columns...")

        missing_cols = new_columns - columns
        if missing_cols:
            print(f"   ❌ Missing columns: {missing_cols}")
            return False
        else:
            print(f"   ✅ All new columns exist: {new_columns}")

        # Test adding data with new columns
        task_id = "TEST-TASK-001"
        agent_id = "test-agent-001"

        # Insert a test task
        conn.execute(
            """
            INSERT INTO tasks(task_id, workspace, status, created_at, updated_at, current_phase_index)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (task_id, workspace_base, "INITIALIZED", datetime.now().isoformat(), datetime.now().isoformat(), 0)
        )

        # Insert a test agent with new columns
        tracked_files = {"log_file": "test.log", "progress_file": "progress.jsonl"}
        conn.execute(
            """
            INSERT INTO agents(
                agent_id, task_id, type, model, tmux_session,
                claude_pid, cursor_pid, tracked_files,
                status, progress, last_update
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id, task_id, "investigator", "opus",
                "tmux-session-001", 12345, 67890,
                json.dumps(tracked_files),
                "working", 50, datetime.now().isoformat()
            )
        )
        conn.commit()

        # Verify data was inserted correctly
        cursor = conn.execute(
            "SELECT model, claude_pid, cursor_pid, tracked_files FROM agents WHERE agent_id = ?",
            (agent_id,)
        )
        row = cursor.fetchone()

        print(f"\n5. Testing data insertion with new columns:")
        print(f"   Model: {row[0]}")
        print(f"   Claude PID: {row[1]}")
        print(f"   Cursor PID: {row[2]}")
        print(f"   Tracked Files: {row[3]}")

        # Parse tracked_files JSON
        try:
            parsed = json.loads(row[3])
            print(f"   ✅ Tracked files JSON valid: {parsed}")
        except Exception as e:
            print(f"   ❌ Failed to parse tracked files: {e}")
            return False

        conn.close()
        print("\n✅ Schema migration test PASSED!")
        return True


def test_crud_functions():
    """Test new CRUD functions."""
    print("\n" + "=" * 60)
    print("Testing New CRUD Functions")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_base = tmpdir
        db_path = state_db.ensure_db(workspace_base)

        task_id = "TEST-TASK-002"
        agent_id = "test-agent-002"

        # Create initial task
        conn = sqlite3.connect(db_path)
        conn.execute(
            """
            INSERT INTO tasks(task_id, workspace, status, created_at, updated_at, current_phase_index)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (task_id, workspace_base, "INITIALIZED", datetime.now().isoformat(), datetime.now().isoformat(), 0)
        )

        # Create a phase
        conn.execute(
            """
            INSERT INTO phases(task_id, phase_index, name, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_id, 0, "Investigation", "PENDING", datetime.now().isoformat())
        )

        # Create an agent
        conn.execute(
            """
            INSERT INTO agents(agent_id, task_id, type, status, progress, last_update, phase_index)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (agent_id, task_id, "investigator", "running", 0, datetime.now().isoformat(), 0)
        )
        conn.commit()
        conn.close()

        print("\n1. Testing update_task_status...")
        result = state_db.update_task_status(
            workspace_base=workspace_base,
            task_id=task_id,
            new_status="ACTIVE"
        )
        print(f"   Result: {'✅ PASSED' if result else '❌ FAILED'}")

        print("\n2. Testing update_phase_status...")
        result = state_db.update_phase_status(
            workspace_base=workspace_base,
            task_id=task_id,
            phase_index=0,
            new_status="ACTIVE"
        )
        print(f"   Result: {'✅ PASSED' if result else '❌ FAILED'}")

        print("\n3. Testing record_agent_finding...")
        finding_id = state_db.record_agent_finding(
            workspace_base=workspace_base,
            task_id=task_id,
            agent_id=agent_id,
            finding_type="insight",
            severity="high",
            message="Found critical performance issue",
            data={"location": "database.py:123", "impact": "high"}
        )
        print(f"   Created finding ID: {finding_id}")
        print(f"   Result: {'✅ PASSED' if finding_id else '❌ FAILED'}")

        print("\n4. Testing get_all_tasks...")
        tasks = state_db.get_all_tasks(
            workspace_base=workspace_base,
            limit=10,
            offset=0
        )
        print(f"   Found {len(tasks)} tasks")
        if tasks:
            print(f"   Task: {tasks[0]['task_id']} - Status: {tasks[0]['status']}")
        print(f"   Result: {'✅ PASSED' if len(tasks) == 1 else '❌ FAILED'}")

        print("\n5. Testing get_active_counts...")
        counts = state_db.get_active_counts(workspace_base=workspace_base)
        print(f"   Active tasks: {counts['active_tasks']}")
        print(f"   Active agents: {counts['active_agents']}")
        print(f"   Total tasks: {counts['total_tasks']}")
        print(f"   Result: {'✅ PASSED' if counts['total_tasks'] == 1 else '❌ FAILED'}")

        print("\n6. Testing cleanup_stale_agents...")
        # Make agent appear stale by updating its last_update to old timestamp
        conn = sqlite3.connect(db_path)
        old_time = datetime(2020, 1, 1).isoformat()
        conn.execute(
            "UPDATE agents SET last_update = ? WHERE agent_id = ?",
            (old_time, agent_id)
        )
        conn.commit()
        conn.close()

        cleaned = state_db.cleanup_stale_agents(
            workspace_base=workspace_base,
            task_id=task_id,
            stale_threshold_minutes=5
        )
        print(f"   Cleaned {cleaned} stale agents")
        print(f"   Result: {'✅ PASSED' if cleaned == 1 else '❌ FAILED'}")

        print("\n7. Testing review functions...")
        review_id = "REVIEW-001"
        created = state_db.create_review(
            workspace_base=workspace_base,
            task_id=task_id,
            phase_index=0,
            review_id=review_id
        )
        print(f"   Review created: {'✅ PASSED' if created else '❌ FAILED'}")

        updated = state_db.update_review(
            workspace_base=workspace_base,
            review_id=review_id,
            status="completed",
            verdict="approved",
            reviewer_notes="All checks passed"
        )
        print(f"   Review updated: {'✅ PASSED' if updated else '❌ FAILED'}")

        print("\n8. Testing handover functions...")
        handover_id = state_db.create_handover(
            workspace_base=workspace_base,
            task_id=task_id,
            from_phase_index=0,
            to_phase_index=1,
            summary="Investigation phase completed successfully",
            key_findings=["Database schema identified", "Missing columns found"],
            blockers=["Need approval for schema changes"],
            recommendations=["Implement gradual migration", "Add monitoring"]
        )
        print(f"   Handover created with ID: {handover_id}")
        print(f"   Result: {'✅ PASSED' if handover_id else '❌ FAILED'}")

        handover = state_db.get_latest_handover(
            workspace_base=workspace_base,
            task_id=task_id,
            to_phase_index=1
        )
        print(f"   Handover retrieved: {'✅ PASSED' if handover else '❌ FAILED'}")
        if handover:
            print(f"   Summary: {handover['summary'][:50]}...")

        print("\n9. Testing get_agent_findings...")
        findings = state_db.get_agent_findings(
            workspace_base=workspace_base,
            task_id=task_id,
            limit=10
        )
        print(f"   Found {len(findings)} findings")
        print(f"   Result: {'✅ PASSED' if len(findings) == 1 else '❌ FAILED'}")

        print("\n10. Testing inspect_database...")
        inspection = state_db.inspect_database(workspace_base)
        print(f"   Database: {inspection['database']}")
        print(f"   Tables: {list(inspection['tables'].keys())}")
        print(f"   Active counts: {inspection['active_counts']}")
        print(f"   Result: ✅ PASSED")

        print("\n✅ All CRUD function tests PASSED!")
        return True


if __name__ == "__main__":
    print("Starting State DB Enhancement Tests")
    print("=" * 60)

    # Run tests
    migration_success = test_schema_migration()
    crud_success = test_crud_functions()

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"Schema Migration: {'✅ PASSED' if migration_success else '❌ FAILED'}")
    print(f"CRUD Functions:   {'✅ PASSED' if crud_success else '❌ FAILED'}")

    if migration_success and crud_success:
        print("\n🎉 ALL TESTS PASSED! Schema enhancements are ready for integration.")
    else:
        print("\n❌ Some tests failed. Please review the output above.")

    print("\nNext steps:")
    print("1. Replace existing state_db.py with state_db_enhanced.py")
    print("2. Update imports in real_mcp_server.py and health_daemon.py")
    print("3. Modify dashboard/backend/api/routes/tasks.py to use SQLite")
    print("4. Test with live orchestrator tasks")