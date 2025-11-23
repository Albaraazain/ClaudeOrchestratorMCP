#!/usr/bin/env python3
"""
PROOF: This demonstrates that cursor-agent backend is configured and working
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the actual functions that MCP uses
from real_mcp_server import (
    AGENT_BACKEND,
    CURSOR_AGENT_MODEL,
    check_cursor_agent_available,
    deploy_cursor_agent,
    create_real_task
)

print("="*70)
print("PROOF: Cursor-Agent Backend Configuration")
print("="*70)

print("\n[1] Backend Configuration:")
print(f"    AGENT_BACKEND = '{AGENT_BACKEND}'")
print(f"    CURSOR_AGENT_MODEL = '{CURSOR_AGENT_MODEL}'")

if AGENT_BACKEND == 'cursor':
    print("\n    ✅ DEFAULT: cursor-agent backend is configured")
else:
    print(f"\n    ❌ DEFAULT: {AGENT_BACKEND} backend is configured")

print("\n[2] Cursor-Agent Availability:")
available = check_cursor_agent_available()
print(f"    cursor-agent installed: {available}")

if available:
    print("    ✅ cursor-agent is ready to use")
else:
    print("    ❌ cursor-agent not found (will fail)")

print("\n[3] Deployment Flow Test:")
print("    Creating test task...")

try:
    task_result = create_real_task(
        description="Backend verification test",
        priority="P3",
        client_cwd=os.getcwd()
    )
    
    if not task_result.get('success'):
        print(f"    ❌ Failed to create task: {task_result.get('error')}")
        sys.exit(1)
    
    task_id = task_result['task_id']
    print(f"    ✅ Task created: {task_id}")
    
    print("\n[4] Deploying agent (this will use cursor-agent)...")
    
    # Call deploy_cursor_agent directly to prove it works
    result = deploy_cursor_agent(
        task_id=task_id,
        agent_type="proof-test",
        prompt="What is 1+1? Just answer with the number."
    )
    
    print("\n[5] Deployment Result:")
    if result.get('success'):
        print(f"    ✅ SUCCESS - Agent deployed!")
        print(f"    Agent ID: {result['agent_id']}")
        print(f"    Backend: {result.get('deployment_method')}")
        print(f"    Model: {result.get('model')}")
        print(f"    PID: {result.get('cursor_pid')}")
        print(f"    Log: {result.get('log_file')}")
        
        if result.get('deployment_method') == 'cursor-agent':
            print("\n    ✅✅✅ VERIFIED: Using cursor-agent backend!")
            
            # Check the log file exists
            log_file = result.get('log_file')
            if log_file and os.path.exists(log_file):
                print(f"\n    Log file created: {log_file}")
                print("    Waiting 5 seconds for cursor-agent to start...")
                import time
                time.sleep(5)
                
                # Check if log has content
                with open(log_file, 'r') as f:
                    content = f.read()
                    if content:
                        print(f"    Log file has {len(content)} bytes")
                        # Show first few lines
                        lines = content.split('\n')[:3]
                        print("\n    First few log lines:")
                        for line in lines:
                            if line:
                                print(f"      {line[:100]}")
                    else:
                        print("    Log file is empty (cursor-agent may still be starting)")
            
            # Try to kill the agent
            print("\n[6] Cleaning up...")
            pid = result.get('cursor_pid')
            if pid:
                try:
                    os.kill(pid, 9)
                    print(f"    ✅ Killed cursor-agent process {pid}")
                except:
                    print(f"    Process {pid} already terminated")
        else:
            print(f"\n    ⚠️  Used {result.get('deployment_method')} instead of cursor-agent!")
    else:
        print(f"    ❌ FAILED: {result.get('error')}")
        
except Exception as e:
    print(f"    ❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*70)
print("TEST COMPLETE")
print("="*70)

