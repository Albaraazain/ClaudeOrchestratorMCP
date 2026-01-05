#!/usr/bin/env python3
"""
One-time migration script to sync historical task data from JSON registries to SQLite.

This script:
1. Reads GLOBAL_REGISTRY.json for all task IDs
2. For each task, checks if workspace exists in .agent-workspace/TASK-*
3. If workspace exists: calls reconcile_task_workspace() to import
4. If no workspace: inserts task metadata with status=ARCHIVED
5. Updates task status based on agent terminal states
6. Is idempotent - safe to run multiple times

Usage:
    python scripts/migrate_to_sqlite.py
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator.state_db import (
    AGENT_ACTIVE_STATUSES,
    AGENT_TERMINAL_STATUSES,
    ensure_db,
    reconcile_task_workspace,
    _connect,
    _parse_dt,
    _read_json_safely,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def migrate_historical_data():
    """
    Main migration function to sync historical data to SQLite.
    """
    # Paths
    workspace_base = os.path.abspath(".agent-workspace")
    registry_path = os.path.join(workspace_base, "registry", "GLOBAL_REGISTRY.json")

    # Statistics
    stats = {
        "total_tasks": 0,
        "migrated_with_workspace": 0,
        "migrated_as_archived": 0,
        "already_in_db": 0,
        "errors": 0,
    }

    logger.info("=" * 80)
    logger.info("Starting migration from JSON registries to SQLite")
    logger.info(f"Workspace base: {workspace_base}")
    logger.info("=" * 80)

    # Ensure database exists
    db_path = ensure_db(workspace_base)
    logger.info(f"Database path: {db_path}")

    # Read GLOBAL_REGISTRY.json
    logger.info(f"\nReading GLOBAL_REGISTRY from: {registry_path}")
    if not os.path.exists(registry_path):
        logger.error(f"GLOBAL_REGISTRY.json not found at {registry_path}")
        return stats

    try:
        global_registry = _read_json_safely(registry_path)
        if not global_registry:
            logger.error("Failed to read GLOBAL_REGISTRY.json")
            return stats
    except Exception as e:
        logger.error(f"Error reading GLOBAL_REGISTRY.json: {e}")
        return stats

    # Get all task IDs
    tasks_dict = global_registry.get("tasks", {})
    stats["total_tasks"] = len(tasks_dict)
    logger.info(f"Found {stats['total_tasks']} tasks in GLOBAL_REGISTRY.json")

    # Check existing tasks in SQLite
    conn = _connect(db_path)
    try:
        existing_tasks = set()
        rows = conn.execute("SELECT task_id FROM tasks").fetchall()
        for row in rows:
            existing_tasks.add(row[0])
        logger.info(f"Found {len(existing_tasks)} tasks already in SQLite")
    finally:
        conn.close()

    # Process each task
    logger.info("\n" + "=" * 80)
    logger.info("Processing tasks...")
    logger.info("=" * 80)

    for task_id, task_info in tasks_dict.items():
        logger.info(f"\n[{task_id}]")

        # Check if already in database
        if task_id in existing_tasks:
            logger.info("  → Already in SQLite, checking for updates...")
            stats["already_in_db"] += 1
            # Still attempt reconciliation in case there are updates
            task_workspace = os.path.join(workspace_base, task_id)
            if os.path.exists(task_workspace):
                try:
                    reconcile_task_workspace(task_workspace)
                    logger.info("  → Updated from workspace")
                except Exception as e:
                    logger.warning(f"  → Error updating: {e}")
            continue

        # Check if workspace exists
        task_workspace = os.path.join(workspace_base, task_id)

        if os.path.exists(task_workspace):
            # Workspace exists - use reconcile_task_workspace
            logger.info(f"  → Workspace found at {task_workspace}")
            try:
                result = reconcile_task_workspace(task_workspace)
                if result:
                    logger.info(f"  → Successfully migrated with full workspace data")
                    stats["migrated_with_workspace"] += 1

                    # Update task status based on agents
                    update_task_status_from_agents(db_path, task_id)
                else:
                    logger.warning(f"  → reconcile_task_workspace returned None")
                    # Try to insert as archived
                    insert_archived_task(db_path, task_id, task_info)
                    stats["migrated_as_archived"] += 1
            except Exception as e:
                logger.error(f"  → Error during reconciliation: {e}")
                # Fallback to archived status
                try:
                    insert_archived_task(db_path, task_id, task_info)
                    stats["migrated_as_archived"] += 1
                except Exception as e2:
                    logger.error(f"  → Failed to insert as archived: {e2}")
                    stats["errors"] += 1
        else:
            # No workspace - insert as archived
            logger.info(f"  → No workspace found, inserting as ARCHIVED")
            try:
                insert_archived_task(db_path, task_id, task_info)
                stats["migrated_as_archived"] += 1
            except Exception as e:
                logger.error(f"  → Error inserting archived task: {e}")
                stats["errors"] += 1

    # Final summary
    logger.info("\n" + "=" * 80)
    logger.info("Migration Summary")
    logger.info("=" * 80)
    logger.info(f"Total tasks in JSON:            {stats['total_tasks']}")
    logger.info(f"Already in database:             {stats['already_in_db']}")
    logger.info(f"Migrated with workspace:         {stats['migrated_with_workspace']}")
    logger.info(f"Migrated as archived:            {stats['migrated_as_archived']}")
    logger.info(f"Errors:                          {stats['errors']}")

    # Verify final counts
    conn = _connect(db_path)
    try:
        final_count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        active_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='ACTIVE'").fetchone()[0]
        archived_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='ARCHIVED'").fetchone()[0]
        completed_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='COMPLETED'").fetchone()[0]

        logger.info(f"\nFinal database state:")
        logger.info(f"  Total tasks in SQLite:  {final_count}")
        logger.info(f"  Active tasks:           {active_count}")
        logger.info(f"  Completed tasks:        {completed_count}")
        logger.info(f"  Archived tasks:         {archived_count}")
    finally:
        conn.close()

    return stats


def insert_archived_task(db_path: str, task_id: str, task_info: dict):
    """
    Insert a task with ARCHIVED status when no workspace exists.
    """
    conn = _connect(db_path)
    try:
        created_at = _parse_dt(task_info.get("created_at")) or datetime.fromtimestamp(0).isoformat()
        updated_at = datetime.now().isoformat()

        conn.execute(
            """
            INSERT INTO tasks(task_id, workspace, workspace_base, description, status, priority,
                              client_cwd, created_at, updated_at, current_phase_index)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(task_id) DO UPDATE SET
              status='ARCHIVED',
              updated_at=excluded.updated_at
            """,
            (
                task_id,
                "",  # No workspace
                os.path.abspath(".agent-workspace"),
                task_info.get("description", ""),
                "ARCHIVED",  # Mark as archived since no workspace
                task_info.get("priority", "P2"),
                "",  # No client_cwd info
                created_at,
                updated_at,
                0,  # No phases
            ),
        )
        logger.debug(f"Inserted task {task_id} as ARCHIVED")
    finally:
        conn.close()


def update_task_status_from_agents(db_path: str, task_id: str):
    """
    Update task status based on agent states.
    If all agents are in terminal state, mark task as COMPLETED.
    If any agents are active, mark as ACTIVE.
    """
    conn = _connect(db_path)
    try:
        # Get agent statuses for this task
        agents = conn.execute(
            "SELECT status FROM agents WHERE task_id=?",
            (task_id,)
        ).fetchall()

        if not agents:
            # No agents, keep current status
            return

        statuses = [row[0] for row in agents]
        active_count = sum(1 for s in statuses if s in AGENT_ACTIVE_STATUSES)
        terminal_count = sum(1 for s in statuses if s in AGENT_TERMINAL_STATUSES)

        if active_count > 0:
            # Has active agents - mark as ACTIVE
            new_status = "ACTIVE"
        elif terminal_count == len(statuses):
            # All agents terminated - mark as COMPLETED
            new_status = "COMPLETED"
        else:
            # Mixed state or initialized - keep as is
            return

        conn.execute(
            "UPDATE tasks SET status=?, updated_at=? WHERE task_id=?",
            (new_status, datetime.now().isoformat(), task_id)
        )
        logger.debug(f"Updated task {task_id} status to {new_status}")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        migrate_historical_data()
        logger.info("\n✅ Migration completed successfully!")
        sys.exit(0)
    except KeyboardInterrupt:
        logger.warning("\n⚠️  Migration interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n❌ Migration failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)