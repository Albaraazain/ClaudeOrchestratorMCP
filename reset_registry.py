#!/usr/bin/env python3
"""
Reset GLOBAL_REGISTRY.json to clear stale counts.
This script:
1. Backs up the current registry
2. Resets active_tasks and active_agents to 0
3. Marks all tasks as ARCHIVED
4. Saves the cleaned registry
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

def reset_registry():
    registry_path = Path('.agent-workspace/registry/GLOBAL_REGISTRY.json')

    if not registry_path.exists():
        print(f"❌ Registry file not found: {registry_path}")
        return False

    # Create backup with timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = registry_path.parent / f"GLOBAL_REGISTRY.json.backup_{timestamp}"

    print(f"📋 Creating backup: {backup_path}")
    shutil.copy2(registry_path, backup_path)

    # Load the registry
    with open(registry_path, 'r') as f:
        registry = json.load(f)

    print(f"\n📊 Current State:")
    print(f"  - active_tasks: {registry.get('active_tasks', 0)}")
    print(f"  - active_agents: {registry.get('active_agents', 0)}")
    print(f"  - total tasks in dict: {len(registry.get('tasks', {}))}")

    # Reset active counts
    registry['active_tasks'] = 0
    registry['active_agents'] = 0

    # Mark all tasks as ARCHIVED
    archived_count = 0
    for task_id, task_data in registry.get('tasks', {}).items():
        if task_data.get('status') != 'ARCHIVED':
            task_data['status'] = 'ARCHIVED'
            archived_count += 1

    # Save the cleaned registry
    with open(registry_path, 'w') as f:
        json.dump(registry, f, indent=2)

    print(f"\n✅ Registry Reset Complete:")
    print(f"  - active_tasks: 0")
    print(f"  - active_agents: 0")
    print(f"  - {archived_count} tasks marked as ARCHIVED")
    print(f"  - Backup saved to: {backup_path}")

    return True

if __name__ == "__main__":
    success = reset_registry()
    exit(0 if success else 1)