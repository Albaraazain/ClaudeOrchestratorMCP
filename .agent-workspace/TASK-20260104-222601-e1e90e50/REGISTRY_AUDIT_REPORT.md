# Registry Operations Audit Report
## Investigation Phase - Complete Registry Analysis

### Executive Summary
Comprehensive audit identified **108 files** with JSON registry dependencies across the codebase. The migration from JSON registries (GLOBAL_REGISTRY.json, AGENT_REGISTRY.json) to SQLite state_db requires modifying **14 core files** containing **80+ write operations** and **25+ read operations**.

### Current Architecture Problems
1. **Stale Counts**: GLOBAL_REGISTRY.json shows `active_tasks: 43, active_agents: 97` that never decrement
2. **Race Conditions**: Despite LockedRegistryFile, concurrent operations still cause data corruption
3. **Status Lifecycle**: Tasks stuck at INITIALIZED, never transition to ACTIVE/COMPLETED
4. **Dashboard Inaccuracy**: Shows 7 active tasks when there are none (checks `active_agents > 0` on stale data)

## Detailed Findings

### 1. Registry Write Operations (CRITICAL)

#### real_mcp_server.py (50+ write operations)
- **LockedRegistryFile usage**: Lines 737, 777, 1104, 1139, 1160, 1305, 1337, 2735, 3138, 3232, 3321, 3378, 4248, 4359, 4491, 4582, 4655, 4749, 4838, 4979, 5051, 5193, 5266, 5480, 5777
- **Direct json.dump**: Lines 506, 1116, 1153, 1169, 1323, 1345, 2156, 2181, 2201, 3104, 3199, 3260, 3336, 3385, 3490, 4449, 4521, 4619, 4699, 4785, 4875, 5100, 5399, 5550, 5830
- **Operations**: Agent deployment, status updates, phase transitions, review management

#### orchestrator/lifecycle.py (6 write operations)
- **write_registry_with_lock**: Lines 127, 147
- **LockedRegistryFile**: Lines 990, 1085, 1100, 1118
- **Operations**: Agent termination, lifecycle management

#### orchestrator/health_daemon.py (7 write operations)
- **LockedRegistryFile**: Lines 209, 237, 341, 506, 700, 749, 809
- **Operations**: Health monitoring, failed agent marking, review escalation

### 2. Registry Read Operations

#### dashboard/backend/api/routes/tasks.py
- **read_registry_with_lock**: Lines 21, 376, 421, 581, 609
- **Direct JSON load**: Line 123 (GLOBAL_REGISTRY.json)
- **Purpose**: Task listing, status display

#### dashboard/backend/api/routes/agents.py
- **read_registry_with_lock**: Lines 21, 136, 230, 270
- **Purpose**: Agent status, progress tracking

#### orchestrator/workspace.py
- **json.load**: Lines 116, 139, 242
- **Purpose**: Registry discovery, workspace resolution

### 3. Core Registry Module Analysis

#### orchestrator/registry.py (2354 lines)
- **LockedRegistryFile class**: Lines 333-483 (atomic file operations)
- **read_registry_with_lock**: Lines 951-1005
- **write_registry_with_lock**: Lines 1007-1076
- **Atomic operations**:
  - atomic_add_agent (line 630)
  - atomic_update_agent_status (line 707)
  - atomic_increment_counts (line 787)
  - atomic_decrement_active_count (line 829)
  - atomic_mark_agents_completed (line 866)
  - Phase transition functions (lines 1340-2066)

### 4. SQLite State_DB Replacement Functions

#### Available Tables
```sql
- tasks: task_id, workspace, status, current_phase_index
- phases: task_id, phase_index, status, started_at, completed_at
- agents: agent_id, task_id, type, status, progress, phase_index
- agent_progress_latest: task_id, agent_id, status, progress, message
```

#### Available Functions
- `ensure_db(workspace_base)`: Initialize SQLite database
- `record_progress(...)`: Materialize agent progress to SQLite
- `reconcile_task_workspace(task_workspace)`: Sync JSONL to SQLite
- `load_task_snapshot(workspace_base, task_id)`: Read task state
- `load_phase_snapshot(workspace_base, task_id, phase_index)`: Read phase state
- `load_recent_progress_latest(workspace_base, task_id)`: Get latest progress

### 5. Migration Mapping

