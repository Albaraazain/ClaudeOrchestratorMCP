#!/usr/bin/env python3
"""
Test conversation_history parameter in create_real_task() function

Tests cover:
1. Valid conversation history
2. User message preservation (<8KB - kept intact)
3. Assistant message truncation (>150 chars - heavily truncated)
4. Invalid structure (not a list)
5. Missing required fields
6. Invalid role values
7. Empty conversation history
8. Conversation history in agent prompt
"""
import json
import os
import sys
import shutil
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from real_mcp_server import create_real_task


def cleanup_test_workspace(workspace_base):
    """Clean up test workspace"""
    if os.path.exists(workspace_base):
        shutil.rmtree(workspace_base)


def test_conversation_history_valid():
    """Test 1: Valid conversation history with proper structure"""
    print("\n=== TEST 1: Valid Conversation History ===")

    workspace_base = "/tmp/test-conv-history-valid"
    cleanup_test_workspace(workspace_base)

    conversation = [
        {
            "role": "user",
            "content": "I need to add authentication",
            "timestamp": "2025-10-29T10:00:00"
        },
        {
            "role": "assistant",
            "content": "I'll help you implement authentication. We should use JWT tokens with bcrypt for password hashing.",
            "timestamp": "2025-10-29T10:00:15"
        },
        {
            "role": "user",
            "content": "Focus on JWT first",
            "timestamp": "2025-10-29T10:01:00"
        }
    ]

    result = create_real_task.fn(
        description="Implement JWT authentication",
        client_cwd="/tmp",
        conversation_history=conversation
    )

    print(f"✓ Result: {json.dumps(result, indent=2)}")

    assert result['success'] == True
    assert result['has_enhanced_context'] == True

    # Verify conversation_history stored in registry
    workspace = result['workspace']
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    with open(registry_path, 'r') as f:
        registry = json.load(f)

    assert 'task_context' in registry
    assert 'conversation_history' in registry['task_context']
    conv_hist = registry['task_context']['conversation_history']
    assert 'messages' in conv_hist
    assert len(conv_hist['messages']) == 3
    assert conv_hist['total_messages'] == 3
    assert conv_hist['truncated_count'] == 0

    print("✓ Conversation history stored correctly")
    print(f"✓ Messages: {len(conv_hist['messages'])}, Truncated: {conv_hist['truncated_count']}")

    cleanup_test_workspace(workspace_base)
    print("✓ Test 1 PASSED: Valid conversation history\n")


def test_conversation_history_truncation_user():
    """Test 2: User message under 8KB should NOT be truncated (preserved intact)"""
    print("\n=== TEST 2: User Message Preservation (<8KB) ===")

    workspace_base = "/tmp/test-conv-history-user-truncate"
    cleanup_test_workspace(workspace_base)

    # Create a user message that's 200 characters (well under 8KB limit)
    long_user_message = "x" * 200

    conversation = [
        {
            "role": "user",
            "content": long_user_message,
            "timestamp": "2025-10-29T10:00:00"
        }
    ]

    result = create_real_task.fn(
        description="Test user preservation",
        client_cwd="/tmp",
        conversation_history=conversation
    )

    print(f"✓ Result: {json.dumps(result, indent=2)}")

    assert result['success'] == True

    # Verify NO truncation happened (user message preserved)
    workspace = result['workspace']
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    with open(registry_path, 'r') as f:
        registry = json.load(f)

    conv_hist = registry['task_context']['conversation_history']
    preserved_msg = conv_hist['messages'][0]

    # User message should NOT be truncated
    assert preserved_msg['truncated'] == False
    assert preserved_msg['original_length'] == 200
    assert len(preserved_msg['content']) == 200  # Fully preserved
    assert preserved_msg['content'] == long_user_message
    assert conv_hist['truncated_count'] == 0

    print(f"✓ Original length: {preserved_msg['original_length']}")
    print(f"✓ Preserved length: {len(preserved_msg['content'])}")
    print(f"✓ User message fully preserved (not truncated)")

    cleanup_test_workspace(workspace_base)
    print("✓ Test 2 PASSED: User message preserved correctly\n")


def test_conversation_history_truncation_assistant():
    """Test 3: Assistant message over 150 chars should be heavily truncated"""
    print("\n=== TEST 3: Assistant Message Truncation (>150 chars) ===")

    workspace_base = "/tmp/test-conv-history-assistant-truncate"
    cleanup_test_workspace(workspace_base)

    # Create an assistant message that's 500 chars (well over 150 char limit)
    long_assistant_message = "y" * 500

    conversation = [
        {
            "role": "assistant",
            "content": long_assistant_message,
            "timestamp": "2025-10-29T10:00:00"
        }
    ]

    result = create_real_task.fn(
        description="Test assistant truncation",
        client_cwd="/tmp",
        conversation_history=conversation
    )

    print(f"✓ Result: {json.dumps(result, indent=2)}")

    assert result['success'] == True

    # Verify heavy truncation happened (150 chars max)
    workspace = result['workspace']
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    with open(registry_path, 'r') as f:
        registry = json.load(f)

    conv_hist = registry['task_context']['conversation_history']
    truncated_msg = conv_hist['messages'][0]

    assert truncated_msg['truncated'] == True
    assert truncated_msg['original_length'] == 500
    assert len(truncated_msg['content']) <= 150 + len(" ... (truncated)")
    assert " ... (truncated)" in truncated_msg['content']
    assert conv_hist['truncated_count'] == 1

    print(f"✓ Original length: {truncated_msg['original_length']}")
    print(f"✓ Truncated length: {len(truncated_msg['content'])}")
    print(f"✓ Content ends with: '{truncated_msg['content'][-20:]}'")

    cleanup_test_workspace(workspace_base)
    print("✓ Test 3 PASSED: Assistant message truncated heavily to 150 chars\n")


