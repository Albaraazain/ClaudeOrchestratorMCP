#!/usr/bin/env python3
"""
Test script for the workspace service module.

Run this from the dashboard/backend directory:
    python test_workspace_service.py
"""

import sys
import os
import json
from pprint import pprint

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.workspace import WorkspaceService, get_workspace_service


def test_workspace_service():
    """Test the workspace service functions."""
    print("=" * 60)
    print("Testing Workspace Service")
    print("=" * 60)

    # Initialize service
    service = get_workspace_service()
    print(f"\n✓ Service initialized with base: {service.workspace_base}")

    # Test 1: List all tasks
    print("\n1. Testing list_tasks()...")
    tasks = service.list_tasks()
    if tasks:
        print(f"   Found {len(tasks)} tasks")
        for task in tasks[:3]:  # Show first 3
            print(f"   - {task['task_id']}: {task['description'][:50]}...")
    else:
        print("   No tasks found (workspace may be empty)")

    # Test 2: Get global registry
    print("\n2. Testing get_global_registry()...")
    global_reg = service.get_global_registry()
    if global_reg:
        print(f"   ✓ Global registry loaded")
        print(f"   Total tasks: {global_reg.get('total_tasks', 0)}")
        print(f"   Active tasks: {global_reg.get('active_tasks', 0)}")
        print(f"   Total agents spawned: {global_reg.get('total_agents_spawned', 0)}")
    else:
        print("   Global registry not found")

    # Test 3: Get a specific task registry (use the current task if available)
    print("\n3. Testing get_task_registry()...")
    current_task = "TASK-20260104-141158-50c60706"  # The current dashboard task

    # Try to find an existing task if current one doesn't exist
    if tasks and not any(t['task_id'] == current_task for t in tasks):
        current_task = tasks[0]['task_id']

    if current_task:
        print(f"   Testing with task: {current_task}")
        task_reg = service.get_task_registry(current_task)
        if task_reg:
            print(f"   ✓ Task registry loaded")
            print(f"   Description: {task_reg.get('task_description', 'N/A')[:60]}...")
            print(f"   Status: {task_reg.get('status', 'UNKNOWN')}")
            print(f"   Current phase: {task_reg.get('current_phase_index', 0)}")
            print(f"   Total agents: {len(task_reg.get('agents', []))}")

            # Test 4: Get task summary
            print("\n4. Testing get_task_summary()...")
            summary = service.get_task_summary(current_task)
            if summary:
                print(f"   ✓ Task summary generated")
                print(f"   Phases: {len(summary.get('phases', []))}")
                print(f"   Active agents: {summary['agent_stats']['active_count']}")
                print(f"   Completed agents: {summary['agent_stats']['completed_count']}")

            # Test 5: Get agent data (if agents exist)
            agents = task_reg.get('agents', [])
            if agents:
                test_agent = agents[0]
                agent_id = test_agent['id']
                print(f"\n5. Testing agent data functions with: {agent_id}")

                # Test progress
                print("   Testing get_agent_progress()...")
                progress = service.get_agent_progress(current_task, agent_id)
                if progress:
                    print(f"   ✓ Found {len(progress)} progress entries")
                    if progress:
                        latest = progress[-1]
                        print(f"   Latest: {latest.get('message', 'N/A')[:60]}...")
                else:
                    print("   No progress entries found")

                # Test findings
                print("   Testing get_agent_findings()...")
                findings = service.get_agent_findings(current_task, agent_id)
                if findings:
                    print(f"   ✓ Found {len(findings)} findings")
                    if findings:
                        latest = findings[-1]
                        print(f"   Latest: {latest.get('message', 'N/A')[:60]}...")
                else:
                    print("   No findings found")

                # Test logs
                print("   Testing get_agent_logs()...")
                logs = service.get_agent_logs(current_task, agent_id, lines=10)
                if logs:
                    print(f"   ✓ Found {len(logs)} log entries (last 10)")
                    # Show types of log entries
                    log_types = {}
                    for log in logs:
                        log_type = log.get('type', 'unknown')
                        log_types[log_type] = log_types.get(log_type, 0) + 1
                    print(f"   Log types: {log_types}")
                else:
                    print("   No logs found")
            else:
                print("\n5. No agents found in task to test agent functions")
        else:
            print(f"   Task registry not found for {current_task}")
    else:
        print("   No tasks available to test")

    print("\n" + "=" * 60)
    print("Workspace Service Test Complete")
    print("=" * 60)


def test_error_handling():
    """Test error handling in workspace service."""
    print("\n" + "=" * 60)
    print("Testing Error Handling")
    print("=" * 60)

    service = get_workspace_service()

    # Test with non-existent task
    print("\n1. Testing with non-existent task...")
    bad_task_id = "TASK-NONEXISTENT"
    result = service.get_task_registry(bad_task_id)
    if result is None:
        print("   ✓ Correctly returned None for non-existent task")
    else:
        print("   ✗ Should have returned None")

    # Test with non-existent agent
    print("\n2. Testing with non-existent agent...")
    logs = service.get_agent_logs("TASK-FAKE", "agent-fake", lines=10)
    if logs == []:
        print("   ✓ Correctly returned empty list for non-existent agent")
    else:
        print("   ✗ Should have returned empty list")

    print("\nError handling tests complete.")


if __name__ == "__main__":
    try:
        test_workspace_service()
        test_error_handling()
        print("\n✅ All tests completed successfully!")
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)