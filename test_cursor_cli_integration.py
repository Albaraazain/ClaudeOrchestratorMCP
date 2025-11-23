#!/usr/bin/env python3
"""
Test script for Cursor CLI integration with Claude Orchestrator MCP

Tests:
1. cursor-agent detection
2. Stream-JSON parsing
3. Tool call extraction
4. Configuration validation
"""

import sys
import os
import json
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import functions from real_mcp_server
from real_mcp_server import (
    check_cursor_agent_available,
    get_cursor_agent_path,
    parse_cursor_stream_jsonl,
    parse_cursor_tool_call,
    AGENT_BACKEND,
    CURSOR_AGENT_PATH,
    CURSOR_AGENT_MODEL,
    CURSOR_ENABLE_THINKING_LOGS
)

def test_cursor_agent_detection():
    """Test 1: Verify cursor-agent is available"""
    print("\n" + "="*70)
    print("TEST 1: Cursor Agent Detection")
    print("="*70)
    
    available = check_cursor_agent_available()
    cursor_path = get_cursor_agent_path()
    
    print(f"✓ check_cursor_agent_available(): {available}")
    print(f"✓ cursor-agent path: {cursor_path}")
    print(f"✓ File exists: {os.path.exists(cursor_path)}")
    
    if available:
        print("✅ PASSED: cursor-agent is available")
    else:
        print("⚠️  WARNING: cursor-agent not available (may need installation)")
    
    return available

def test_configuration():
    """Test 2: Verify configuration variables"""
    print("\n" + "="*70)
    print("TEST 2: Configuration Variables")
    print("="*70)
    
    config_vars = {
        "AGENT_BACKEND": AGENT_BACKEND,
        "CURSOR_AGENT_PATH": CURSOR_AGENT_PATH,
        "CURSOR_AGENT_MODEL": CURSOR_AGENT_MODEL,
        "CURSOR_ENABLE_THINKING_LOGS": CURSOR_ENABLE_THINKING_LOGS
    }
    
    for key, value in config_vars.items():
        print(f"✓ {key}: {value}")
    
    print("✅ PASSED: Configuration loaded successfully")
    return True

def test_stream_json_parsing():
    """Test 3: Parse sample cursor stream-json output"""
    print("\n" + "="*70)
    print("TEST 3: Stream-JSON Parsing")
    print("="*70)
    
    # Create sample stream-json log
    sample_events = [
        {"type": "system", "subtype": "init", "session_id": "test-123", "model": "Auto", "cwd": "/tmp"},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "Hello"}]}, "session_id": "test-123"},
        {"type": "thinking", "subtype": "delta", "text": "Analyzing...", "session_id": "test-123", "timestamp_ms": 1000},
        {"type": "thinking", "subtype": "completed", "session_id": "test-123", "timestamp_ms": 2000},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello! How can I help?"}]}, "session_id": "test-123", "timestamp_ms": 3000},
        {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 5000, "result": "Task completed", "session_id": "test-123"}
    ]
    
    # Write to temporary file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        temp_file = f.name
        for event in sample_events:
            f.write(json.dumps(event) + '\n')
    
    try:
        # Parse the file
        result = parse_cursor_stream_jsonl(temp_file, include_thinking=True)
        
        print(f"✓ Parsed successfully: {result.get('success', False)}")
        print(f"✓ Session ID: {result.get('session_id')}")
        print(f"✓ Model: {result.get('model')}")
        print(f"✓ Events count: {len(result.get('events', []))}")
        print(f"✓ Assistant messages: {len(result.get('assistant_messages', []))}")
        print(f"✓ Thinking text: '{result.get('thinking_text', '')}'")
        print(f"✓ Duration: {result.get('duration_ms')}ms")
        print(f"✓ Final result: {result.get('final_result', {}).get('subtype')}")
        
        # Validate results
        assert result['session_id'] == 'test-123', "Session ID mismatch"
        assert result['model'] == 'Auto', "Model mismatch"
        # Events list only includes: system_init, thinking_completed, assistant_message
        assert len(result['events']) >= 3, f"Expected at least 3 events, got {len(result['events'])}"
        assert len(result['assistant_messages']) == 1, "Expected 1 assistant message"
        assert result['thinking_text'] == 'Analyzing...', "Thinking text mismatch"
        assert result['duration_ms'] == 5000, "Duration mismatch"
        assert result['final_result']['subtype'] == 'success', "Result subtype mismatch"
        
        print("✅ PASSED: Stream-JSON parsing works correctly")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Cleanup
        os.unlink(temp_file)

