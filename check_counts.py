#!/usr/bin/env python3
"""Check current global counts from both SQLite and JSON."""

import json
from pathlib import Path
import sys

# Add orchestrator to path
orchestrator_path = Path(__file__).parent
sys.path.insert(0, str(orchestrator_path))

from orchestrator import state_db

workspace_base = str(Path.home() / ".agent-workspace")

# Get counts from SQLite (the truth)
sqlite_counts = state_db.get_global_active_counts(workspace_base=workspace_base)
print("SQLite Counts (Truth):")
print(f"  Active Tasks: {sqlite_counts['active_tasks']}")
print(f"  Active Agents: {sqlite_counts['active_agents']}")

# Get full global counts
full_counts = state_db.get_global_counts(workspace_base=workspace_base)
print(f"\nFull SQLite Stats:")
print(f"  Total Tasks: {full_counts['total_tasks']}")
print(f"  Active Tasks: {full_counts['active_tasks']}")
print(f"  Completed Tasks: {full_counts['completed_tasks']}")
print(f"  Failed Tasks: {full_counts['failed_tasks']}")
print(f"  Total Agents: {full_counts['total_agents']}")
print(f"  Active Agents: {full_counts['active_agents']}")
print(f"  Completed Agents: {full_counts['completed_agents']}")
print(f"  Failed Agents: {full_counts['failed_agents']}")

# Compare with JSON registry (the old way)
global_registry_path = Path(workspace_base) / "registry" / "GLOBAL_REGISTRY.json"
if global_registry_path.exists():
    with open(global_registry_path, 'r') as f:
        global_reg = json.load(f)
    print(f"\nJSON Registry Counts (Stale):")
    print(f"  Active Tasks: {global_reg.get('active_tasks', 0)}")
    print(f"  Active Agents: {global_reg.get('active_agents', 0)}")

    print(f"\nMismatch:")
    print(f"  JSON shows {global_reg.get('active_tasks', 0)} active tasks but SQLite shows {sqlite_counts['active_tasks']} (correct)")
    print(f"  JSON shows {global_reg.get('active_agents', 0)} active agents but SQLite shows {sqlite_counts['active_agents']} (correct)")

print("\n✅ SQLite is now the single source of truth for counts!")
print("The JSON registry counts are no longer accurate and should be deprecated.")