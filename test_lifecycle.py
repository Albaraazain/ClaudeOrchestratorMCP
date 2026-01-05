#!/usr/bin/env python3
"""Test script to verify task/agent lifecycle transitions work correctly."""

import os
import sys
import sqlite3
from pathlib import Path

# Add orchestrator to path
orchestrator_path = Path(__file__).parent
sys.path.insert(0, str(orchestrator_path))

from orchestrator import state_db

def test_lifecycle_transitions():
    """Test the lifecycle transition functions."""
    print("Testing Task/Agent Lifecycle Transitions\n")
    print("=" * 50)

    # Use test workspace
    workspace_base = "/tmp/test_workspace"
    os.makedirs(f"{workspace_base}/registry", exist_ok=True)

    # Initialize database
    db_path = state_db.ensure_db(workspace_base)
    print(f"✓ Database initialized at: {db_path}")

    # Connect to database for test setup
    conn = state_db._connect(db_path)

    # Create a test task
    test_task_id = "TEST-20260104-123456-test"
    conn.execute("""
        INSERT INTO tasks (task_id, workspace, workspace_base, description, status,
                          priority, created_at, updated_at, current_phase_index)
        VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'), 0)
    """, (test_task_id, f"{workspace_base}/{test_task_id}", workspace_base,
          "Test task for lifecycle", "INITIALIZED", "P2"))

    print(f"✓ Created test task: {test_task_id}")

    # Test 1: Transition task to ACTIVE
    print("\n1. Testing transition_task_to_active...")
    result = state_db.transition_task_to_active(workspace_base=workspace_base, task_id=test_task_id)
    print(f"   Result: {result}")

    # Verify status changed
    row = conn.execute("SELECT status FROM tasks WHERE task_id=?", (test_task_id,)).fetchone()
    print(f"   Task status: {row['status']}")
    assert row["status"] == "ACTIVE", "Task should be ACTIVE"
    print("   ✓ Task successfully transitioned to ACTIVE")

    # Test 2: Try transitioning again (should fail)
    print("\n2. Testing duplicate transition (should fail)...")
    result = state_db.transition_task_to_active(workspace_base=workspace_base, task_id=test_task_id)
    print(f"   Result: {result}")
    assert result == False, "Should not transition already active task"
    print("   ✓ Correctly prevented duplicate transition")

    # Test 3: Add test agents
    print("\n3. Adding test agents...")
    agent_ids = ["agent-1", "agent-2", "agent-3"]
    for agent_id in agent_ids:
        conn.execute("""
            INSERT INTO agents (agent_id, task_id, type, status, progress,
                              started_at, last_update, phase_index)
            VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'), 0)
        """, (agent_id, test_task_id, "test_agent", "working", 50))
    print(f"   ✓ Added {len(agent_ids)} agents")

    # Test 4: Get active agent count
    print("\n4. Testing get_active_agent_count...")
    active_count = state_db.get_active_agent_count(workspace_base=workspace_base, task_id=test_task_id)
    print(f"   Active agents: {active_count}")
    assert active_count == 3, f"Should have 3 active agents, got {active_count}"
    print("   ✓ Active count correct")

    # Test 5: Mark agent as terminal
    print("\n5. Testing mark_agent_terminal...")
    result = state_db.mark_agent_terminal(
        workspace_base=workspace_base,
        agent_id="agent-1",
        status="completed",
        reason="Test completion",
        auto_rollup=False  # Don't auto-transition task yet
    )
    print(f"   Result: {result}")
    assert result.get("transitioned_to") == "completed", "Agent should be completed"
    print("   ✓ Agent marked as completed")

    # Verify active count decreased
    active_count = state_db.get_active_agent_count(workspace_base=workspace_base, task_id=test_task_id)
    print(f"   Active agents after completion: {active_count}")
    assert active_count == 2, f"Should have 2 active agents, got {active_count}"

    # Test 6: Check task completion (should be False)
    print("\n6. Testing check_task_completion (not all done)...")
    all_done = state_db.check_task_completion(workspace_base=workspace_base, task_id=test_task_id)
    print(f"   All agents done: {all_done}")
    assert all_done == False, "Task should not be complete yet"
    print("   ✓ Correctly detected incomplete task")

    # Test 7: Mark remaining agents as terminal
    print("\n7. Marking remaining agents as terminal...")
    state_db.mark_agent_terminal(
        workspace_base=workspace_base,
        agent_id="agent-2",
        status="completed",
        auto_rollup=False
    )
    state_db.mark_agent_terminal(
        workspace_base=workspace_base,
        agent_id="agent-3",
        status="failed",
        reason="Test failure",
        auto_rollup=False
    )
    print("   ✓ All agents marked terminal")

    # Test 8: Check task completion (should be True now)
    print("\n8. Testing check_task_completion (all done)...")
    all_done = state_db.check_task_completion(workspace_base=workspace_base, task_id=test_task_id)
    print(f"   All agents done: {all_done}")
    assert all_done == True, "Task should be complete now"
    print("   ✓ Correctly detected complete task")

    # Test 9: Transition task to COMPLETED
    print("\n9. Testing transition_task_to_completed...")
    result = state_db.transition_task_to_completed(workspace_base=workspace_base, task_id=test_task_id)
    print(f"   Result: {result}")

    # Verify status changed
    row = conn.execute("SELECT status FROM tasks WHERE task_id=?", (test_task_id,)).fetchone()
    print(f"   Task status: {row['status']}")
    assert row["status"] == "COMPLETED", "Task should be COMPLETED"
    print("   ✓ Task successfully transitioned to COMPLETED")

    # Test 10: Get global active counts
    print("\n10. Testing get_global_active_counts...")
    global_counts = state_db.get_global_active_counts(workspace_base=workspace_base)
    print(f"   Global counts: {global_counts}")
    assert global_counts["active_tasks"] == 0, "Should have 0 active tasks"
    assert global_counts["active_agents"] == 0, "Should have 0 active agents"
    print("   ✓ Global counts correct")

    # Test 11: Get phase agent counts
    print("\n11. Testing get_phase_agent_counts...")
    phase_counts = state_db.get_phase_agent_counts(
        workspace_base=workspace_base,
        task_id=test_task_id,
        phase_index=0
    )
    print(f"   Phase counts: {phase_counts}")
    assert phase_counts["total"] == 3, "Should have 3 total agents"
    assert phase_counts["active"] == 0, "Should have 0 active agents"
    assert phase_counts["completed"] == 2, "Should have 2 completed agents"
    assert phase_counts["failed"] == 1, "Should have 1 failed agent"
    print("   ✓ Phase counts correct")

    conn.close()

    print("\n" + "=" * 50)
    print("✅ ALL TESTS PASSED!")
    print("\nLifecycle transition functions are working correctly.")
    print("Tasks properly transition: INITIALIZED -> ACTIVE -> COMPLETED")
    print("Agent counts are accurately tracked in SQLite.")

if __name__ == "__main__":
    test_lifecycle_transitions()