| JSON Operation | SQLite Replacement | Location |
|---------------|-------------------|----------|
| `registry['agents'].append()` | INSERT INTO agents | real_mcp_server.py:1105 |
| `registry['active_count'] += 1` | UPDATE tasks SET status | Multiple locations |
| `registry['phases'][i]['status']` | UPDATE phases SET status | Phase transitions |
| `read_registry_with_lock()` | load_task_snapshot() | Dashboard APIs |
| `global_reg['agents'][id]` | SELECT FROM agents WHERE | Global registry ops |

### 6. Critical Migration Points

#### High Priority (Causing Current Issues)
1. **Dashboard task counting** (tasks.py:123-147) - Reading stale GLOBAL_REGISTRY.json
2. **Active count updates** (real_mcp_server.py:1140-1154) - Never decrements properly
3. **Task status transitions** - Stuck at INITIALIZED

#### Medium Priority (Functionality Impact)
1. **Health daemon reconciliation** (health_daemon.py:341-400)
2. **Phase transition logic** (registry.py:1410-1529)
3. **Agent completion marking** (multiple locations)

#### Low Priority (Can Run in Parallel)
1. **Archive operations**
2. **Cleanup routines**
3. **Debug/monitoring endpoints**

### 7. Risk Assessment

#### Data Loss Risks
- **Concurrent writes during migration**: Need phased rollout
- **JSONL as source of truth**: Must preserve append-only logs
- **Rollback capability**: Keep JSON as fallback initially

#### Performance Impact
- **SQLite faster for reads**: Dashboard will improve
- **Write performance similar**: Still need transactions
- **Index optimization needed**: On task_id, agent_id, phase_index

### 8. Recommended Migration Strategy

#### Phase 1: Parallel Write (Low Risk)
1. Modify `record_progress()` to write BOTH JSON and SQLite
2. Add SQLite writes alongside all LockedRegistryFile operations
3. Monitor for consistency

#### Phase 2: Read Migration (Medium Risk)
1. Update dashboard to read from SQLite (load_task_snapshot)
2. Keep JSON as fallback for missing data
3. Add reconciliation on startup

#### Phase 3: Write Cutover (High Risk)
1. Stop writing to JSON registries
2. SQLite becomes primary store
3. JSON becomes read-only archive

#### Phase 4: Cleanup
1. Remove LockedRegistryFile usage
2. Delete registry.py functions
3. Archive old JSON files

### Files Requiring Modification

1. **real_mcp_server.py** - 80+ modifications
2. **dashboard/backend/api/routes/tasks.py** - 10+ modifications
3. **dashboard/backend/api/routes/agents.py** - 5+ modifications
4. **orchestrator/health_daemon.py** - 10+ modifications
5. **orchestrator/lifecycle.py** - 6+ modifications
6. **orchestrator/workspace.py** - 5+ modifications
7. **orchestrator/registry.py** - Can be deprecated after migration
8. **dashboard/backend/api/routes/phases.py** - Minor updates
9. **dashboard/backend/services/workspace.py** - Update imports
10. **dashboard/backend/services/watcher.py** - Update imports
11. **orchestrator/handover.py** - Update registry access
12. **orchestrator/review.py** - Update registry access
13. **orchestrator/__init__.py** - Update exports
14. **orchestrator/deployment.py** - Update registry validation

### Immediate Actions Required

1. **Fix Dashboard Counting**: Modify tasks.py to use SQLite for active task counts
2. **Fix Status Transitions**: Ensure tasks move from INITIALIZED → ACTIVE → COMPLETED
3. **Implement Decrements**: Properly decrement active_agents when agents complete
4. **Add Reconciliation**: Sync JSONL → SQLite on daemon startup

### Conclusion

The migration from JSON registries to SQLite is necessary to fix critical issues with stale counts and incorrect dashboard display. The state_db.py module provides all necessary replacement functions, but the migration requires careful coordination across 14+ files with 100+ modification points.

The highest priority is fixing the dashboard display issue where it shows active tasks when there are none. This can be resolved by updating dashboard/backend/api/routes/tasks.py to read from SQLite's tasks and agents tables instead of the stale GLOBAL_REGISTRY.json.

---
Report compiled by: registry-auditor-222658-46d031
Timestamp: 2026-01-04T22:29:00Z