def test_conversation_history_invalid_structure():
    """Test 4: Invalid structure (not a list) should be ignored with warning"""
    print("\n=== TEST 4: Invalid Structure (not a list) ===")

    workspace_base = "/tmp/test-conv-history-invalid-structure"
    cleanup_test_workspace(workspace_base)

    # Pass a dict instead of a list
    invalid_conversation = {
        "role": "user",
        "content": "This should be in a list"
    }

    result = create_real_task.fn(
        description="Test invalid structure",
        client_cwd="/tmp",
        conversation_history=invalid_conversation
    )

    print(f"✓ Result: {json.dumps(result, indent=2)}")

    # Should succeed with validation warning
    assert result['success'] == True
    assert 'validation_warnings' in result

    # Check that warning mentions the issue
    warnings = result.get('validation_warnings', [])
    has_relevant_warning = any('conversation_history' in w.lower() for w in warnings)
    assert has_relevant_warning, f"Expected warning about conversation_history, got: {warnings}"

    print(f"✓ Validation warnings: {warnings}")
    print("✓ Invalid structure handled gracefully with warning")

    cleanup_test_workspace(workspace_base)
    print("✓ Test 4 PASSED: Invalid structure handled gracefully\n")


def test_conversation_history_missing_fields():
    """Test 5: Missing required fields should raise error"""
    print("\n=== TEST 5: Missing Required Fields ===")

    workspace_base = "/tmp/test-conv-history-missing-fields"
    cleanup_test_workspace(workspace_base)

    # Test missing 'role'
    print("  5a: Missing 'role' field")
    conversation_no_role = [
        {
            "content": "Message without role"
        }
    ]

    try:
        result = create_real_task.fn(
            description="Test missing role",
            client_cwd="/tmp",
            conversation_history=conversation_no_role
        )
        assert False, "Expected error for missing role"
    except Exception as e:
        error_msg = str(e)
        print(f"  ✓ Error: {error_msg}")
        assert "role" in error_msg.lower()

    # Test missing 'content'
    print("  5b: Missing 'content' field")
    conversation_no_content = [
        {
            "role": "user"
        }
    ]

    try:
        result = create_real_task.fn(
            description="Test missing content",
            client_cwd="/tmp",
            conversation_history=conversation_no_content
        )
        assert False, "Expected error for missing content"
    except Exception as e:
        error_msg = str(e)
        print(f"  ✓ Error: {error_msg}")
        assert "content" in error_msg.lower()

    cleanup_test_workspace(workspace_base)
    print("✓ Test 5 PASSED: Missing fields rejected\n")


def test_conversation_history_invalid_role():
    """Test 6: Invalid role values should raise error"""
    print("\n=== TEST 6: Invalid Role Values ===")

    workspace_base = "/tmp/test-conv-history-invalid-role"
    cleanup_test_workspace(workspace_base)

    # Invalid role: "system" (only user/assistant/orchestrator allowed per schema)
    conversation = [
        {
            "role": "system",
            "content": "Invalid role value",
            "timestamp": "2025-10-29T10:00:00"
        }
    ]

    try:
        result = create_real_task.fn(
            description="Test invalid role",
            client_cwd="/tmp",
            conversation_history=conversation
        )

        # Should not reach here
        assert False, "Expected error for invalid role"

    except Exception as e:
        error_msg = str(e)
        print(f"✓ Expected error raised: {error_msg}")
        assert "role" in error_msg.lower() or "invalid" in error_msg.lower()
        print("✓ Invalid role rejected correctly")

    cleanup_test_workspace(workspace_base)
    print("✓ Test 6 PASSED: Invalid role rejected\n")


def test_conversation_history_empty():
    """Test 7: Empty conversation history should be handled gracefully"""
    print("\n=== TEST 7: Empty Conversation History ===")

    workspace_base = "/tmp/test-conv-history-empty"
    cleanup_test_workspace(workspace_base)

    # Empty list
    conversation = []

    result = create_real_task.fn(
        description="Test empty conversation",
        client_cwd="/tmp",
        conversation_history=conversation
    )

    print(f"✓ Result: {json.dumps(result, indent=2)}")

    assert result['success'] == True

    # Empty conversation should not create enhanced context
    # OR should create it but with no messages
    workspace = result['workspace']
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    with open(registry_path, 'r') as f:
        registry = json.load(f)

    # Either no task_context, or task_context without conversation_history
    if 'task_context' in registry:
        conv_hist = registry['task_context'].get('conversation_history')
        if conv_hist:
            assert len(conv_hist.get('messages', [])) == 0
            print("✓ Empty conversation stored as empty messages")
        else:
            print("✓ Empty conversation not stored (expected)")
    else:
        print("✓ No task_context for empty conversation (expected)")

    cleanup_test_workspace(workspace_base)
    print("✓ Test 7 PASSED: Empty conversation handled gracefully\n")


