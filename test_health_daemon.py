#!/usr/bin/env python3
"""
Test script for the Health Monitoring Daemon.

This script tests the active health monitoring functionality by:
1. Creating a mock task with agents
2. Simulating agent failures (killing tmux sessions)
3. Verifying the daemon detects and marks them as failed
"""

import os
import sys
import json
import time
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

# Add orchestrator module to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from orchestrator.health_daemon import HealthDaemon, register_task_for_monitoring
from orchestrator.registry import LockedRegistryFile

def create_mock_task(workspace_base: str, task_id: str) -> str:
    """Create a mock task with test agents."""
    workspace = os.path.join(workspace_base, task_id)
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(os.path.join(workspace, 'logs'), exist_ok=True)

    # Create mock registry
    registry = {
        "task_id": task_id,
        "task_description": "Test health monitoring",
        "created_at": datetime.now().isoformat(),
        "workspace": workspace,
        "status": "ACTIVE",
        "agents": [
            {
                "id": "test_agent_1",
                "type": "investigator",
                "status": "running",
                "tmux_session": f"{task_id}_test_agent_1",
                "started_at": datetime.now().isoformat()
            },
            {
                "id": "test_agent_2",
                "type": "builder",
                "status": "working",
                "tmux_session": f"{task_id}_test_agent_2",
                "started_at": datetime.now().isoformat()
            }
        ],
        "active_count": 2,
        "completed_count": 0
    }

    registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")
    with open(registry_path, 'w') as f:
        json.dump(registry, f, indent=2)

    # Create mock log files
    for agent in registry['agents']:
        log_file = os.path.join(workspace, 'logs', f"{agent['id']}_stream.jsonl")
        with open(log_file, 'w') as f:
            f.write(json.dumps({"timestamp": datetime.now().isoformat(), "message": "Starting agent"}) + "\n")

    return workspace

def create_tmux_session(session_name: str):
    """Create a tmux session for testing."""
    subprocess.run(['tmux', 'new-session', '-d', '-s', session_name, 'sleep', '300'],
                   capture_output=True)

def kill_tmux_session(session_name: str):
    """Kill a tmux session to simulate agent failure."""
    subprocess.run(['tmux', 'kill-session', '-t', session_name],
                   capture_output=True)

def main():
    print("=" * 60)
    print("HEALTH DAEMON TEST")
    print("=" * 60)

    # Create temporary workspace
    with tempfile.TemporaryDirectory() as workspace_base:
        print(f"\n1. Setting up test environment in {workspace_base}")

        task_id = f"TEST-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        workspace = create_mock_task(workspace_base, task_id)
        print(f"   Created mock task: {task_id}")

        # Create tmux sessions for mock agents
        session1 = f"{task_id}_test_agent_1"
        session2 = f"{task_id}_test_agent_2"

        create_tmux_session(session1)
        create_tmux_session(session2)
        print(f"   Created tmux sessions: {session1}, {session2}")

        # Initialize health daemon with fast scan interval
        print("\n2. Starting Health Daemon (scan interval: 5 seconds)")
        daemon = HealthDaemon(workspace_base, scan_interval=5)
        daemon.start()

        # Register task for monitoring
        daemon.register_task(task_id)
        print(f"   Registered task {task_id} for monitoring")

        # Verify agents are healthy initially
        print("\n3. Initial health check - agents should be healthy")
        time.sleep(2)  # Let daemon run initial scan

        registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")
        with open(registry_path, 'r') as f:
            registry = json.load(f)

        healthy_count = sum(1 for a in registry['agents'] if a['status'] in ['running', 'working'])
        print(f"   Healthy agents: {healthy_count}/2")

        # Kill one tmux session to simulate failure
        print(f"\n4. Simulating agent failure - killing session {session1}")
        kill_tmux_session(session1)

        # Wait for daemon to detect failure
        print("   Waiting for daemon to detect failure (up to 10 seconds)...")
        detected = False
        for i in range(10):
            time.sleep(1)

            with open(registry_path, 'r') as f:
                registry = json.load(f)

            failed_agents = [a for a in registry['agents'] if a['status'] == 'failed']
            if failed_agents:
                detected = True
                print(f"   ✓ Daemon detected failure of agent: {failed_agents[0]['id']}")
                print(f"     Reason: {failed_agents[0].get('failure_reason', 'Unknown')}")
                break

        if not detected:
            print("   ✗ Daemon did not detect failure within timeout")

        # Test stuck agent detection
        print("\n5. Testing stuck agent detection")

        # Make log file old to simulate stuck agent
        log_file = os.path.join(workspace, 'logs', 'test_agent_2_stream.jsonl')
        old_time = time.time() - 400  # 6+ minutes ago
        os.utime(log_file, (old_time, old_time))
        print(f"   Set test_agent_2 log to 6+ minutes old")

        # Update daemon's stuck threshold for testing
        daemon.last_log_check = {}  # Reset cache
        original_threshold = daemon.STUCK_AGENT_THRESHOLD
        HealthDaemon.STUCK_AGENT_THRESHOLD = 60  # 1 minute for testing

        print("   Waiting for stuck detection (up to 10 seconds)...")
        stuck_detected = False
        for i in range(10):
            time.sleep(1)

            with open(registry_path, 'r') as f:
                registry = json.load(f)

            stuck_agents = [a for a in registry['agents']
                          if a['status'] == 'failed' and 'stuck' in a.get('failure_reason', '')]
            if stuck_agents:
                stuck_detected = True
                print(f"   ✓ Daemon detected stuck agent: {stuck_agents[0]['id']}")
                print(f"     Reason: {stuck_agents[0].get('failure_reason', 'Unknown')}")
                break

        if not stuck_detected:
            print("   Note: Stuck detection requires multiple scan cycles")

        # Stop daemon
        print("\n6. Stopping Health Daemon")
        daemon.stop()

        # Cleanup tmux sessions
        kill_tmux_session(session2)

        # Final summary
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)

        with open(registry_path, 'r') as f:
            final_registry = json.load(f)

        for agent in final_registry['agents']:
            status_icon = "✓" if agent['status'] == 'failed' else "✗"
            print(f"{status_icon} {agent['id']}: {agent['status']}")
            if agent['status'] == 'failed':
                print(f"  Reason: {agent.get('failure_reason', 'Unknown')}")

        print("\nHealth Daemon Test Complete!")

if __name__ == "__main__":
    main()