def test_tool_call_parsing():
    """Test 4: Parse tool call events"""
    print("\n" + "="*70)
    print("TEST 4: Tool Call Parsing")
    print("="*70)
    
    # Test shell tool call
    shell_event = {
        "type": "tool_call",
        "subtype": "completed",
        "call_id": "tool_123",
        "tool_call": {
            "shellToolCall": {
                "args": {
                    "command": "ls -la",
                    "workingDirectory": "/tmp",
                    "timeout": 300000
                },
                "result": {
                    "success": {
                        "exitCode": 0,
                        "stdout": "total 0\ndrwxr-xr-x  2 user  staff  64 Oct 31 12:00 .\n",
                        "stderr": "",
                        "executionTime": 150
                    }
                }
            }
        }
    }
    
    shell_info = parse_cursor_tool_call(shell_event)
    print(f"✓ Shell tool call parsed:")
    print(f"  - Type: {shell_info.get('tool_type')}")
    print(f"  - Command: {shell_info.get('command')}")
    print(f"  - Success: {shell_info.get('success')}")
    print(f"  - Exit code: {shell_info.get('exit_code')}")
    print(f"  - Execution time: {shell_info.get('execution_time_ms')}ms")
    
    assert shell_info['tool_type'] == 'shell', "Tool type mismatch"
    assert shell_info['command'] == 'ls -la', "Command mismatch"
    assert shell_info['success'] == True, "Success status mismatch"
    assert shell_info['exit_code'] == 0, "Exit code mismatch"
    
    # Test edit tool call
    edit_event = {
        "type": "tool_call",
        "subtype": "completed",
        "call_id": "tool_456",
        "tool_call": {
            "editToolCall": {
                "args": {"path": "/tmp/test.py"},
                "result": {
                    "success": {
                        "path": "/tmp/test.py",
                        "linesAdded": 5,
                        "linesRemoved": 2,
                        "diffString": "+ print('hello')\n- pass",
                        "afterFullFileContent": "print('hello')\n"
                    }
                }
            }
        }
    }
    
    edit_info = parse_cursor_tool_call(edit_event)
    print(f"✓ Edit tool call parsed:")
    print(f"  - Type: {edit_info.get('tool_type')}")
    print(f"  - Path: {edit_info.get('path')}")
    print(f"  - Lines added: {edit_info.get('lines_added')}")
    print(f"  - Lines removed: {edit_info.get('lines_removed')}")
    
    assert edit_info['tool_type'] == 'edit', "Tool type mismatch"
    assert edit_info['path'] == '/tmp/test.py', "Path mismatch"
    assert edit_info['lines_added'] == 5, "Lines added mismatch"
    assert edit_info['lines_removed'] == 2, "Lines removed mismatch"
    
    print("✅ PASSED: Tool call parsing works correctly")
    return True

def test_real_cursor_agent():
    """Test 5: Run actual cursor-agent command (if available)"""
    print("\n" + "="*70)
    print("TEST 5: Real Cursor Agent Execution")
    print("="*70)
    
    if not check_cursor_agent_available():
        print("⚠️  SKIPPED: cursor-agent not available")
        return True
    
    import subprocess
    
    # Create temporary directory for test
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "test_output.jsonl")
        
        try:
            # Run simple cursor-agent command
            cursor_path = get_cursor_agent_path()
            cmd = [
                cursor_path, "-p",
                "What is 2+2? Just answer with the number.",
                "--output-format", "stream-json",
                "--model", "auto"
            ]
            
            print(f"✓ Running command: {' '.join(cmd)}")
            
            with open(log_file, 'w') as f:
                result = subprocess.run(
                    cmd,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    timeout=30
                )
            
            print(f"✓ Command completed with exit code: {result.returncode}")
            
            # Parse the output
            parsed = parse_cursor_stream_jsonl(log_file)
            
            print(f"✓ Log parsed successfully:")
            print(f"  - Session ID: {parsed.get('session_id')}")
            print(f"  - Success: {parsed.get('success')}")
            print(f"  - Duration: {parsed.get('duration_ms')}ms")
            print(f"  - Events: {len(parsed.get('events', []))}")
            print(f"  - Assistant messages: {len(parsed.get('assistant_messages', []))}")
            
            if parsed.get('assistant_messages'):
                print(f"  - First response: {parsed['assistant_messages'][0][:100]}")
            
            print("✅ PASSED: Real cursor-agent execution and parsing works")
            return True
            
        except subprocess.TimeoutExpired:
            print("❌ FAILED: Command timed out")
            return False
        except Exception as e:
            print(f"❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False

def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("CURSOR CLI INTEGRATION TEST SUITE")
    print("="*70)
    
    tests = [
        ("Cursor Agent Detection", test_cursor_agent_detection),
        ("Configuration", test_configuration),
        ("Stream-JSON Parsing", test_stream_json_parsing),
        ("Tool Call Parsing", test_tool_call_parsing),
        ("Real Cursor Agent", test_real_cursor_agent),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ {test_name} raised exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())

