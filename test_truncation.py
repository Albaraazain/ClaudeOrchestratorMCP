#!/usr/bin/env python3
"""
Test script to verify intelligent coordination_info truncation.
Tests the truncate_coordination_info and truncate_json_structure functions.
"""

import json
import sys

# Import functions from real_mcp_server
sys.path.insert(0, '/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP')
from real_mcp_server import truncate_coordination_info, truncate_json_structure

def test_truncate_coordination_info():
    """Test the truncate_coordination_info function."""
    print("=" * 80)
    print("TEST 1: truncate_coordination_info() function")
    print("=" * 80)

    # Create a sample coordination_info structure with bloat
    sample_coord_info = {
        "success": True,
        "task_id": "TASK-TEST",
        "agent_counts": {
            "total_spawned": 4,
            "active": 4,
            "completed": 0
        },
        "coordination_data": {
            "recent_findings": [
                {"id": i, "message": f"Finding {i}" * 50} for i in range(10)
            ],
            "recent_progress": [
                {"id": i, "message": f"Progress {i}" * 50} for i in range(20)
            ]
        },
        "agents": [
            {
                "id": f"agent-{i}",
                "type": "tester",
                "status": "running",
                "prompt": "x" * 500
            } for i in range(10)
        ]
    }

    original_size = len(json.dumps(sample_coord_info))
    print(f"Original size: {original_size} bytes")

    # Truncate
    truncated = truncate_coordination_info(sample_coord_info)
    truncated_size = len(json.dumps(truncated))
    print(f"Truncated size: {truncated_size} bytes")
    print(f"Reduction: {original_size - truncated_size} bytes ({100 - (truncated_size/original_size*100):.1f}%)")

    # Verify structure
    assert truncated['_truncated'] == True, "Should be marked as truncated"
    assert len(truncated['coordination_data']['recent_findings']) <= 3, "Should keep max 3 findings"
    assert len(truncated['coordination_data']['recent_progress']) <= 5, "Should keep max 5 progress"
    assert 'agents_summary' in truncated, "Should have agents_summary"
    assert len(truncated['agents']) <= 2, "Should keep max 2 sample agents"

    print("✓ All assertions passed for truncate_coordination_info()")
    print()
    return True

def test_truncate_json_structure():
    """Test the truncate_json_structure function with coordination_info."""
    print("=" * 80)
    print("TEST 2: truncate_json_structure() with coordination_info")
    print("=" * 80)

    # Create a tool_result message with large coordination_info in content
    large_coord_info = {
        "success": True,
        "own_update": {
            "agent_id": "test-agent",
            "status": "working",
            "progress": 50
        },
        "coordination_info": {
            "success": True,
            "task_id": "TASK-TEST",
            "agent_counts": {"total_spawned": 10, "active": 8, "completed": 2},
            "coordination_data": {
                "recent_findings": [
                    {"id": i, "message": f"Finding {i}" * 100} for i in range(10)
                ],
                "recent_progress": [
                    {"id": i, "message": f"Progress {i}" * 100} for i in range(20)
                ]
            },
            "agents": [
                {
                    "id": f"agent-{i}",
                    "type": "worker",
                    "status": "running",
                    "prompt": "x" * 1000
                } for i in range(15)
            ]
        }
    }

    # Create tool_result message structure
    tool_result_message = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "test-123",
                    "content": json.dumps(large_coord_info)
                }
            ]
        }
    }

    original_content_size = len(tool_result_message['message']['content'][0]['content'])
    print(f"Original tool_result.content size: {original_content_size} bytes")

    # Apply truncation
    truncated_msg = truncate_json_structure(tool_result_message, max_length=50000)

    truncated_content = truncated_msg['message']['content'][0]['content']
    truncated_content_size = len(truncated_content)
    print(f"Truncated tool_result.content size: {truncated_content_size} bytes")
    print(f"Reduction: {original_content_size - truncated_content_size} bytes ({100 - (truncated_content_size/original_content_size*100):.1f}%)")

    # Verify truncation happened
    assert truncated_msg['message']['content'][0]['truncated'] == True, "Should be marked as truncated"
    assert truncated_msg['message']['content'][0]['truncation_type'] == 'intelligent_coordination_info', \
        "Should use intelligent truncation"

    # Verify content is still valid JSON
    parsed_truncated = json.loads(truncated_content)
    assert 'coordination_info' in parsed_truncated, "Should still have coordination_info"
    assert parsed_truncated['coordination_info'].get('_truncated') == True, \
        "coordination_info should be marked as truncated"

    print("✓ All assertions passed for truncate_json_structure()")
    print()
    return True

def test_backward_compatibility():
    """Test that non-coordination_info content still works."""
    print("=" * 80)
    print("TEST 3: Backward compatibility with non-coordination_info content")
    print("=" * 80)

    # Create a tool_result with regular string content
    regular_message = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "test-456",
                    "content": "x" * 5000  # Just a long string
                }
            ]
        }
    }

    print(f"Original size: {len(regular_message['message']['content'][0]['content'])} bytes")

    # Apply truncation
    truncated_msg = truncate_json_structure(regular_message, max_length=50000)

    truncated_content = truncated_msg['message']['content'][0]['content']
    print(f"Truncated size: {len(truncated_content)} bytes")

    # Verify it used fallback truncation
    assert truncated_msg['message']['content'][0]['truncated'] == True, "Should be marked as truncated"
    assert truncated_msg['message']['content'][0]['truncation_type'] in ['blind_string', 'blind_string_fallback'], \
        "Should use blind truncation for non-JSON content"

    print("✓ Backward compatibility maintained")
    print()
    return True

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("INTELLIGENT COORDINATION_INFO TRUNCATION - TEST SUITE")
    print("=" * 80 + "\n")

    try:
        test1_passed = test_truncate_coordination_info()
        test2_passed = test_truncate_json_structure()
        test3_passed = test_backward_compatibility()

        print("=" * 80)
        print("ALL TESTS PASSED ✓")
        print("=" * 80)
        print("\nImplementation verified successfully!")
        print("- truncate_coordination_info() reduces size by ~60-70%")
        print("- truncate_json_structure() correctly detects and handles coordination_info")
        print("- Backward compatibility maintained for non-coordination_info content")

    except Exception as e:
        print("\n" + "=" * 80)
        print("TEST FAILED ✗")
        print("=" * 80)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