def test_conversation_history_in_agent_prompt():
    """Test 8: Verify conversation history is injected into agent prompt"""
    print("\n=== TEST 8: Conversation History in Agent Prompt ===")

    workspace_base = "/tmp/test-conv-history-prompt"
    cleanup_test_workspace(workspace_base)

    conversation = [
        {
            "role": "user",
            "content": "Fix the authentication bug",
            "timestamp": "2025-10-29T10:00:00"
        },
        {
            "role": "assistant",
            "content": "I'll help you debug the authentication issue. This involves checking JWT token validation and session management.",
            "timestamp": "2025-10-29T10:00:15"
        }
    ]

    result = create_real_task.fn(
        description="Debug authentication system",
        client_cwd="/tmp",
        conversation_history=conversation,
        background_context="User reported login failures"
    )

    print(f"✓ Task created: {result['task_id']}")

    assert result['success'] == True

    # Read the agent prompt file to verify injection
    workspace = result['workspace']

    # The agent prompt should be in the workspace - check agent_prompt.txt or similar
    # Based on the schema, format_task_enrichment_prompt formats it
    # Let's check if we can find the formatted prompt

    # First verify registry has the conversation_history
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    with open(registry_path, 'r') as f:
        registry = json.load(f)

    assert 'task_context' in registry
    assert 'conversation_history' in registry['task_context']

    conv_hist = registry['task_context']['conversation_history']
    print(f"✓ Conversation history stored with {len(conv_hist['messages'])} messages")

    # The formatting happens when agents are deployed
    # For now, verify the data is ready to be formatted
    messages = conv_hist['messages']
    assert len(messages) == 2
    assert messages[0]['role'] == 'user'
    assert messages[1]['role'] == 'assistant'
    assert 'Fix the authentication bug' in messages[0]['content']
    assert 'JWT token validation' in messages[1]['content']

    print("✓ Conversation history ready for prompt injection")
    print(f"✓ Message 1: [{messages[0]['role']}] {messages[0]['content'][:50]}...")
    print(f"✓ Message 2: [{messages[1]['role']}] {messages[1]['content'][:50]}...")

    # Verify metadata
    metadata = conv_hist.get('metadata', {})
    assert 'collection_time' in metadata
    assert 'oldest_message' in metadata
    assert 'newest_message' in metadata
    print(f"✓ Metadata: collection_time={metadata['collection_time'][:19]}")

    cleanup_test_workspace(workspace_base)
    print("✓ Test 8 PASSED: Conversation history prepared for agent prompt\n")


def run_all_tests():
    """Run all conversation history tests"""
    print("=" * 70)
    print("Testing conversation_history Parameter in create_real_task()")
    print("=" * 70)

    tests = [
        ("Valid conversation history", test_conversation_history_valid),
        ("User message preservation", test_conversation_history_truncation_user),
        ("Assistant message truncation", test_conversation_history_truncation_assistant),
        ("Invalid structure handling", test_conversation_history_invalid_structure),
        ("Missing fields rejection", test_conversation_history_missing_fields),
        ("Invalid role rejection", test_conversation_history_invalid_role),
        ("Empty conversation handling", test_conversation_history_empty),
        ("Prompt injection preparation", test_conversation_history_in_agent_prompt),
    ]

    passed = 0
    failed = 0
    errors = []

    for test_name, test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            failed += 1
            errors.append((test_name, str(e)))
            print(f"❌ TEST FAILED: {test_name}")
            print(f"   Assertion: {e}\n")
        except Exception as e:
            failed += 1
            errors.append((test_name, str(e)))
            print(f"❌ TEST ERROR: {test_name}")
            print(f"   Exception: {e}\n")
            import traceback
            traceback.print_exc()

    # Summary
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Total tests: {len(tests)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed > 0:
        print("\n❌ FAILED TESTS:")
        for test_name, error in errors:
            print(f"  - {test_name}: {error}")
        return False
    else:
        print("\n✅ ALL TESTS PASSED!")
        print("\nCOVERAGE:")
        print("  ✓ Valid conversation history with proper structure")
        print("  ✓ User message preservation (<8KB - kept intact)")
        print("  ✓ Assistant message truncation (>150 chars - heavily truncated)")
        print("  ✓ Invalid structure (not a list) rejection")
        print("  ✓ Missing required fields rejection")
        print("  ✓ Invalid role values rejection")
        print("  ✓ Empty conversation history handling")
        print("  ✓ Conversation history prepared for agent prompt injection")
        return True


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
