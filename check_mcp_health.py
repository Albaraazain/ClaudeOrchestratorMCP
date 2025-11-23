#!/usr/bin/env python3
"""
Quick health check for Claude Orchestrator MCP
Run this to verify everything is working correctly
"""

import os
import json
import subprocess
import sys

def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")

def check_config():
    """Check if MCP config exists and is valid"""
    print("1️⃣  Checking MCP Configuration...")
    config_path = os.path.expanduser("~/.cursor/mcp.json")
    
    if not os.path.exists(config_path):
        print("   ❌ MCP config not found at ~/.cursor/mcp.json")
        return False
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        if 'claude-orchestrator' not in config.get('mcpServers', {}):
            print("   ❌ claude-orchestrator not configured in MCP config")
            return False
        
        server_config = config['mcpServers']['claude-orchestrator']
        server_path = server_config['args'][0]
        
        print(f"   ✅ MCP config exists")
        print(f"   ✅ claude-orchestrator configured")
        print(f"   📁 Server path: {server_path}")
        
        if not os.path.exists(server_path):
            print(f"   ⚠️  Warning: Server file not found at {server_path}")
            return False
        
        print(f"   ✅ Server file exists")
        return True
    except Exception as e:
        print(f"   ❌ Error reading config: {e}")
        return False

def check_server_health():
    """Check if MCP server can start"""
    print("\n2️⃣  Checking Server Health...")
    
    try:
        # Try to import the server
        sys.path.insert(0, os.path.dirname(__file__))
        import real_mcp_server
        print("   ✅ Server imports successfully")
        
        # Check for required functions
        required_functions = [
            'create_real_task',
            'deploy_headless_agent',
            'get_real_task_status',
            'find_task_workspace'
        ]
        
        for func in required_functions:
            if hasattr(real_mcp_server, func):
                print(f"   ✅ Function '{func}' found")
            else:
                print(f"   ❌ Function '{func}' missing")
                return False
        
        return True
    except Exception as e:
        print(f"   ❌ Error importing server: {e}")
        return False

def check_workspace():
    """Check workspace setup"""
    print("\n3️⃣  Checking Workspace...")
    
    workspace = os.path.expanduser("~/.agent-workspace")
    
    if not os.path.exists(workspace):
        print(f"   ℹ️  Workspace doesn't exist yet (will be created on first use)")
        print(f"   📁 Location: {workspace}")
        return True
    
    print(f"   ✅ Workspace exists: {workspace}")
    
    # Check for global registry
    registry = os.path.join(workspace, "registry", "GLOBAL_REGISTRY.json")
    if os.path.exists(registry):
        try:
            with open(registry, 'r') as f:
                reg_data = json.load(f)
            task_count = len(reg_data.get('tasks', {}))
            print(f"   ✅ Global registry exists with {task_count} tasks")
        except Exception as e:
            print(f"   ⚠️  Registry exists but couldn't read: {e}")
    else:
        print(f"   ℹ️  Registry will be created on first task")
    
    return True

def check_cursor_agent():
    """Check if cursor-agent is available"""
    print("\n4️⃣  Checking cursor-agent...")
    
    try:
        result = subprocess.run(
            ['cursor-agent', '--version'],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            print(f"   ✅ cursor-agent available: {version}")
            return True
        else:
            print(f"   ⚠️  cursor-agent found but returned error")
            return False
    except FileNotFoundError:
        print(f"   ⚠️  cursor-agent not found (optional, but recommended)")
        print(f"   💡 Install: curl https://cursor.com/install -fsSL | bash")
        return True  # Not a critical failure
    except Exception as e:
        print(f"   ⚠️  Error checking cursor-agent: {e}")
        return True  # Not a critical failure

def check_processes():
    """Check for running MCP processes"""
    print("\n5️⃣  Checking Running Processes...")
    
    try:
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True
        )
        
        mcp_processes = [line for line in result.stdout.split('\n') 
                         if 'real_mcp_server.py' in line and 'grep' not in line]
        
        if mcp_processes:
            print(f"   ✅ Found {len(mcp_processes)} MCP server process(es)")
            for proc in mcp_processes[:3]:  # Show first 3
                parts = proc.split()
                if len(parts) >= 2:
                    print(f"      PID: {parts[1]}")
        else:
            print(f"   ℹ️  No MCP server processes running")
            print(f"   💡 Cursor will start them automatically when needed")
        
        return True
    except Exception as e:
        print(f"   ⚠️  Couldn't check processes: {e}")
        return True  # Not a critical failure

def main():
    print_header("Claude Orchestrator MCP Health Check")
    
    results = {
        'config': check_config(),
        'server': check_server_health(),
        'workspace': check_workspace(),
        'cursor_agent': check_cursor_agent(),
        'processes': check_processes()
    }
    
    print_header("Summary")
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {status} - {name}")
    
    print(f"\n   Score: {passed}/{total} checks passed")
    
    if all(results.values()):
        print("\n🎉 All checks passed! Your MCP is ready to use!")
        print("\n📋 Next Steps:")
        print("   1. In Cursor, press Cmd+Shift+P")
        print("   2. Type: 'MCP: Restart All Servers'")
        print("   3. Wait 10 seconds for connection")
        print("   4. Ask Claude to create a task!")
        print("\n💡 Tip: Check MCP_QUICK_START.md for usage guide")
    else:
        print("\n⚠️  Some checks failed. Please review the errors above.")
        print("\n📋 Troubleshooting:")
        print("   1. Run: ./restart_mcp.sh")
        print("   2. Check: ~/.cursor/mcp.json")
        print("   3. See: MCP_QUICK_START.md")
    
    sys.exit(0 if all(results.values()) else 1)

if __name__ == "__main__":
    main()



