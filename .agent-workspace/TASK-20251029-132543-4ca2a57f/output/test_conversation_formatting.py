#!/usr/bin/env python3
"""
Test conversation history formatting in format_task_enrichment_prompt()
This test verifies the formatting section added to real_mcp_server.py:806-855
"""

import sys
sys.path.insert(0, '/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP')

from real_mcp_server import format_task_enrichment_prompt

def test_conversation_history_formatting():
    """Test that conversation history is formatted correctly with emoji indicators"""

    # Mock task registry with conversation history
    task_registry = {
        'task_context': {
            'conversation_history': {
                'messages': [
                    {
                        'role': 'user',
                        'content': 'Can you help me fix the authentication bug?',
                        'timestamp': '2025-10-29T10:00:00',
                        'truncated': False,
                        'original_length': 44
                    },
                    {
                        'role': 'assistant',
                        'content': 'I will investigate the authentication system. Let me check the JWT validation logic and identify the issue.',
                        'timestamp': '2025-10-29T10:00:15',
                        'truncated': False,
                        'original_length': 111
                    },
                    {
                        'role': 'user',
                        'content': 'It\'s specifically in the token refresh endpoint. Users report 401 errors when trying to refresh their session tokens. This is a critical production issue... [truncated]',
                        'timestamp': '2025-10-29T10:01:30',
                        'truncated': True,
                        'original_length': 250
                    }
                ],
                'total_messages': 3,
                'truncated_count': 1,
                'metadata': {
                    'collection_time': '2025-10-29T10:02:00',
                    'oldest_message': '2025-10-29T10:00:00',
                    'newest_message': '2025-10-29T10:01:30'
                }
            }
        }
    }

    # Call the formatting function
    result = format_task_enrichment_prompt(task_registry)

    print("=" * 80)
    print("CONVERSATION HISTORY FORMATTING TEST")
    print("=" * 80)
    print("\nFormatted output:")
    print(result)
    print("\n" + "=" * 80)
    print("VALIDATION CHECKS")
    print("=" * 80)

    # Validate the output
    checks = {
        "Contains conversation history header": "💬 CONVERSATION HISTORY" in result,
        "Contains numbered message [1]": "[1]" in result,
        "Contains numbered message [2]": "[2]" in result,
        "Contains numbered message [3]": "[3]" in result,
        "Contains user emoji (👤)": "👤" in result,
        "Contains assistant emoji (🤖)": "🤖" in result,
        "Contains User role": "User" in result,
        "Contains Assistant role": "Assistant" in result,
        "Contains timestamp (10:00:00)": "10:00:00" in result,
        "Contains timestamp (10:00:15)": "10:00:15" in result,
        "Contains timestamp (10:01:30)": "10:01:30" in result,
        "Contains first message content": "Can you help me fix the authentication bug?" in result,
        "Contains second message content": "I will investigate the authentication system" in result,
        "Contains third message content (truncated)": "token refresh endpoint" in result,
        "Contains truncation indicator [TRUNCATED]": "[TRUNCATED]" in result,
        "Contains metadata footer": "📊 History metadata:" in result,
        "Contains message count": "3 messages" in result,
        "Contains truncation count": "1 truncated" in result,
        "Contains context explanation": "WHY this task exists" in result,
    }

    all_passed = True
    for check_name, passed in checks.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {check_name}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 80)
    if all_passed:
        print("✅ ALL CHECKS PASSED - Formatting implementation is correct!")
    else:
        print("❌ SOME CHECKS FAILED - Review implementation")
    print("=" * 80)

    return all_passed

def test_empty_conversation_history():
    """Test that empty conversation history doesn't produce output"""

    task_registry = {
        'task_context': {
            'conversation_history': {
                'messages': [],
                'total_messages': 0,
                'truncated_count': 0
            }
        }
    }

    result = format_task_enrichment_prompt(task_registry)

    print("\n" + "=" * 80)
    print("EMPTY CONVERSATION HISTORY TEST")
    print("=" * 80)

    # Should not contain conversation history section
    has_conv_section = "💬 CONVERSATION HISTORY" in result

    if not has_conv_section:
        print("✅ PASS: Empty conversation history correctly skipped")
        return True
    else:
        print("❌ FAIL: Empty conversation history should not produce output")
        print(f"Result: {result}")
        return False

def test_no_conversation_history():
    """Test that missing conversation history field doesn't break"""

    task_registry = {
        'task_context': {
            'background_context': 'Some background info'
        }
    }

    result = format_task_enrichment_prompt(task_registry)

    print("\n" + "=" * 80)
    print("NO CONVERSATION HISTORY FIELD TEST")
    print("=" * 80)

    # Should not contain conversation history section
    has_conv_section = "💬 CONVERSATION HISTORY" in result

    # But should still contain background context
    has_background = "📋 BACKGROUND CONTEXT" in result

    if not has_conv_section and has_background:
        print("✅ PASS: Missing conversation_history field handled gracefully")
        print("✅ PASS: Other sections still rendered")
        return True
    else:
        print(f"❌ FAIL: has_conv_section={has_conv_section}, has_background={has_background}")
        print(f"Result: {result}")
        return False

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("CONVERSATION HISTORY FORMATTING TEST SUITE")
    print("Testing: real_mcp_server.py:806-855 implementation")
    print("=" * 80 + "\n")

    test_results = []

    # Run tests
    test_results.append(("Full conversation history", test_conversation_history_formatting()))
    test_results.append(("Empty conversation history", test_empty_conversation_history()))
    test_results.append(("No conversation history field", test_no_conversation_history()))

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    for test_name, passed in test_results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")

    all_passed = all(result[1] for result in test_results)

    print("\n" + "=" * 80)
    if all_passed:
        print("🎉 ALL TESTS PASSED!")
        print("Conversation history formatting is working correctly.")
        sys.exit(0)
    else:
        print("⚠️  SOME TESTS FAILED")
        print("Review the implementation and fix issues.")
        sys.exit(1)
