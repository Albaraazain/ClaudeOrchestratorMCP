#!/usr/bin/env python3
"""
Test script to verify race condition fix in update_agent_progress.

This script demonstrates that the LockedRegistryFile prevents race conditions
when multiple agents update their progress concurrently.
"""

import json
import os
import time
import threading
from datetime import datetime
import tempfile
import shutil
from pathlib import Path

# Import the fixed module components
import sys
sys.path.insert(0, '/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP')
from orchestrator.registry import LockedRegistryFile

def create_test_registry(path: str, num_agents: int = 5):
    """Create a test registry file with mock agents."""
    registry = {
        "task_id": "TEST-TASK-001",
        "active_count": num_agents,
        "completed_count": 0,
        "agents": []
    }

    for i in range(num_agents):
        registry["agents"].append({
            "id": f"agent-{i}",
            "status": "working",
            "progress": 0,
            "last_update": datetime.now().isoformat()
        })

    with open(path, 'w') as f:
        json.dump(registry, f, indent=2)

    return registry

def simulate_agent_update(registry_path: str, agent_id: str, iterations: int = 10):
    """Simulate an agent updating its progress multiple times."""
    for i in range(iterations):
        try:
            # Use LockedRegistryFile to prevent race conditions
            with LockedRegistryFile(registry_path, timeout=5) as (registry, f):
                # Find and update agent
                for agent in registry['agents']:
                    if agent['id'] == agent_id:
                        agent['progress'] = (i + 1) * 10
                        agent['last_update'] = datetime.now().isoformat()

                        # Simulate some processing time
                        time.sleep(0.01)

                        # Complete on last iteration
                        if i == iterations - 1:
                            previous_status = agent['status']
                            agent['status'] = 'completed'

                            # Update counts if transitioning to completed
                            if previous_status in ['working', 'running']:
                                registry['active_count'] = max(0, registry.get('active_count', 1) - 1)
                                registry['completed_count'] = registry.get('completed_count', 0) + 1
                        break

                # Write back atomically
                f.seek(0)
                f.write(json.dumps(registry, indent=2))
                f.truncate()

            print(f"[{agent_id}] Updated progress to {(i+1)*10}%")

        except Exception as e:
            print(f"[{agent_id}] Error updating: {e}")

def test_concurrent_updates():
    """Test that concurrent updates don't cause race conditions."""
    print("\n=== Testing Concurrent Registry Updates ===\n")

    # Create temporary test directory
    test_dir = tempfile.mkdtemp(prefix="race_condition_test_")
    registry_path = os.path.join(test_dir, "AGENT_REGISTRY.json")

    try:
        # Create test registry with 5 agents
        num_agents = 5
        initial_registry = create_test_registry(registry_path, num_agents)
        print(f"Created test registry with {num_agents} agents at: {registry_path}")
        print(f"Initial active_count: {initial_registry['active_count']}")
        print(f"Initial completed_count: {initial_registry['completed_count']}\n")

        # Create threads for concurrent updates
        threads = []
        for i in range(num_agents):
            agent_id = f"agent-{i}"
            thread = threading.Thread(
                target=simulate_agent_update,
                args=(registry_path, agent_id, 5)
            )
            threads.append(thread)

        print("Starting concurrent agent updates...")
        start_time = time.time()

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        elapsed = time.time() - start_time
        print(f"\nAll agents completed in {elapsed:.2f} seconds")

        # Verify final state
        with open(registry_path, 'r') as f:
            final_registry = json.load(f)

        print("\n=== Final Registry State ===")
        print(f"Active count: {final_registry['active_count']} (expected: 0)")
        print(f"Completed count: {final_registry['completed_count']} (expected: {num_agents})")

        # Check each agent's final state
        all_completed = True
        for agent in final_registry['agents']:
            status = agent['status']
            progress = agent['progress']
            print(f"  {agent['id']}: status={status}, progress={progress}%")
            if status != 'completed' or progress != 50:
                all_completed = False

        # Verify integrity
        print("\n=== Verification Results ===")
        if final_registry['active_count'] == 0:
            print("✓ Active count correctly decremented to 0")
        else:
            print(f"✗ Active count is {final_registry['active_count']}, expected 0 (RACE CONDITION!)")

        if final_registry['completed_count'] == num_agents:
            print(f"✓ Completed count correctly incremented to {num_agents}")
        else:
            print(f"✗ Completed count is {final_registry['completed_count']}, expected {num_agents} (RACE CONDITION!)")

        if all_completed:
            print("✓ All agents reached completed status with 50% progress")
        else:
            print("✗ Some agents didn't complete properly (RACE CONDITION!)")

        # Overall result
        success = (
            final_registry['active_count'] == 0 and
            final_registry['completed_count'] == num_agents and
            all_completed
        )

        if success:
            print("\n🎉 SUCCESS: No race conditions detected! LockedRegistryFile is working correctly.")
        else:
            print("\n❌ FAILURE: Race conditions detected! Registry counters are corrupted.")

    finally:
        # Cleanup
        shutil.rmtree(test_dir)
        print(f"\nCleaned up test directory: {test_dir}")

if __name__ == "__main__":
    test_concurrent_updates()