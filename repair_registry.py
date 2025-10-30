#!/usr/bin/env python3
"""
Standalone Registry Repair Script

This script repairs corrupted agent registries by:
1. Scanning all active tmux sessions
2. Comparing with agents marked as active in registries
3. Marking zombie agents (no tmux session) as 'terminated'
4. Fixing active_count to match reality

Usage:
    python repair_registry.py --task TASK-ID [--dry-run] [--all]
    python repair_registry.py --global [--dry-run]
    python repair_registry.py --all [--dry-run]

Examples:
    # Dry-run on specific task
    python repair_registry.py --task TASK-20251029-233824-9cd33bdd --dry-run

    # Repair specific task
    python repair_registry.py --task TASK-20251029-233824-9cd33bdd

    # Repair all task registries
    python repair_registry.py --all

    # Check global registry health
    python repair_registry.py --global --dry-run
"""

import json
import subprocess
import fcntl
import argparse
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Set


def list_all_tmux_sessions() -> Dict[str, Any]:
    """List all active tmux sessions and extract agent session info."""
    try:
        result = subprocess.run(
            ['tmux', 'ls', '-F', '#{session_name}'],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            return {'success': False, 'error': 'No tmux sessions found or tmux error', 'sessions': []}

        # Parse tmux output - each line is a session name
        session_names = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]

        # Extract agent sessions (start with 'agent_')
        agent_sessions = {}
        for session_name in session_names:
            if session_name.startswith('agent_'):
                # Extract agent ID from session name: agent_TYPE-TIMESTAMP-HASH
                agent_id = session_name.replace('agent_', '')
                agent_sessions[session_name] = {
                    'agent_id': agent_id,
                    'session_name': session_name,
                    'is_agent': True
                }

        return {
            'success': True,
            'total_sessions': len(session_names),
            'agent_sessions': len(agent_sessions),
            'sessions': agent_sessions
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Exception listing tmux sessions: {str(e)}',
            'sessions': {}
        }


def validate_and_repair_registry(registry_path: str, dry_run: bool = False) -> Dict[str, Any]:
    """
    Scan tmux sessions and repair registry discrepancies.

    Args:
        registry_path: Path to AGENT_REGISTRY.json
        dry_run: If True, report what would be changed without actually changing

    Returns:
        Repair report with changes made
    """
    try:
        # Get actual tmux sessions
        tmux_result = list_all_tmux_sessions()
        if not tmux_result['success']:
            return {
                'success': False,
                'error': f"Failed to list tmux sessions: {tmux_result.get('error')}",
                'changes_made': 0
            }

        actual_sessions = set(tmux_result['sessions'].keys())

        # Acquire exclusive lock for modification
        with open(registry_path, 'r+') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive lock

            # Load current registry
            registry = json.load(f)

            # Track changes
            changes = {
                'zombies_terminated': [],
                'orphans_found': [],
                'count_corrected': False,
                'old_active_count': registry.get('active_count', 0),
                'new_active_count': 0
            }

            # Process all agents
            active_statuses = {'running', 'working', 'blocked'}
            actual_active_count = 0

            for agent in registry.get('agents', []):
                agent_status = agent.get('status')
                tmux_session = agent.get('tmux_session')

                # Check if agent claims to be active
                if agent_status in active_statuses:
                    # Verify tmux session exists
                    if tmux_session and tmux_session in actual_sessions:
                        # Agent is truly active
                        actual_active_count += 1
                    else:
                        # Zombie agent - mark as terminated
                        if not dry_run:
                            agent['status'] = 'terminated'
                            agent['termination_reason'] = 'session_not_found'
                            agent['terminated_at'] = datetime.now().isoformat()
                            agent['last_update'] = datetime.now().isoformat()

                        changes['zombies_terminated'].append({
                            'agent_id': agent['id'],
                            'agent_type': agent.get('type'),
                            'old_status': agent_status,
                            'tmux_session': tmux_session,
                            'started_at': agent.get('started_at')
                        })

            # Find orphan sessions
            registry_sessions = {
                agent.get('tmux_session')
                for agent in registry.get('agents', [])
                if agent.get('tmux_session')
            }

            for session in actual_sessions:
                if session not in registry_sessions:
                    changes['orphans_found'].append(session)

            # Fix active_count
            if registry.get('active_count', 0) != actual_active_count:
                changes['count_corrected'] = True
                changes['new_active_count'] = actual_active_count
                if not dry_run:
                    registry['active_count'] = actual_active_count
            else:
                changes['new_active_count'] = actual_active_count

            # Write changes if not dry run
            if not dry_run:
                f.seek(0)
                f.write(json.dumps(registry, indent=2))
                f.truncate()
                print(f"✓ Registry repaired: {len(changes['zombies_terminated'])} zombies terminated, "
                      f"active_count corrected to {actual_active_count}")

            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            return {
                'success': True,
                'dry_run': dry_run,
                'registry_path': registry_path,
                'changes': changes,
                'zombies_terminated': len(changes['zombies_terminated']),
                'orphans_found': len(changes['orphans_found']),
                'count_corrected': changes['count_corrected'],
                'summary': (
                    f"{'[DRY RUN] ' if dry_run else ''}Terminated {len(changes['zombies_terminated'])} zombies, "
                    f"found {len(changes['orphans_found'])} orphans, "
                    f"{'corrected' if changes['count_corrected'] else 'verified'} active_count "
                    f"({changes['old_active_count']} -> {changes['new_active_count']})"
                )
            }
    except FileNotFoundError:
        return {
            'success': False,
            'error': f'Registry not found: {registry_path}',
            'changes_made': 0
        }
    except Exception as e:
        return {
            'success': False,
            'error': f'Repair exception: {str(e)}',
            'changes_made': 0
        }


