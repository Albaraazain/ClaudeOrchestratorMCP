# SQLite Migration Scripts

## Overview

These scripts help migrate historical task data from JSON registries to the SQLite database. The migration is necessary to transition from the legacy JSON-based storage to the new SQLite-backed state management system.

## Scripts

### 1. `migrate_to_sqlite.py`

**Purpose:** One-time migration script to sync all historical task data from JSON to SQLite.

**What it does:**
- Reads all task IDs from `GLOBAL_REGISTRY.json`
- For each task with a workspace directory: calls `reconcile_task_workspace()` to import full data
- For tasks without workspace: inserts as ARCHIVED status
- Updates task status based on agent terminal states
- Safe to run multiple times (idempotent)

**Usage:**
```bash
cd /path/to/ClaudeOrchestratorMCP
python scripts/migrate_to_sqlite.py
```

**Output:**
- Detailed log of each task processed
- Summary statistics of migration
- Final database state counts

### 2. `verify_migration.py`

**Purpose:** Verification script to ensure migration was successful.

**What it checks:**
1. **Task Counts**: Verifies JSON and SQLite have same number of tasks
2. **Task Presence**: Ensures all tasks from JSON exist in SQLite
3. **Task Statuses**: Reports status distribution and identifies issues
4. **Agent Data**: Validates agent counts and statuses
5. **Database Integrity**: Checks foreign keys and required fields

**Usage:**
```bash
cd /path/to/ClaudeOrchestratorMCP
python scripts/verify_migration.py
```

**Output:**
- Verification results for each check
- List of any critical issues found
- Warnings about data inconsistencies
- Database statistics summary

## Migration Process

### Step 1: Backup (Optional but Recommended)
```bash
cp .agent-workspace/registry/GLOBAL_REGISTRY.json .agent-workspace/registry/GLOBAL_REGISTRY.json.backup
cp .agent-workspace/registry/state.sqlite3 .agent-workspace/registry/state.sqlite3.backup
```

### Step 2: Run Migration
```bash
python scripts/migrate_to_sqlite.py
```

Expected output:
```
================================================================================
Starting migration from JSON registries to SQLite
================================================================================
Found 45 tasks in GLOBAL_REGISTRY.json
Processing tasks...
[TASK-xxx] → Successfully migrated with full workspace data
...
Migration Summary
================================================================================
Total tasks in JSON:            45
Already in database:             0
Migrated with workspace:         43
Migrated as archived:            2
Errors:                          0

✅ Migration completed successfully!
```

### Step 3: Verify Migration
```bash
python scripts/verify_migration.py
```

Expected output:
```
================================================================================
VERIFICATION SUMMARY
================================================================================
✅ No critical issues found!

📊 Database Statistics:
   Total tasks:      45
   Active tasks:     0
   Completed tasks:  0
   Archived tasks:   2
   Total agents:     223
   Total phases:     21

🎉 Migration verification PASSED!
```

## Common Issues

### Issue: Tasks stuck in INITIALIZED with all agents terminated

**Cause:** Legacy tasks didn't properly update status when agents completed.

**Solution:** The migration script attempts to fix this by calling `update_task_status_from_agents()`. Tasks with all terminal agents are marked as COMPLETED.

### Issue: Missing workspace directories

**Cause:** Some tasks may have had their workspace directories deleted.

**Solution:** These tasks are inserted with ARCHIVED status to preserve history.

### Issue: Foreign key violations

**Cause:** Database integrity issues from partial migrations.

**Solution:** Drop and recreate the database before migration:
```bash
rm .agent-workspace/registry/state.sqlite3
python scripts/migrate_to_sqlite.py
```

## Database Schema

The SQLite database contains:
- `tasks`: Main task records with status, priority, timestamps
- `phases`: Task phases with status tracking
- `agents`: Agent records with type, status, progress
- `agent_progress_latest`: Latest progress update per agent

## Post-Migration

After successful migration:
1. The dashboard and APIs should read from SQLite instead of JSON
2. Task/agent counts should be accurate
3. New tasks will automatically use SQLite
4. GLOBAL_REGISTRY.json becomes read-only legacy data

## Troubleshooting

Enable debug logging:
```bash
python scripts/migrate_to_sqlite.py 2>&1 | tee migration.log
```

Check database directly:
```bash
sqlite3 .agent-workspace/registry/state.sqlite3
.tables
SELECT COUNT(*) FROM tasks;
SELECT status, COUNT(*) FROM tasks GROUP BY status;
.quit
```

Reset and retry:
```bash
rm .agent-workspace/registry/state.sqlite3
python scripts/migrate_to_sqlite.py
```