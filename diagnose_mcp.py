#!/usr/bin/env python3
"""
Diagnose MCP connection issues and test the orchestrator.
"""

import sys
import os
import json
import subprocess

def print_section(title):
    print(f"\n{'='*70}")
    print(f" {title}")
    print(f"{'='*70}\n")

def check_mcp_config():
    """Check MCP configuration."""
    print_section("MCP Configuration")
    
    config_path = os.path.expanduser("~/.cursor/mcp.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
        print(f"✅ Config file exists: {config_path}")
        
        if "claude-orchestrator" in config.get("mcpServers", {}):
            server_config = config["mcpServers"]["claude-orchestrator"]
            print(f"✅ Server configured: claude-orchestrator")
            print(f"   Command: {server_config.get('command')}")
            print(f"   Args: {server_config.get('args')}")
        else:
            print("❌ claude-orchestrator not found in config")
    else:
        print(f"❌ Config file not found: {config_path}")

def check_server_process():
    """Check if MCP server is running."""
    print_section("Server Process")
    
    result = subprocess.run(
        ["ps", "aux"],
        capture_output=True,
        text=True
    )
    
    lines = [line for line in result.stdout.split('\n') 
             if 'real_mcp_server.py' in line and 'grep' not in line]
    
    if lines:
        print(f"✅ Server process found ({len(lines)} instance(s)):")
        for line in lines:
            parts = line.split()
            pid = parts[1]
            print(f"   PID: {pid}")
            print(f"   {line}")
    else:
        print("❌ Server process not running")

def check_server_health():
    """Test server functionality directly."""
    print_section("Server Health Check")
    
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import real_mcp_server
        
        print("✅ Module imports successfully")
        
        # Test task creation
        result = real_mcp_server.create_real_task.fn(
            description="Diagnostic test task",
            priority="P2"
        )
        
        if result.get("success"):
            print(f"✅ Task creation works")
            print(f"   Task ID: {result['task_id']}")
            return result['task_id']
        else:
            print(f"❌ Task creation failed: {result.get('error')}")
            return None
            
    except Exception as e:
        print(f"❌ Error testing server: {e}")
        return None

def suggest_fixes():
    """Suggest fixes for common issues."""
    print_section("Troubleshooting Steps")
    
    print("If the MCP tools aren't working in Cursor, try these steps:\n")
    
    print("1️⃣  RESTART CURSOR")
    print("   - Completely quit Cursor (Cmd+Q)")
    print("   - Reopen Cursor")
    print("   - Wait 10 seconds for MCP servers to connect\n")
    
    print("2️⃣  CHECK SERVER LOGS")
    print("   - Look for error messages in Cursor's output panel")
    print("   - Check: View > Output > MCP\n")
    
    print("3️⃣  VERIFY CONNECTION IN CURSOR")
    print("   - In Cursor chat, type: list_mcp_resources()")
    print("   - You should see 'claude-orchestrator' resources\n")
    
    print("4️⃣  MANUALLY RESTART THE SERVER")
    print("   - Kill the process: pkill -f real_mcp_server.py")
    print("   - Cursor will auto-restart it when needed\n")
    
    print("5️⃣  RE-ADD THE SERVER")
    print("   Run these commands:")
    print("   cd /Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP")
    print("   # If using Cursor's settings, manually edit ~/.cursor/mcp.json")
    print("   # Or reinstall using the install script\n")

def main():
    print("\n" + "="*70)
    print(" Claude Orchestrator MCP - Diagnostic Tool")
    print("="*70)
    
    check_mcp_config()
    check_server_process()
    task_id = check_server_health()
    suggest_fixes()
    
    print_section("Summary")
    
    if task_id:
        print("✅ SERVER IS FUNCTIONAL")
        print(f"   Test task created: {task_id}")
        print("\n📌 The server backend works perfectly!")
        print("📌 If MCP tools don't work in Cursor, it's a CONNECTION issue.")
        print("\n💡 Most likely fix: RESTART CURSOR completely (Cmd+Q, then reopen)")
        print("   This will re-establish the MCP connection.")
    else:
        print("❌ SERVER HAS ISSUES")
        print("   Check the error messages above.")
    
    print("\n" + "="*70 + "\n")

if __name__ == "__main__":
    main()