def find_all_task_registries(workspace_base: str) -> list:
    """Find all AGENT_REGISTRY.json files in workspace"""
    workspace_path = Path(workspace_base)
    registries = []

    for task_dir in workspace_path.glob('TASK-*'):
        registry_file = task_dir / 'AGENT_REGISTRY.json'
        if registry_file.exists():
            registries.append(str(registry_file))

    return registries


def print_report(result: Dict[str, Any]):
    """Pretty print repair report"""
    if not result['success']:
        print(f"❌ ERROR: {result['error']}")
        return

    print(f"\n{'='*80}")
    print(f"Registry: {result['registry_path']}")
    print(f"{'='*80}")
    print(f"\n{result['summary']}\n")

    if result['zombies_terminated'] > 0:
        print(f"🧟 Zombie Agents Terminated ({result['zombies_terminated']}):")
        for zombie in result['changes']['zombies_terminated']:
            print(f"  - {zombie['agent_id']} ({zombie['agent_type']}) - {zombie['old_status']}")
            print(f"    Session: {zombie['tmux_session']}")
            print(f"    Started: {zombie['started_at']}\n")

    if result['orphans_found'] > 0:
        print(f"👻 Orphan Sessions Found ({result['orphans_found']}):")
        for orphan in result['changes']['orphans_found']:
            print(f"  - {orphan}")

    if result['count_corrected']:
        print(f"\n📊 Active Count: {result['changes']['old_active_count']} → {result['changes']['new_active_count']}")


def main():
    parser = argparse.ArgumentParser(
        description='Repair corrupted agent registries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--task', type=str, help='Specific task ID to repair')
    parser.add_argument('--global', dest='global_reg', action='store_true', help='Repair global registry')
    parser.add_argument('--all', action='store_true', help='Repair all task registries')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be changed without changing')
    parser.add_argument('--workspace', type=str, default='.agent-workspace', help='Workspace base directory')

    args = parser.parse_args()

    # Validate arguments
    if not any([args.task, args.global_reg, args.all]):
        parser.error('Must specify --task, --global, or --all')

    registries_to_repair = []

    # Determine which registries to repair
    if args.task:
        registry_path = f"{args.workspace}/{args.task}/AGENT_REGISTRY.json"
        if not Path(registry_path).exists():
            print(f"❌ ERROR: Registry not found: {registry_path}")
            sys.exit(1)
        registries_to_repair.append(registry_path)

    if args.global_reg:
        global_registry_path = f"{args.workspace}/registry/GLOBAL_REGISTRY.json"
        if not Path(global_registry_path).exists():
            print(f"❌ ERROR: Global registry not found: {global_registry_path}")
            sys.exit(1)
        registries_to_repair.append(global_registry_path)

    if args.all:
        all_registries = find_all_task_registries(args.workspace)
        if not all_registries:
            print(f"❌ ERROR: No task registries found in {args.workspace}")
            sys.exit(1)
        registries_to_repair.extend(all_registries)

    # Repair each registry
    total_zombies = 0
    total_orphans = 0
    total_corrections = 0

    print(f"\n{'='*80}")
    print(f"Registry Repair Tool")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE REPAIR'}")
    print(f"Registries to process: {len(registries_to_repair)}")
    print(f"{'='*80}\n")

    for registry_path in registries_to_repair:
        result = validate_and_repair_registry(registry_path, dry_run=args.dry_run)
        print_report(result)

        if result['success']:
            total_zombies += result['zombies_terminated']
            total_orphans += result['orphans_found']
            if result['count_corrected']:
                total_corrections += 1

    # Final summary
    print(f"\n{'='*80}")
    print(f"REPAIR SUMMARY")
    print(f"{'='*80}")
    print(f"Registries processed: {len(registries_to_repair)}")
    print(f"Total zombies terminated: {total_zombies}")
    print(f"Total orphans found: {total_orphans}")
    print(f"Registries with count corrections: {total_corrections}")
    print(f"{'='*80}\n")

    if args.dry_run:
        print("⚠️  This was a DRY RUN. No changes were made.")
        print("   Remove --dry-run flag to apply these changes.\n")


if __name__ == '__main__':
    main()
