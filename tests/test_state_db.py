"""
Comprehensive test suite for state_db.py functions.

Tests cover:
- Schema creation and table existence
- record_progress updates
- reconcile_task_workspace synchronization from JSONL
- load_task_snapshot data retrieval
- Task/agent status transitions
- Count queries accuracy
- Edge cases and error handling
"""

import json
import os
import sqlite3
import tempfile
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any
import pytest

# Add parent directory to path for imports
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator.state_db import (
    ensure_db,
    record_progress,
    reconcile_task_workspace,
    load_task_snapshot,
    load_phase_snapshot,
    load_recent_progress_latest,
    normalize_agent_status,
    get_state_db_path,
    AGENT_TERMINAL_STATUSES,
    AGENT_ACTIVE_STATUSES,
    _connect,
    _init_db,
)


class TestStateDB:
    """Test suite for state_db.py functionality."""

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory."""
        temp_dir = tempfile.mkdtemp(prefix="test_state_db_")
        yield temp_dir
        # Cleanup after test
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def sample_task_data(self) -> Dict[str, Any]:
        """Sample task data for testing."""
        return {
            "task_id": "TASK-20260104-123456-test001",
            "workspace": "test_workspace",
            "workspace_base": "test_base",
            "task_description": "Test task for state_db",
            "status": "INITIALIZED",
            "priority": "P1",
            "client_cwd": "/test/path",
            "created_at": datetime.now().isoformat(),
            "current_phase_index": 0,
            "phases": [
                {
                    "id": "phase-1",
                    "name": "Investigation",
                    "status": "ACTIVE",
                    "created_at": datetime.now().isoformat(),
                },
                {
                    "id": "phase-2",
                    "name": "Implementation",
                    "status": "PENDING",
                    "created_at": datetime.now().isoformat(),
                }
            ],
            "agents": [
                {
                    "id": "agent-001",
                    "agent_id": "agent-001",
                    "type": "investigator",
                    "tmux_session": "tmux-agent-001",
                    "parent": "orchestrator",
                    "depth": 1,
                    "phase_index": 0,
                    "status": "working",
                    "progress": 50,
                    "prompt": "Investigate the codebase",
                    "started_at": datetime.now().isoformat(),
                },
                {
                    "id": "agent-002",
                    "agent_id": "agent-002",
                    "type": "builder",
                    "tmux_session": "tmux-agent-002",
                    "parent": "orchestrator",
                    "depth": 1,
                    "phase_index": 0,
                    "status": "completed",
                    "progress": 100,
                    "prompt": "Build the solution",
                    "started_at": datetime.now().isoformat(),
                    "completed_at": datetime.now().isoformat(),
                }
            ]
        }

    def test_schema_creation(self, temp_workspace):
        """Test that all required tables are created correctly."""
        db_path = ensure_db(temp_workspace)

        # Verify database file exists
        assert os.path.exists(db_path)

        # Connect and check tables
        conn = _connect(db_path)
        try:
            # Check all tables exist
            cursor = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table'
                ORDER BY name
            """)
            tables = [row[0] for row in cursor.fetchall()]

            expected_tables = ['agent_progress_latest', 'agents', 'phases', 'tasks']
            assert tables == expected_tables, f"Expected tables {expected_tables}, got {tables}"

            # Verify tasks table columns
            cursor = conn.execute("PRAGMA table_info(tasks)")
            task_columns = {row[1] for row in cursor.fetchall()}
            expected_task_columns = {
                'task_id', 'workspace', 'workspace_base', 'description',
                'status', 'priority', 'client_cwd', 'created_at',
                'updated_at', 'current_phase_index'
            }
            assert expected_task_columns.issubset(task_columns)

            # Verify agents table columns
            cursor = conn.execute("PRAGMA table_info(agents)")
            agent_columns = {row[1] for row in cursor.fetchall()}
            expected_agent_columns = {
                'agent_id', 'task_id', 'type', 'tmux_session', 'parent',
                'depth', 'phase_index', 'started_at', 'completed_at',
                'status', 'progress', 'last_update', 'prompt_preview'
            }
            assert expected_agent_columns.issubset(agent_columns)

            # Verify indexes exist
            cursor = conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='index' AND name LIKE 'idx_%'
            """)
            indexes = [row[0] for row in cursor.fetchall()]
            assert 'idx_agents_task' in indexes
            assert 'idx_agents_task_phase' in indexes

        finally:
            conn.close()

    def test_record_progress_updates_both_tables(self, temp_workspace):
        """Test that record_progress updates both agent_progress_latest and agents tables."""
        db_path = ensure_db(temp_workspace)

        # First insert a task and agent
        conn = _connect(db_path)
        try:
            task_id = "TASK-test-001"
            agent_id = "agent-test-001"

            # Insert task
            conn.execute("""
                INSERT INTO tasks(task_id, workspace, workspace_base, description, status, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
            """, (task_id, "workspace", temp_workspace, "Test", "INITIALIZED",
                  datetime.now().isoformat(), datetime.now().isoformat()))

            # Insert agent
            conn.execute("""
                INSERT INTO agents(agent_id, task_id, type, status, progress, started_at)
                VALUES(?, ?, ?, ?, ?, ?)
            """, (agent_id, task_id, "tester", "working", 0, datetime.now().isoformat()))

        finally:
            conn.close()

        # Now test record_progress
        timestamp = datetime.now().isoformat()
        record_progress(
            workspace_base=temp_workspace,
            task_id=task_id,
            agent_id=agent_id,
            timestamp=timestamp,
            status="working",
            message="Processing data",
            progress=75
        )

        # Verify updates
        conn = _connect(db_path)
        try:
            # Check agent_progress_latest
            row = conn.execute("""
                SELECT status, progress, message FROM agent_progress_latest
                WHERE task_id=? AND agent_id=?
            """, (task_id, agent_id)).fetchone()

            assert row is not None
            assert row[0] == "working"
            assert row[1] == 75
            assert row[2] == "Processing data"

            # Check agents table
            row = conn.execute("""
                SELECT status, progress FROM agents
                WHERE agent_id=? AND task_id=?
            """, (agent_id, task_id)).fetchone()

            assert row is not None
            assert row[0] == "working"
            assert row[1] == 75

        finally:
            conn.close()

    def test_reconcile_task_workspace_from_jsonl(self, temp_workspace, sample_task_data):
        """Test reconcile_task_workspace syncs correctly from JSONL files."""
        task_id = sample_task_data["task_id"]

        # Create task workspace structure
        task_workspace = os.path.join(temp_workspace, task_id)
        os.makedirs(task_workspace, exist_ok=True)
        progress_dir = os.path.join(task_workspace, "progress")
        os.makedirs(progress_dir, exist_ok=True)

        # Create AGENT_REGISTRY.json
        registry_path = os.path.join(task_workspace, "AGENT_REGISTRY.json")
        with open(registry_path, "w") as f:
            json.dump(sample_task_data, f)

        # Create progress JSONL files for agents
        for agent in sample_task_data["agents"]:
            agent_id = agent["agent_id"]
            progress_file = os.path.join(progress_dir, f"{agent_id}_progress.jsonl")

            # Write multiple progress entries
            with open(progress_file, "w") as f:
                # Entry 1: starting
                f.write(json.dumps({
                    "timestamp": datetime.now().isoformat(),
                    "status": "working",
                    "progress": 25,
                    "message": "Starting work"
                }) + "\n")

                # Entry 2: progress update
                f.write(json.dumps({
                    "timestamp": datetime.now().isoformat(),
                    "status": "working",
                    "progress": agent["progress"],
                    "message": "Making progress"
                }) + "\n")

                # Entry 3: final status
                if agent["status"] == "completed":
                    f.write(json.dumps({
                        "timestamp": datetime.now().isoformat(),
                        "status": "completed",
                        "progress": 100,
                        "message": "Work completed"
                    }) + "\n")

        # Run reconciliation
        db_path = reconcile_task_workspace(task_workspace)
        assert db_path is not None

        # Verify data was materialized correctly
        conn = _connect(db_path)
        try:
            # Check task
            row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            assert row is not None
            assert dict(row)["task_id"] == task_id
            assert dict(row)["status"] == "INITIALIZED"
            assert dict(row)["priority"] == "P1"

            # Check phases
            phases = conn.execute("""
                SELECT * FROM phases WHERE task_id=? ORDER BY phase_index
            """, (task_id,)).fetchall()
            assert len(phases) == 2
            assert dict(phases[0])["name"] == "Investigation"
            assert dict(phases[1])["name"] == "Implementation"

            # Check agents with JSONL-derived status
            agents = conn.execute("""
                SELECT agent_id, status, progress FROM agents WHERE task_id=?
            """, (task_id,)).fetchall()

            agent_dict = {dict(row)["agent_id"]: dict(row) for row in agents}
            assert len(agent_dict) == 2

            # Agent 002 should be completed from JSONL
            assert agent_dict["agent-002"]["status"] == "completed"
            assert agent_dict["agent-002"]["progress"] == 100

            # Check agent_progress_latest
            progress = conn.execute("""
                SELECT agent_id, status, progress, message FROM agent_progress_latest WHERE task_id=?
            """, (task_id,)).fetchall()

            progress_dict = {dict(row)["agent_id"]: dict(row) for row in progress}
            assert "agent-002" in progress_dict
            assert progress_dict["agent-002"]["message"] == "Work completed"

        finally:
            conn.close()

    def test_load_task_snapshot_returns_correct_structure(self, temp_workspace, sample_task_data):
        """Test load_task_snapshot returns properly structured data."""
        # Setup database with sample data
        task_id = sample_task_data["task_id"]
        db_path = ensure_db(temp_workspace)

        conn = _connect(db_path)
        try:
            # Insert task
            conn.execute("""
                INSERT INTO tasks(task_id, workspace, workspace_base, description, status, priority,
                                 client_cwd, created_at, updated_at, current_phase_index)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id, "workspace", temp_workspace, "Test task", "ACTIVE", "P1",
                "/test", datetime.now().isoformat(), datetime.now().isoformat(), 0
            ))

            # Insert phases
            for idx, phase in enumerate(sample_task_data["phases"]):
                conn.execute("""
                    INSERT INTO phases(task_id, phase_index, phase_id, name, status, created_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                """, (task_id, idx, phase["id"], phase["name"], phase["status"], phase["created_at"]))

            # Insert agents with various statuses
            test_agents = [
                ("agent-active-1", "working", 50),
                ("agent-active-2", "blocked", 30),
                ("agent-completed-1", "completed", 100),
                ("agent-failed-1", "failed", 20),
                ("agent-error-1", "error", 15),
            ]

            for agent_id, status, progress in test_agents:
                conn.execute("""
                    INSERT INTO agents(agent_id, task_id, type, status, progress, phase_index, started_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                """, (agent_id, task_id, "tester", status, progress, 0, datetime.now().isoformat()))

        finally:
            conn.close()

        # Load snapshot
        snapshot = load_task_snapshot(workspace_base=temp_workspace, task_id=task_id)

        # Verify structure
        assert snapshot is not None
        assert snapshot["task_id"] == task_id
        assert snapshot["status"] == "ACTIVE"

        # Check phases
        assert "phases" in snapshot
        assert len(snapshot["phases"]) == 2
        assert snapshot["phases"][0]["name"] == "Investigation"

        # Check agents
        assert "agents" in snapshot
        assert len(snapshot["agents"]) == 5

        # Check counts are accurate
        assert "counts" in snapshot
        counts = snapshot["counts"]
        assert counts["total"] == 5
        assert counts["active"] == 2  # working + blocked
        assert counts["completed"] == 1
        assert counts["terminal"] == 3  # completed + failed + error

    def test_status_transitions_work_correctly(self, temp_workspace):
        """Test that agent status transitions are handled correctly."""
        db_path = ensure_db(temp_workspace)
        task_id = "TASK-transition-test"
        agent_id = "agent-transition-test"

        # Setup initial state
        conn = _connect(db_path)
        try:
            conn.execute("""
                INSERT INTO tasks(task_id, workspace, workspace_base, status, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
            """, (task_id, "workspace", temp_workspace, "INITIALIZED",
                  datetime.now().isoformat(), datetime.now().isoformat()))

            conn.execute("""
                INSERT INTO agents(agent_id, task_id, type, status, progress, started_at)
                VALUES(?, ?, ?, ?, ?, ?)
            """, (agent_id, task_id, "worker", "running", 0, datetime.now().isoformat()))
        finally:
            conn.close()

        # Test status transitions
        transitions = [
            ("running", 0, "running"),
            ("working", 25, "working"),
            ("working", 50, "working"),
            ("blocked", 50, "blocked"),
            ("working", 75, "working"),
            ("completed", 100, "completed"),
        ]

        for status, progress, expected_status in transitions:
            record_progress(
                workspace_base=temp_workspace,
                task_id=task_id,
                agent_id=agent_id,
                timestamp=datetime.now().isoformat(),
                status=status,
                message=f"Status: {status}",
                progress=progress
            )

            # Verify status
            conn = _connect(db_path)
            try:
                row = conn.execute("""
                    SELECT status, progress FROM agents WHERE agent_id=?
                """, (agent_id,)).fetchone()

                assert row[0] == expected_status, f"Expected {expected_status}, got {row[0]}"
                assert row[1] == progress

                # Check completed_at is set when status becomes completed
                if expected_status == "completed":
                    row = conn.execute("""
                        SELECT completed_at FROM agents WHERE agent_id=?
                    """, (agent_id,)).fetchone()
                    assert row[0] is not None, "completed_at should be set for completed agents"

            finally:
                conn.close()

    def test_count_queries_accuracy(self, temp_workspace):
        """Test that count queries return accurate values."""
        db_path = ensure_db(temp_workspace)
        task_id = "TASK-count-test"

        # Create agents with specific statuses for testing counts
        agent_configs = [
            ("agent-w1", "working", 40),
            ("agent-w2", "working", 60),
            ("agent-b1", "blocked", 30),
            ("agent-c1", "completed", 100),
            ("agent-c2", "completed", 100),
            ("agent-c3", "completed", 100),
            ("agent-f1", "failed", 20),
            ("agent-e1", "error", 10),
            ("agent-t1", "terminated", 50),
        ]

        conn = _connect(db_path)
        try:
            # Insert task
            conn.execute("""
                INSERT INTO tasks(task_id, workspace, workspace_base, status, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
            """, (task_id, "workspace", temp_workspace, "ACTIVE",
                  datetime.now().isoformat(), datetime.now().isoformat()))

            # Insert agents
            for agent_id, status, progress in agent_configs:
                conn.execute("""
                    INSERT INTO agents(agent_id, task_id, type, status, progress, phase_index, started_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                """, (agent_id, task_id, "worker", status, progress, 0, datetime.now().isoformat()))

        finally:
            conn.close()

        # Load snapshot and verify counts
        snapshot = load_task_snapshot(workspace_base=temp_workspace, task_id=task_id)

        assert snapshot is not None
        counts = snapshot["counts"]

        # Total should be 9
        assert counts["total"] == 9, f"Expected 9 total, got {counts['total']}"

        # Active (working + blocked) should be 3
        assert counts["active"] == 3, f"Expected 3 active, got {counts['active']}"

        # Completed should be 3
        assert counts["completed"] == 3, f"Expected 3 completed, got {counts['completed']}"

        # Terminal (completed + failed + error + terminated) should be 6
        assert counts["terminal"] == 6, f"Expected 6 terminal, got {counts['terminal']}"

    def test_edge_case_empty_database(self, temp_workspace):
        """Test behavior with empty database."""
        db_path = ensure_db(temp_workspace)

        # Try to load non-existent task
        snapshot = load_task_snapshot(workspace_base=temp_workspace, task_id="NON-EXISTENT")
        assert snapshot is None

        # Try to load recent progress for non-existent task
        progress = load_recent_progress_latest(workspace_base=temp_workspace, task_id="NON-EXISTENT", limit=10)
        assert progress == []

        # Try to load phase snapshot for non-existent task
        phase_snapshot = load_phase_snapshot(workspace_base=temp_workspace, task_id="NON-EXISTENT", phase_index=0)
        assert phase_snapshot["agents"] == []
        assert phase_snapshot["counts"]["total"] == 0

    def test_edge_case_missing_workspace(self, temp_workspace):
        """Test reconciliation with missing workspace directory."""
        non_existent_path = os.path.join(temp_workspace, "non-existent-task")

        # Should return None for missing workspace
        result = reconcile_task_workspace(non_existent_path)
        assert result is None

    def test_edge_case_malformed_jsonl(self, temp_workspace):
        """Test reconciliation with malformed JSONL entries."""
        task_id = "TASK-malformed-test"
        task_workspace = os.path.join(temp_workspace, task_id)
        os.makedirs(task_workspace, exist_ok=True)
        progress_dir = os.path.join(task_workspace, "progress")
        os.makedirs(progress_dir, exist_ok=True)

        # Create AGENT_REGISTRY.json
        registry = {
            "task_id": task_id,
            "workspace": task_workspace,
            "workspace_base": temp_workspace,
            "agents": [{
                "id": "agent-malformed",
                "agent_id": "agent-malformed",
                "type": "tester",
                "status": "working",
                "progress": 50
            }]
        }

        with open(os.path.join(task_workspace, "AGENT_REGISTRY.json"), "w") as f:
            json.dump(registry, f)

        # Create progress JSONL with some malformed entries
        progress_file = os.path.join(progress_dir, "agent-malformed_progress.jsonl")
        with open(progress_file, "w") as f:
            # Valid entry
            f.write(json.dumps({"timestamp": datetime.now().isoformat(), "status": "working", "progress": 25}) + "\n")
            # Malformed JSON
            f.write("{ broken json }\n")
            # Another valid entry
            f.write(json.dumps({"timestamp": datetime.now().isoformat(), "status": "working", "progress": 75}) + "\n")
            # Empty line
            f.write("\n")
            # Non-JSON text
            f.write("This is not JSON\n")

        # Should still process successfully, using last valid entry
        db_path = reconcile_task_workspace(task_workspace)
        assert db_path is not None

        # Verify it used the last valid entry
        conn = _connect(db_path)
        try:
            row = conn.execute("""
                SELECT status, progress FROM agents WHERE agent_id='agent-malformed'
            """).fetchone()

            assert row is not None
            assert row[0] == "working"
            assert row[1] == 75  # From last valid entry

        finally:
            conn.close()

    def test_concurrent_updates_basic_race_condition(self, temp_workspace):
        """Test basic race condition handling with concurrent updates."""
        import threading
        import time

        db_path = ensure_db(temp_workspace)
        task_id = "TASK-concurrent-test"

        # Setup initial state
        conn = _connect(db_path)
        try:
            conn.execute("""
                INSERT INTO tasks(task_id, workspace, workspace_base, status, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
            """, (task_id, "workspace", temp_workspace, "ACTIVE",
                  datetime.now().isoformat(), datetime.now().isoformat()))

            # Create multiple agents
            for i in range(5):
                agent_id = f"agent-concurrent-{i}"
                conn.execute("""
                    INSERT INTO agents(agent_id, task_id, type, status, progress, started_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                """, (agent_id, task_id, "worker", "working", 0, datetime.now().isoformat()))
        finally:
            conn.close()

        # Function to update progress concurrently
        def update_agent_progress(agent_num: int, iterations: int):
            agent_id = f"agent-concurrent-{agent_num}"
            for i in range(iterations):
                try:
                    record_progress(
                        workspace_base=temp_workspace,
                        task_id=task_id,
                        agent_id=agent_id,
                        timestamp=datetime.now().isoformat(),
                        status="working",
                        message=f"Update {i}",
                        progress=min(100, (i + 1) * 10)
                    )
                    time.sleep(0.01)  # Small delay to increase chance of conflicts
                except Exception as e:
                    print(f"Error in thread {agent_num}: {e}")

        # Create threads for concurrent updates
        threads = []
        for i in range(5):
            thread = threading.Thread(target=update_agent_progress, args=(i, 10))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all updates completed without corruption
        conn = _connect(db_path)
        try:
            # Check that all agents have been updated
            rows = conn.execute("""
                SELECT agent_id, status, progress FROM agents
                WHERE task_id=? ORDER BY agent_id
            """, (task_id,)).fetchall()

            assert len(rows) == 5
            for row in rows:
                assert row[1] == "working"  # Status should be working
                assert row[2] == 100  # Final progress should be 100

            # Check agent_progress_latest has entries for all agents
            rows = conn.execute("""
                SELECT COUNT(*) FROM agent_progress_latest WHERE task_id=?
            """, (task_id,)).fetchone()

            assert rows[0] == 5, f"Expected 5 entries in agent_progress_latest, got {rows[0]}"

        finally:
            conn.close()

    def test_normalize_agent_status(self):
        """Test the normalize_agent_status function with various inputs."""
        # Test valid statuses
        assert normalize_agent_status("working", 50) == "working"
        assert normalize_agent_status("completed", 100) == "completed"
        assert normalize_agent_status("blocked", 30) == "blocked"
        assert normalize_agent_status("failed", 20) == "failed"

        # Test status normalization
        assert normalize_agent_status("pending", 0) == "running"
        assert normalize_agent_status("starting", 0) == "running"
        assert normalize_agent_status("WORKING", 50) == "working"  # Case insensitive

        # Test progress-based status inference
        assert normalize_agent_status("unknown", 100) == "completed"
        assert normalize_agent_status("unknown", 0) == "running"
        assert normalize_agent_status("unknown", 50) == "working"

        # Test edge cases
        assert normalize_agent_status(None, None) == "working"
        assert normalize_agent_status("", 50) == "working"
        assert normalize_agent_status("invalid_status", None) == "working"

    def test_load_phase_snapshot(self, temp_workspace):
        """Test load_phase_snapshot returns correct phase-specific data."""
        db_path = ensure_db(temp_workspace)
        task_id = "TASK-phase-test"

        conn = _connect(db_path)
        try:
            # Insert task
            conn.execute("""
                INSERT INTO tasks(task_id, workspace, workspace_base, status, created_at, updated_at, current_phase_index)
                VALUES(?, ?, ?, ?, ?, ?, ?)
            """, (task_id, "workspace", temp_workspace, "ACTIVE",
                  datetime.now().isoformat(), datetime.now().isoformat(), 0))

            # Insert agents for phase 0
            phase0_agents = [
                ("agent-p0-1", "completed", 100),
                ("agent-p0-2", "completed", 100),
                ("agent-p0-3", "failed", 50),
            ]

            for agent_id, status, progress in phase0_agents:
                conn.execute("""
                    INSERT INTO agents(agent_id, task_id, type, status, progress, phase_index, started_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                """, (agent_id, task_id, "worker", status, progress, 0, datetime.now().isoformat()))

            # Insert agents for phase 1
            phase1_agents = [
                ("agent-p1-1", "working", 60),
                ("agent-p1-2", "blocked", 30),
            ]

            for agent_id, status, progress in phase1_agents:
                conn.execute("""
                    INSERT INTO agents(agent_id, task_id, type, status, progress, phase_index, started_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                """, (agent_id, task_id, "worker", status, progress, 1, datetime.now().isoformat()))

        finally:
            conn.close()

        # Test phase 0 snapshot
        phase0_snapshot = load_phase_snapshot(workspace_base=temp_workspace, task_id=task_id, phase_index=0)
        assert len(phase0_snapshot["agents"]) == 3
        assert phase0_snapshot["counts"]["total"] == 3
        assert phase0_snapshot["counts"]["completed"] == 2
        assert phase0_snapshot["counts"]["failed"] == 1
        assert phase0_snapshot["counts"]["pending"] == 0
        assert phase0_snapshot["counts"]["all_done"] == True

        # Test phase 1 snapshot
        phase1_snapshot = load_phase_snapshot(workspace_base=temp_workspace, task_id=task_id, phase_index=1)
        assert len(phase1_snapshot["agents"]) == 2
        assert phase1_snapshot["counts"]["total"] == 2
        assert phase1_snapshot["counts"]["completed"] == 0
        assert phase1_snapshot["counts"]["failed"] == 0
        assert phase1_snapshot["counts"]["pending"] == 2
        assert phase1_snapshot["counts"]["all_done"] == False

    def test_load_recent_progress_latest(self, temp_workspace):
        """Test load_recent_progress_latest returns recent updates correctly."""
        db_path = ensure_db(temp_workspace)
        task_id = "TASK-progress-test"

        conn = _connect(db_path)
        try:
            # Insert task
            conn.execute("""
                INSERT INTO tasks(task_id, workspace, workspace_base, status, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
            """, (task_id, "workspace", temp_workspace, "ACTIVE",
                  datetime.now().isoformat(), datetime.now().isoformat()))

            # Insert multiple progress updates with different timestamps
            base_time = datetime.now()
            for i in range(5):
                agent_id = f"agent-{i}"
                # Create agents first
                conn.execute("""
                    INSERT INTO agents(agent_id, task_id, type, status, progress, started_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                """, (agent_id, task_id, "worker", "working", i * 20, base_time.isoformat()))

                # Insert progress updates
                timestamp = datetime.fromtimestamp(base_time.timestamp() - i * 60).isoformat()  # Each 1 minute older
                conn.execute("""
                    INSERT INTO agent_progress_latest(task_id, agent_id, timestamp, status, progress, message)
                    VALUES(?, ?, ?, ?, ?, ?)
                """, (task_id, agent_id, timestamp, "working", i * 20, f"Progress update {i}"))

        finally:
            conn.close()

        # Load recent progress (limit 3)
        recent = load_recent_progress_latest(workspace_base=temp_workspace, task_id=task_id, limit=3)

        # Should return 3 most recent entries
        assert len(recent) == 3

        # Should be ordered by timestamp desc (most recent first)
        for i in range(len(recent) - 1):
            assert recent[i]["timestamp"] >= recent[i + 1]["timestamp"]

        # Verify content
        assert recent[0]["agent_id"] == "agent-0"  # Most recent
        assert recent[0]["message"] == "Progress update 0"


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "--tb=short"])