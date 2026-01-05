#!/usr/bin/env python3
"""
Registry management utility for ClaudeOrchestratorMCP.
Provides commands to reset, backup, and analyze the GLOBAL_REGISTRY.json file.

Usage:
    python manage_registry.py reset    # Reset all active counts to 0
    python manage_registry.py analyze  # Show current state
    python manage_registry.py backup   # Create timestamped backup
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

REGISTRY_PATH = Path('.agent-workspace/registry/GLOBAL_REGISTRY.json')


def analyze_registry():
    """Analyze and display current registry state."""
    if not REGISTRY_PATH.exists():
        print(f"❌ Registry file not found: {REGISTRY_PATH}")
        return False

    with open(REGISTRY_PATH, 'r') as f:
        registry = json.load(f)

    print("\n📊 GLOBAL_REGISTRY.json Analysis:")
    print("=" * 50)
    print(f"📅 Created: {registry.get('created_at', 'Unknown')}")
    print(f"\n📈 Counters:")
    print(f"  - total_tasks: {registry.get('total_tasks', 0)}")
    print(f"  - active_tasks: {registry.get('active_tasks', 0)}")
    print(f"  - total_agents_spawned: {registry.get('total_agents_spawned', 0)}")
    print(f"  - active_agents: {registry.get('active_agents', 0)}")
    print(f"  - max_concurrent_agents: {registry.get('max_concurrent_agents', 0)}")

    tasks = registry.get('tasks', {})
    print(f"\n📋 Tasks ({len(tasks)} total):")

    # Count by status
    status_counts = {}
    for task_data in tasks.values():
        status = task_data.get('status', 'UNKNOWN')
        status_counts[status] = status_counts.get(status, 0) + 1

    for status, count in sorted(status_counts.items()):
        print(f"  - {status}: {count}")

    # Check for inconsistencies
    print(f"\n⚠️  Consistency Check:")
    active_by_count = sum(1 for t in tasks.values()
                          if t.get('status') not in ('ARCHIVED', 'COMPLETED', 'FAILED'))
    if active_by_count != registry.get('active_tasks', 0):
        print(f"  ❌ active_tasks mismatch: counter={registry.get('active_tasks', 0)}, actual={active_by_count}")
    else:
        print(f"  ✅ active_tasks counter is consistent")

    return True


def backup_registry():
    """Create a timestamped backup of the registry."""
    if not REGISTRY_PATH.exists():
        print(f"❌ Registry file not found: {REGISTRY_PATH}")
        return False

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = REGISTRY_PATH.parent / f"GLOBAL_REGISTRY.json.backup_{timestamp}"

    shutil.copy2(REGISTRY_PATH, backup_path)
    print(f"✅ Backup created: {backup_path}")
    return True


def reset_registry(archive_tasks=True):
    """Reset active counts and optionally archive all tasks."""
    if not REGISTRY_PATH.exists():
        print(f"❌ Registry file not found: {REGISTRY_PATH}")
        return False

    # Create backup first
    if not backup_registry():
        return False

    # Load the registry
    with open(REGISTRY_PATH, 'r') as f:
        registry = json.load(f)

    print(f"\n📊 Before Reset:")
    print(f"  - active_tasks: {registry.get('active_tasks', 0)}")
    print(f"  - active_agents: {registry.get('active_agents', 0)}")

    # Reset active counts
    registry['active_tasks'] = 0
    registry['active_agents'] = 0

    # Optionally archive all tasks
    archived_count = 0
    if archive_tasks:
        for task_id, task_data in registry.get('tasks', {}).items():
            if task_data.get('status') not in ('ARCHIVED', 'COMPLETED', 'FAILED'):
                task_data['status'] = 'ARCHIVED'
                task_data['archived_at'] = datetime.now().isoformat()
                archived_count += 1

    # Save the cleaned registry
    with open(REGISTRY_PATH, 'w') as f:
        json.dump(registry, f, indent=2)

    print(f"\n✅ Reset Complete:")
    print(f"  - active_tasks: 0")
    print(f"  - active_agents: 0")
    if archive_tasks:
        print(f"  - {archived_count} tasks marked as ARCHIVED")

    return True


def main():
    """Main CLI interface."""
    if len(sys.argv) < 2:
        print("Usage: python manage_registry.py [analyze|reset|backup]")
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == 'analyze':
        success = analyze_registry()
    elif command == 'reset':
        confirm = input("⚠️  This will reset active counts. Continue? [y/N]: ")
        if confirm.lower() == 'y':
            success = reset_registry()
        else:
            print("Cancelled.")
            success = True
    elif command == 'backup':
        success = backup_registry()
    else:
        print(f"Unknown command: {command}")
        print("Available commands: analyze, reset, backup")
        success = False

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()