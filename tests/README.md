# State Database Test Suite

This directory contains comprehensive tests for the `orchestrator/state_db.py` module, which manages SQLite-backed state storage for the Claude Orchestrator MCP.

## Test Files

### test_state_db.py
Main test suite containing 13 comprehensive tests covering:

1. **Schema Creation** (`test_schema_creation`)
   - Verifies all required tables are created
   - Checks table columns match specifications
   - Validates indexes are properly created

2. **Progress Recording** (`test_record_progress_updates_both_tables`)
   - Tests that `record_progress` updates both `agent_progress_latest` and `agents` tables
   - Verifies status normalization and progress tracking

3. **Task Reconciliation** (`test_reconcile_task_workspace_from_jsonl`)
   - Tests synchronization from JSONL files to SQLite
   - Verifies proper materialization of task, phase, and agent data
   - Validates that JSONL takes precedence over registry JSON

4. **Snapshot Loading** (`test_load_task_snapshot_returns_correct_structure`)
   - Validates complete task data retrieval
   - Tests phase and agent aggregation
   - Verifies count calculations (active, completed, terminal)

5. **Status Transitions** (`test_status_transitions_work_correctly`)
   - Tests agent status lifecycle: running → working → blocked → completed
   - Validates automatic setting of `completed_at` timestamp

6. **Count Accuracy** (`test_count_queries_accuracy`)
   - Verifies accurate counting of active agents (working + blocked)
   - Tests terminal status counting (completed + failed + error + terminated)

7. **Edge Cases**:
   - **Empty Database** (`test_edge_case_empty_database`) - Handles queries on non-existent data
   - **Missing Workspace** (`test_edge_case_missing_workspace`) - Gracefully handles missing directories
   - **Malformed JSONL** (`test_edge_case_malformed_jsonl`) - Resilient to corrupted progress files

8. **Concurrency** (`test_concurrent_updates_basic_race_condition`)
   - Tests handling of concurrent updates from multiple threads
   - Validates SQLite's WAL mode prevents data corruption

9. **Helper Functions**:
   - **Status Normalization** (`test_normalize_agent_status`) - Tests status conversion logic
   - **Phase Snapshots** (`test_load_phase_snapshot`) - Phase-specific agent queries
   - **Recent Progress** (`test_load_recent_progress_latest`) - Time-ordered progress retrieval

### fixtures.py
Provides test data and utility functions:

- `create_sample_task_workspace()` - Creates complete task directory structure
- `create_agent_registry()` - Generates AGENT_REGISTRY.json files
- `create_progress_jsonl()` - Creates progress JSONL files for agents
- `get_sample_task_with_phases()` - Returns multi-phase task data
- `get_progress_entries_for_agent()` - Generates realistic progress sequences
- `create_complex_task_scenario()` - Sets up complete testing scenario
- `create_edge_case_scenarios()` - Creates edge case test data

### run_state_db_tests.py
Simple test runner that can execute tests without global pytest installation.

## Running Tests

### With pytest installed:
```bash
pytest tests/test_state_db.py -v
```

### Run specific test categories:
```bash
# Edge cases only
pytest tests/test_state_db.py -k "edge_case" -v

# Concurrency tests
pytest tests/test_state_db.py -k "concurrent" -v

# Schema and structure tests
pytest tests/test_state_db.py -k "schema or snapshot" -v
```

### Using the test runner:
```bash
python tests/run_state_db_tests.py
```

## Test Coverage

The test suite covers:

- ✅ **Schema Creation**: All tables, columns, indexes
- ✅ **Data Operations**: Insert, update, query operations
- ✅ **JSONL Reconciliation**: Progress file parsing and materialization
- ✅ **Status Management**: Agent lifecycle and transitions
- ✅ **Count Queries**: Accurate active/completed/terminal counts
- ✅ **Edge Cases**: Empty data, missing files, corrupted JSONL
- ✅ **Race Conditions**: Basic concurrent update handling
- ✅ **Phase Management**: Phase-specific agent queries
- ✅ **Progress Tracking**: Time-ordered progress retrieval

## Test Results

All 13 tests pass successfully in ~0.29 seconds:

```
============================== 13 passed in 0.29s ==============================
```

## Integration Points

These tests verify that `state_db.py` correctly:
- Creates and maintains SQLite schema
- Syncs from JSONL progress files (source of truth)
- Provides accurate task/agent status for dashboard
- Handles concurrent updates safely
- Recovers from malformed data gracefully