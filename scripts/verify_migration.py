#!/usr/bin/env python3
"""
Verification script to compare JSON registry data with SQLite database.

This script:
1. Compares task counts between GLOBAL_REGISTRY.json and SQLite
2. Verifies all tasks from JSON are present in SQLite
3. Reports any discrepancies in task data
4. Validates agent counts and statuses
5. Provides detailed report of database integrity

Usage:
    python scripts/verify_migration.py
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator.state_db import (
    AGENT_ACTIVE_STATUSES,
    AGENT_TERMINAL_STATUSES,
    ensure_db,
    _connect,
    _read_json_safely,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class MigrationVerifier:
    """Verifies migration from JSON to SQLite was successful."""

    def __init__(self, workspace_base: str):
        self.workspace_base = workspace_base
        self.registry_path = os.path.join(workspace_base, "registry", "GLOBAL_REGISTRY.json")
        self.db_path = os.path.join(workspace_base, "registry", "state.sqlite3")
        self.issues = []
        self.warnings = []

    def verify_all(self) -> bool:
        """Run all verification checks."""
        logger.info("=" * 80)
        logger.info("Starting Migration Verification")
        logger.info(f"Workspace: {self.workspace_base}")
        logger.info(f"Database: {self.db_path}")
        logger.info("=" * 80)

        # Run verification checks
        checks = [
            ("Task Counts", self.verify_task_counts),
            ("Task Presence", self.verify_task_presence),
            ("Task Statuses", self.verify_task_statuses),
            ("Agent Data", self.verify_agent_data),
            ("Database Integrity", self.verify_database_integrity),
        ]

        all_passed = True
        for check_name, check_func in checks:
            logger.info(f"\n📋 Checking {check_name}...")
            try:
                if check_func():
                    logger.info(f"   ✅ {check_name} verification PASSED")
                else:
                    logger.error(f"   ❌ {check_name} verification FAILED")
                    all_passed = False
            except Exception as e:
                logger.error(f"   ❌ {check_name} check crashed: {e}")
                all_passed = False

        # Print summary
        self.print_summary()
        return all_passed and len(self.issues) == 0

    def verify_task_counts(self) -> bool:
        """Verify task counts match between JSON and SQLite."""
        # Read JSON registry
        global_registry = self._read_global_registry()
        if not global_registry:
            self.issues.append("Could not read GLOBAL_REGISTRY.json")
            return False

        json_tasks = global_registry.get("tasks", {})
        json_count = len(json_tasks)

        # Query SQLite
        conn = _connect(self.db_path)
        try:
            db_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        finally:
            conn.close()

        logger.info(f"   Tasks in JSON:   {json_count}")
        logger.info(f"   Tasks in SQLite: {db_count}")

        if json_count != db_count:
            self.issues.append(f"Task count mismatch: JSON has {json_count}, SQLite has {db_count}")
            return False

        return True

    def verify_task_presence(self) -> bool:
        """Verify all tasks from JSON are present in SQLite."""
        global_registry = self._read_global_registry()
        if not global_registry:
            return False

        json_task_ids = set(global_registry.get("tasks", {}).keys())

        # Get task IDs from SQLite
        conn = _connect(self.db_path)
        try:
            rows = conn.execute("SELECT task_id FROM tasks").fetchall()
            db_task_ids = set(row[0] for row in rows)
        finally:
            conn.close()

        # Compare sets
        missing_in_db = json_task_ids - db_task_ids
        extra_in_db = db_task_ids - json_task_ids

        if missing_in_db:
            self.issues.append(f"Tasks in JSON but not SQLite: {missing_in_db}")
            logger.error(f"   Missing in SQLite: {len(missing_in_db)} tasks")
            for task_id in list(missing_in_db)[:5]:  # Show first 5
                logger.error(f"     - {task_id}")

        if extra_in_db:
            self.warnings.append(f"Tasks in SQLite but not JSON: {extra_in_db}")
            logger.warning(f"   Extra in SQLite: {len(extra_in_db)} tasks")
            for task_id in list(extra_in_db)[:5]:  # Show first 5
                logger.warning(f"     - {task_id}")

        return len(missing_in_db) == 0

    def verify_task_statuses(self) -> bool:
        """Verify task statuses are correctly set."""
        conn = _connect(self.db_path)
        try:
            # Count tasks by status
            status_counts = {}
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM tasks GROUP BY status"
            ).fetchall()
            for status, count in rows:
                status_counts[status] = count

            logger.info("   Task status distribution:")
            for status, count in sorted(status_counts.items()):
                logger.info(f"     {status:15s}: {count:3d} tasks")

            # Verify no tasks are stuck in INITIALIZED with completed agents
            problematic = conn.execute("""
                SELECT t.task_id, t.status,
                       COUNT(DISTINCT a.agent_id) as total_agents,
                       SUM(CASE WHEN a.status IN ('completed', 'failed', 'error', 'terminated', 'killed')
                           THEN 1 ELSE 0 END) as terminal_agents
                FROM tasks t
                LEFT JOIN agents a ON t.task_id = a.task_id
                WHERE t.status = 'INITIALIZED'
                GROUP BY t.task_id, t.status
                HAVING total_agents > 0 AND terminal_agents = total_agents
            """).fetchall()

            if problematic:
                for row in problematic:
                    self.warnings.append(
                        f"Task {row[0]} is INITIALIZED but all {row[2]} agents are terminated"
                    )
                logger.warning(f"   Found {len(problematic)} tasks with incorrect status")

        finally:
            conn.close()

        return True

    def verify_agent_data(self) -> bool:
        """Verify agent data integrity."""
        conn = _connect(self.db_path)
        try:
            # Total agents
            total_agents = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            logger.info(f"   Total agents in SQLite: {total_agents}")

            # Agents by status
            status_counts = {}
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM agents GROUP BY status"
            ).fetchall()
            for status, count in rows:
                status_counts[status] = count

            active_count = sum(count for status, count in status_counts.items()
                              if status in AGENT_ACTIVE_STATUSES)
            terminal_count = sum(count for status, count in status_counts.items()
                                if status in AGENT_TERMINAL_STATUSES)

            logger.info(f"   Active agents:   {active_count}")
            logger.info(f"   Terminal agents: {terminal_count}")

            # Check for orphaned agents (agents without tasks)
            orphaned = conn.execute("""
                SELECT COUNT(*) FROM agents a
                WHERE NOT EXISTS (SELECT 1 FROM tasks t WHERE t.task_id = a.task_id)
            """).fetchone()[0]

            if orphaned > 0:
                self.issues.append(f"Found {orphaned} orphaned agents without tasks")

            # Check for agents with invalid statuses
            invalid = conn.execute("""
                SELECT DISTINCT status FROM agents
                WHERE status NOT IN (
                    'running', 'working', 'blocked', 'completed', 'failed',
                    'error', 'terminated', 'reviewing', 'phase_completed', 'killed'
                )
            """).fetchall()

            if invalid:
                invalid_statuses = [row[0] for row in invalid]
                self.issues.append(f"Found agents with invalid statuses: {invalid_statuses}")

        finally:
            conn.close()

        return True

    def verify_database_integrity(self) -> bool:
        """Verify database integrity and foreign key constraints."""
        conn = _connect(self.db_path)
        try:
            # Check foreign key integrity
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                self.issues.append(f"Foreign key violations: {violations}")
                return False

            # Check for NULL values in required fields
            null_checks = [
                ("tasks", "task_id"),
                ("tasks", "status"),
                ("agents", "agent_id"),
                ("agents", "task_id"),
            ]

            for table, column in null_checks:
                null_count = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {column} IS NULL"
                ).fetchone()[0]
                if null_count > 0:
                    self.issues.append(f"Found {null_count} NULL values in {table}.{column}")

            # Verify indices exist
            indices = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"
            ).fetchall()
            expected_indices = ["idx_agents_task", "idx_agents_task_phase"]
            existing_indices = [row[0] for row in indices]

            for idx in expected_indices:
                if idx not in existing_indices:
                    self.warnings.append(f"Missing index: {idx}")

        finally:
            conn.close()

        return len(self.issues) == 0

    def _read_global_registry(self) -> dict:
        """Read GLOBAL_REGISTRY.json safely."""
        if not os.path.exists(self.registry_path):
            logger.error(f"GLOBAL_REGISTRY.json not found at {self.registry_path}")
            return {}

        registry = _read_json_safely(self.registry_path)
        if not registry:
            logger.error("Failed to read GLOBAL_REGISTRY.json")
            return {}

        return registry

    def print_summary(self):
        """Print verification summary."""
        logger.info("\n" + "=" * 80)
        logger.info("VERIFICATION SUMMARY")
        logger.info("=" * 80)

        if self.issues:
            logger.error(f"\n❌ Found {len(self.issues)} critical issues:")
            for i, issue in enumerate(self.issues, 1):
                logger.error(f"   {i}. {issue}")
        else:
            logger.info("\n✅ No critical issues found!")

        if self.warnings:
            logger.warning(f"\n⚠️  Found {len(self.warnings)} warnings:")
            for i, warning in enumerate(self.warnings, 1):
                logger.warning(f"   {i}. {warning}")

        # Database statistics
        conn = _connect(self.db_path)
        try:
            stats = conn.execute("""
                SELECT
                    (SELECT COUNT(*) FROM tasks) as total_tasks,
                    (SELECT COUNT(*) FROM tasks WHERE status='ACTIVE') as active_tasks,
                    (SELECT COUNT(*) FROM tasks WHERE status='COMPLETED') as completed_tasks,
                    (SELECT COUNT(*) FROM tasks WHERE status='ARCHIVED') as archived_tasks,
                    (SELECT COUNT(*) FROM agents) as total_agents,
                    (SELECT COUNT(*) FROM phases) as total_phases
            """).fetchone()

            logger.info("\n📊 Database Statistics:")
            logger.info(f"   Total tasks:      {stats[0]}")
            logger.info(f"   Active tasks:     {stats[1]}")
            logger.info(f"   Completed tasks:  {stats[2]}")
            logger.info(f"   Archived tasks:   {stats[3]}")
            logger.info(f"   Total agents:     {stats[4]}")
            logger.info(f"   Total phases:     {stats[5]}")

        finally:
            conn.close()


def main():
    """Main entry point."""
    workspace_base = os.path.abspath(".agent-workspace")
    verifier = MigrationVerifier(workspace_base)

    try:
        if verifier.verify_all():
            logger.info("\n🎉 Migration verification PASSED!")
            sys.exit(0)
        else:
            logger.error("\n💔 Migration verification FAILED - check issues above")
            sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("\n⚠️  Verification interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Verification failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()