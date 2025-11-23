#!/usr/bin/env python3
"""
Test script for cursor-agent deployment workflow

Tests the complete lifecycle:
1. Deploy cursor-agent
2. Monitor output
3. Get parsed results
4. Kill agent
5. Cleanup
"""

import sys
import os
import time
import json

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Set environment to use cursor backend
os.environ['CLAUDE_ORCHESTRATOR_BACKEND'] = 'cursor'
os.environ['CURSOR_AGENT_MODEL'] = 'auto'

# Import functions from real_mcp_server
from real_mcp_server import (
    create_real_task,
    deploy_headless_agent,
    get_agent_output,
    kill_real_agent,
    AGENT_BACKEND
)

def test_deployment_workflow():
    """Test complete cursor-agent deployment workflow"""
    print("\n" + "="*70)
    print("TEST: Cursor Agent Deployment Workflow")
    print("="*70)
    
    print(f"\n✓ Backend configured: {AGENT_BACKEND}")
    
    # Step 1: Create a test task
    print("\n[1/5] Creating test task...")
    task_result = create_real_task(
        description="Test cursor-agent deployment",
        priority="P2",
        client_cwd=os.getcwd()
    )
    
    if not task_result.get('success'):
        print(f"❌ Failed to create task: {task_result.get('error')}")
        return False
    
    task_id = task_result['task_id']
    print(f"✓ Task created: {task_id}")
    
    try:
        # Step 2: Deploy cursor-agent
        print("\n[2/5] Deploying cursor-agent...")
        deploy_result = deploy_headless_agent(
            task_id=task_id,
            agent_type="test-agent",
            prompt="What is 2+2? Just answer with the number and explain briefly."
        )
        
        if not deploy_result.get('success'):
            print(f"❌ Failed to deploy: {deploy_result.get('error')}")
            return False
        
        agent_id = deploy_result['agent_id']
        cursor_pid = deploy_result.get('cursor_pid')
        print(f"✓ Agent deployed: {agent_id}")
        print(f"✓ PID: {cursor_pid}")
        print(f"✓ Method: {deploy_result.get('deployment_method')}")
        print(f"✓ Model: {deploy_result.get('model')}")
        
        # Step 3: Wait for agent to process
        print("\n[3/5] Waiting for agent to complete...")
        max_wait = 30  # seconds
        wait_interval = 2
        elapsed = 0
        
        while elapsed < max_wait:
            time.sleep(wait_interval)
            elapsed += wait_interval
            
            # Check if log file has final result
            output_result = get_agent_output(
                task_id=task_id,
                agent_id=agent_id,
                format="parsed"
            )
            
            if output_result.get('success'):
                final_result = output_result.get('output', {}).get('final_result')
                if final_result:
                    print(f"✓ Agent completed after {elapsed}s")
                    break
            
            print(f"  Waiting... ({elapsed}s / {max_wait}s)")
        
        # Step 4: Get and display output
        print("\n[4/5] Getting agent output...")
        
        # Get text format
        text_output = get_agent_output(
            task_id=task_id,
            agent_id=agent_id,
            format="text",
            include_metadata=True
        )
        
        if text_output.get('success'):
            print("✓ Text output retrieved:")
            print("-" * 70)
            print(text_output['output'][:500])
            if len(text_output['output']) > 500:
                print(f"\n... ({len(text_output['output']) - 500} more characters)")
            print("-" * 70)
            
            # Show metadata
            if text_output.get('metadata'):
                meta = text_output['metadata']
                print(f"\n✓ Metadata:")
                print(f"  Duration: {meta.get('duration_ms')}ms")
                print(f"  Events: {meta.get('event_count')}")
                print(f"  Tool calls: {meta.get('tool_call_count')}")
                print(f"  Model: {meta.get('model')}")
        else:
            print(f"⚠️ Failed to get text output: {text_output.get('error')}")
        
        # Get parsed format
        parsed_output = get_agent_output(
            task_id=task_id,
            agent_id=agent_id,
            format="parsed"
        )
        
        if parsed_output.get('success'):
            output_data = parsed_output['output']
            print(f"\n✓ Parsed output retrieved:")
            print(f"  Session ID: {output_data.get('session_id')}")
            print(f"  Assistant messages: {len(output_data.get('assistant_messages', []))}")
            print(f"  Tool calls: {len(output_data.get('tool_calls', []))}")
            
            # Show assistant messages
            for i, msg in enumerate(output_data.get('assistant_messages', [])[:3], 1):
                print(f"\n  Message {i}: {msg[:200]}")
            
            # Show tool calls
            for tool in output_data.get('tool_calls', [])[:3]:
                print(f"\n  Tool: {tool.get('tool_type')} [{tool.get('status')}]")
                if tool.get('tool_type') == 'shell':
                    print(f"    Command: {tool.get('command')}")
                elif tool.get('tool_type') == 'edit':
                    print(f"    Path: {tool.get('path')}")
        
        # Step 5: Kill agent
        print("\n[5/5] Killing agent...")
        kill_result = kill_real_agent(
            task_id=task_id,
            agent_id=agent_id,
            reason="Test complete"
        )
        
        if kill_result.get('success'):
            print(f"✓ Agent killed")
            print(f"  Method: cursor process termination")
            print(f"  PID killed: {kill_result.get('cleanup', {}).get('cursor_pid')}")
        else:
            print(f"⚠️ Failed to kill agent: {kill_result.get('error')}")
        
        print("\n" + "="*70)
        print("✅ TEST PASSED: Full deployment workflow completed")
        print("="*70)
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run deployment workflow test"""
    print("\n" + "="*70)
    print("CURSOR AGENT DEPLOYMENT TEST")
    print("="*70)
    
    # Check prerequisites
    from real_mcp_server import check_cursor_agent_available
    
    if not check_cursor_agent_available():
        print("\n❌ SKIPPED: cursor-agent not available")
        print("Install with: curl https://cursor.com/install -fsSL | bash")
        return 1
    
    print("\n✓ cursor-agent is available")
    
    # Run test
    success = test_deployment_workflow()
    
    if success:
        print("\n🎉 All deployment tests passed!")
        return 0
    else:
        print("\n❌ Deployment test failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())

