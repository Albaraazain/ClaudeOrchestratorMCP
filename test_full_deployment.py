#!/usr/bin/env python3
"""
Full deployment test - creates a task and deploys a real headless agent.

This tests the complete workflow:
1. Create task
2. Deploy headless agent
3. Monitor agent status
4. Verify agent is running
5. Retrieve agent output
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import real_mcp_server
from datetime import datetime

def print_header(text):
    """Print formatted header."""
    print(f"\n{'='*70}")
    print(f" {text}")
    print(f"{'='*70}")

def test_full_deployment():
    """Test complete agent deployment workflow."""
    print_header("Claude Orchestrator - Full Deployment Test")
    print(f"Timestamp: {datetime.now().isoformat()}")
    
    # Step 1: Create task
    print_header("STEP 1: Creating Task")
    task_result = real_mcp_server.create_real_task.fn(
        description="Test deployment: Create a simple hello.txt file with timestamp",
        priority="P2",
        client_cwd=os.getcwd()
    )
    
    if not task_result.get("success"):
        print(f"❌ Failed to create task: {task_result.get('error')}")
        return False
    
    task_id = task_result["task_id"]
    print(f"✅ Task created: {task_id}")
    print(f"   Workspace: {task_result['workspace']}")
    
    # Step 2: Deploy agent
    print_header("STEP 2: Deploying Headless Agent")
    agent_result = real_mcp_server.deploy_headless_agent.fn(
        task_id=task_id,
        agent_type="test_agent",
        prompt="""You are a test agent. Your job is simple:

1. Create a file named 'hello.txt' in the current directory
2. Write the message 'Hello from Claude Orchestrator!' to it
3. Add the current timestamp
4. Report your progress using update_agent_progress
5. Report your findings when done

This is a quick test to verify the orchestrator is working.""",
        parent="orchestrator"
    )
    
    if not agent_result.get("success"):
        print(f"❌ Failed to deploy agent: {agent_result.get('error')}")
        return False
    
    agent_id = agent_result["agent_id"]
    print(f"✅ Agent deployed: {agent_id}")
    print(f"   Type: {agent_result['agent_type']}")
    print(f"   Backend: {agent_result.get('backend', 'tmux')}")
    
    if agent_result.get('backend') == 'cursor':
        print(f"   Process ID: {agent_result.get('pid')}")
        print(f"   Log file: {agent_result.get('log_file')}")
    else:
        print(f"   Session: {agent_result.get('session_name')}")
    
    # Step 3: Wait a moment for agent to start
    print_header("STEP 3: Monitoring Agent")
    print("Waiting 3 seconds for agent to start...")
    time.sleep(3)
    
    # Step 4: Check task status
    status_result = real_mcp_server.get_real_task_status.fn(task_id=task_id)
    
    if not status_result.get("success"):
        print(f"❌ Failed to get status: {status_result.get('error')}")
        return False
    
    print(f"✅ Task status retrieved")
    print(f"   Status: {status_result['status']}")
    print(f"   Active agents: {status_result['agents']['active']}")
    print(f"   Total spawned: {status_result['agents']['total_spawned']}")
    
    # Step 5: Get agent output
    print_header("STEP 4: Retrieving Agent Output")
    output_result = real_mcp_server.get_agent_output.fn(
        task_id=task_id,
        agent_id=agent_id,
        tail=50,
        response_format="summary"
    )
    
    if not output_result.get("success"):
        print(f"⚠️  Could not get agent output: {output_result.get('error')}")
        print("   (This is normal if agent just started)")
    else:
        print(f"✅ Agent output retrieved")
        output = output_result.get('output', '')
        if output:
            print(f"\n   Recent output (last 50 lines):")
            print("   " + "-"*66)
            for line in output.split('\n')[:10]:  # Show first 10 lines
                print(f"   {line}")
            if output.count('\n') > 10:
                print(f"   ... ({output.count(chr(10)) - 10} more lines)")
    
    # Summary
    print_header("TEST SUMMARY")
    print(f"✅ Task ID: {task_id}")
    print(f"✅ Agent ID: {agent_id}")
    print(f"✅ Agent Status: {'RUNNING' if status_result['agents']['active'] > 0 else 'COMPLETED'}")
    print(f"\n📁 Task workspace: {task_result['workspace']}")
    print(f"\n📝 To monitor this agent in real-time, use:")
    print(f"   tail -f {task_result['workspace']}/output/{agent_id}.jsonl")
    print(f"\n🔍 To check task status:")
    print(f"   mcp_claude-orchestrator_get_real_task_status('{task_id}')")
    print(f"\n🛑 To kill the agent:")
    print(f"   mcp_claude-orchestrator_kill_real_agent('{task_id}', '{agent_id}')")
    
    return True

if __name__ == "__main__":
    try:
        success = test_full_deployment()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

