#!/usr/bin/env python3
"""
Test script to verify Claude Orchestrator MCP server functionality.

This script tests all MCP tools directly to ensure they work correctly.
Run this after restarting Cursor to verify the MCP connection.

Usage:
    python3 test_mcp_connection.py
"""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import real_mcp_server
import json
from datetime import datetime

def print_test_header(test_name):
    """Print a formatted test header."""
    print(f"\n{'='*70}")
    print(f" {test_name}")
    print(f"{'='*70}")

def print_result(success, message):
    """Print test result."""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status}: {message}")

def test_create_task():
    """Test create_real_task tool."""
    print_test_header("TEST 1: create_real_task")
    
    try:
        result = real_mcp_server.create_real_task.fn(
            description="MCP Connection Test - Automated Testing",
            priority="P2"
        )
        
        if result.get("success"):
            task_id = result.get("task_id")
            print_result(True, f"Task created: {task_id}")
            print(f"   Workspace: {result.get('workspace')}")
            return task_id
        else:
            print_result(False, f"Task creation failed: {result.get('error')}")
            return None
    except Exception as e:
        print_result(False, f"Exception: {e}")
        return None

def test_get_task_status(task_id):
    """Test get_real_task_status tool."""
    print_test_header("TEST 2: get_real_task_status")
    
    try:
        result = real_mcp_server.get_real_task_status.fn(task_id=task_id)
        
        if result.get("success"):
            print_result(True, f"Retrieved status for task {task_id}")
            print(f"   Status: {result.get('status')}")
            print(f"   Agents: {result.get('agents', {}).get('total_spawned', 0)} spawned, "
                  f"{result.get('agents', {}).get('active', 0)} active")
            return True
        else:
            print_result(False, f"Status retrieval failed: {result.get('error')}")
            return False
    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False

def test_update_progress(task_id, agent_id="test-agent-verify"):
    """Test update_agent_progress tool."""
    print_test_header("TEST 3: update_agent_progress")
    
    try:
        result = real_mcp_server.update_agent_progress.fn(
            task_id=task_id,
            agent_id=agent_id,
            status="working",
            message="Testing progress update functionality",
            progress=50
        )
        
        if result.get("success"):
            print_result(True, f"Progress update successful for {agent_id}")
            print(f"   Status: {result.get('own_update', {}).get('status')}")
            print(f"   Progress: {result.get('own_update', {}).get('progress')}%")
            return True
        else:
            print_result(False, f"Progress update failed: {result.get('error')}")
            return False
    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False

def test_report_finding(task_id, agent_id="test-agent-verify"):
    """Test report_agent_finding tool."""
    print_test_header("TEST 4: report_agent_finding")
    
    try:
        result = real_mcp_server.report_agent_finding.fn(
            task_id=task_id,
            agent_id=agent_id,
            finding_type="insight",
            severity="low",
            message="MCP server is functioning correctly",
            data={"test": "success", "timestamp": datetime.now().isoformat()}
        )
        
        if result.get("success"):
            print_result(True, f"Finding reported successfully for {agent_id}")
            finding = result.get('own_finding', {})
            print(f"   Type: {finding.get('finding_type')}")
            print(f"   Severity: {finding.get('severity')}")
            print(f"   Message: {finding.get('message')}")
            return True
        else:
            print_result(False, f"Finding report failed: {result.get('error')}")
            return False
    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False

def test_get_agent_output_error_handling(task_id):
    """Test get_agent_output error handling with non-existent agent."""
    print_test_header("TEST 5: get_agent_output (error handling)")
    
    try:
        result = real_mcp_server.get_agent_output.fn(
            task_id=task_id,
            agent_id="nonexistent-agent-12345"
        )
        
        if not result.get("success"):
            print_result(True, f"Correctly returned error for non-existent agent")
            print(f"   Error: {result.get('error')}")
            return True
        else:
            print_result(False, "Should have returned error for non-existent agent")
            return False
    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False

def test_workspace_files(task_id):
    """Test that workspace files were created correctly."""
    print_test_header("TEST 6: Workspace File Structure")
    
    try:
        workspace = real_mcp_server.find_task_workspace(task_id)
        if not workspace:
            print_result(False, "Task workspace not found")
            return False
        
        required_files = [
            "AGENT_REGISTRY.json",
        ]
        required_dirs = [
            "progress",
            "findings",
            "logs",
            "output"
        ]
        
        all_good = True
        for file in required_files:
            path = os.path.join(workspace, file)
            if os.path.exists(path):
                print_result(True, f"File exists: {file}")
            else:
                print_result(False, f"Missing file: {file}")
                all_good = False
        
        for dir in required_dirs:
            path = os.path.join(workspace, dir)
            if os.path.isdir(path):
                print_result(True, f"Directory exists: {dir}/")
            else:
                print_result(False, f"Missing directory: {dir}/")
                all_good = False
        
        return all_good
    except Exception as e:
        print_result(False, f"Exception: {e}")
        return False

def main():
    """Run all tests."""
    print("\n" + "="*70)
    print(" Claude Orchestrator MCP Server - Connection Test")
    print("="*70)
    print(f" Timestamp: {datetime.now().isoformat()}")
    print(f" Python: {sys.version.split()[0]}")
    print("="*70)
    
    results = []
    
    # Test 1: Create task
    task_id = test_create_task()
    results.append(("Create Task", task_id is not None))
    
    if not task_id:
        print("\n❌ Cannot continue testing without a task. Stopping.")
        return False
    
    # Test 2: Get task status
    results.append(("Get Task Status", test_get_task_status(task_id)))
    
    # Test 3: Update progress
    results.append(("Update Progress", test_update_progress(task_id)))
    
    # Test 4: Report finding
    results.append(("Report Finding", test_report_finding(task_id)))
    
    # Test 5: Error handling
    results.append(("Error Handling", test_get_agent_output_error_handling(task_id)))
    
    # Test 6: Workspace structure
    results.append(("Workspace Files", test_workspace_files(task_id)))
    
    # Summary
    print_test_header("TEST SUMMARY")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\n{'='*70}")
    print(f" Results: {passed}/{total} tests passed")
    print(f"={'='*70}\n")
    
    if passed == total:
        print("🎉 All tests passed! MCP server is fully functional.")
        print(f"\n📋 Test task ID: {task_id}")
        print(f"   You can check this task in Cursor using:")
        print(f"   mcp_claude-orchestrator_get_real_task_status('{task_id}')")
        return True
    else:
        print(f"⚠️  {total - passed} test(s) failed. Check errors above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

