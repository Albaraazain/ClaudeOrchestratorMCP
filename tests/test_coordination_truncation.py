#!/usr/bin/env python3
"""
End-to-end integration tests for coordination_info truncation fixes.
Tests the complete flow: MCP tool calls → JSONL logs → truncation → verification.
"""

import json
import sys
import os
import tempfile
import shutil
from pathlib import Path

# Import from real_mcp_server
sys.path.insert(0, str(Path(__file__).parent.parent))
import real_mcp_server


def test_mcp_tool_returns_minimal_coordination_info():
    """
    Test that get_minimal_coordination_info returns minimal data.
    """
    print("=" * 80)
    print("TEST 1: get_minimal_coordination_info() Returns Minimal Data")
    print("=" * 80)

    # Create a temporary workspace with task registry
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir) / ".agent-workspace" / "TASK-TEST"
        workspace.mkdir(parents=True)

        task_id = "TASK-TEST-MINIMAL"

        # Create minimal AGENT_REGISTRY.json
        registry = {
            "task_id": task_id,
            "task_description": "Test task",
            "agents": {
                "test-agent-1": {
                    "id": "test-agent-1",
                    "type": "tester",
                    "status": "working",
                    "progress": 50
                }
            },
            "progress_log": [
                {"timestamp": "2025-01-01T00:00:00", "agent_id": "test-agent-1", "message": "Test"}
            ],
            "findings_log": [
                {"timestamp": "2025-01-01T00:00:00", "agent_id": "test-agent-1", "message": "Found"}
            ]
        }

        with open(workspace / "AGENT_REGISTRY.json", 'w') as f:
            json.dump(registry, f)

        # Call get_minimal_coordination_info
        result = real_mcp_server.get_minimal_coordination_info(str(workspace))

        serialized = json.dumps(result)
        size = len(serialized)

        print(f"Coordination info size: {size} bytes")
        print(f"Keys: {list(result.keys())}")

        # Should be minimal (< 5KB)
        assert size < 5000, f"Coordination info should be < 5KB, got {size} bytes"
        assert 'agent_counts' in result, "Should have agent_counts"

        print("✓ get_minimal_coordination_info returns minimal data")
        print()
        return True


def test_truncate_coordination_info_helper():
    """
    Test the truncate_coordination_info helper function directly.
    """
    print("=" * 80)
    print("TEST 2: truncate_coordination_info() Helper Function")
    print("=" * 80)

    # Create bloated coordination_info
    bloated = {
        "success": True,
        "task_id": "TASK-TEST",
        "agent_counts": {"total": 10, "active": 5},
        "coordination_data": {
            "recent_findings": [{"id": i, "msg": f"Finding {i}" * 100} for i in range(10)],
            "recent_progress": [{"id": i, "msg": f"Progress {i}" * 100} for i in range(20)]
        },
        "agents": [
            {"id": f"agent-{i}", "status": "running", "prompt": "x" * 1000}
            for i in range(15)
        ]
    }

    original_size = len(json.dumps(bloated))
    print(f"Original size: {original_size} bytes")

    # Truncate
    truncated = real_mcp_server.truncate_coordination_info(bloated)
    truncated_size = len(json.dumps(truncated))

    print(f"Truncated size: {truncated_size} bytes")
    print(f"Reduction: {100 - (truncated_size/original_size*100):.1f}%")

    # Verify structure preserved
    assert truncated['_truncated'] is True
    assert len(truncated['coordination_data']['recent_findings']) <= 3
    assert len(truncated['coordination_data']['recent_progress']) <= 5
    assert 'agents_summary' in truncated

    # Should achieve 60-80% reduction
    reduction_pct = 100 - (truncated_size/original_size*100)
    assert reduction_pct > 60, f"Should achieve >60% reduction, got {reduction_pct:.1f}%"

    print("✓ Helper function achieves target reduction")
    print()
    return True


def test_truncate_json_structure_with_coordination():
    """
    Test that truncate_json_structure intelligently handles coordination_info.
    """
    print("=" * 80)
    print("TEST 3: truncate_json_structure() with Coordination Info")
    print("=" * 80)

    # Create tool_result with large coordination_info
    tool_result = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "test-123",
                    "content": json.dumps({
                        "success": True,
                        "own_update": {"agent_id": "test", "status": "working"},
                        "coordination_info": {
                            "success": True,
                            "task_id": "TASK-TEST",
                            "agent_counts": {"total": 20},
                            "coordination_data": {
                                "recent_findings": [
                                    {"id": i, "message": f"Finding {i}" * 200}
                                    for i in range(10)
                                ],
                                "recent_progress": [
                                    {"id": i, "message": f"Progress {i}" * 200}
                                    for i in range(20)
                                ]
                            },
                            "agents": [
                                {"id": f"agent-{i}", "status": "running", "prompt": "x" * 2000}
                                for i in range(20)
                            ]
                        }
                    })
                }
            ]
        }
    }

    original_content_size = len(tool_result['message']['content'][0]['content'])
    print(f"Original tool_result.content size: {original_content_size} bytes")

    # Apply truncation
    truncated = real_mcp_server.truncate_json_structure(tool_result, max_length=100000)

    truncated_content = truncated['message']['content'][0]['content']
    truncated_size = len(truncated_content)

    print(f"Truncated size: {truncated_size} bytes")
    print(f"Reduction: {100 - (truncated_size/original_content_size*100):.1f}%")
    print(f"Truncation type: {truncated['message']['content'][0].get('truncation_type')}")

    # Verify intelligent truncation was used
    assert truncated['message']['content'][0]['truncated'] is True
    assert truncated['message']['content'][0]['truncation_type'] == 'intelligent_coordination_info'

    # Verify content is still valid JSON
    parsed = json.loads(truncated_content)
    assert 'coordination_info' in parsed
    assert parsed['coordination_info'].get('_truncated') is True

    # Should achieve significant reduction (>60%)
    reduction_pct = 100 - (truncated_size/original_content_size*100)
    assert reduction_pct > 60, f"Should achieve >60% reduction, got {reduction_pct:.1f}%"

    print("✓ Intelligent truncation works correctly")
    print()
    return True


def test_end_to_end_real_world_scenario():
    """
    Test the complete flow: Simulate coordination_info → truncation → size reduction.
    """
    print("=" * 80)
    print("TEST 4: End-to-End Real-World Scenario")
    print("=" * 80)

    # Simulate multiple coordination_info responses (what MCP tools return)
    total_size_before = 0
    total_size_after = 0

    for i in range(5):
        # Simulate a large coordination_info response
        mcp_response = {
            "success": True,
            "own_update": {
                "agent_id": f"agent-{i}",
                "status": "working",
                "message": f"Progress update {i}" * 50,  # Bloated message
                "progress": i * 20
            },
            "coordination_info": {
                "success": True,
                "task_id": "TASK-E2E-TEST",
                "agent_counts": {"total": 10, "active": 8},
                "coordination_data": {
                    "recent_findings": [
                        {"id": j, "message": f"Finding {j}" * 100}
                        for j in range(10)
                    ],
                    "recent_progress": [
                        {"id": j, "message": f"Progress {j}" * 100}
                        for j in range(20)
                    ]
                },
                "agents": [
                    {"id": f"agent-{j}", "status": "running", "prompt": "x" * 500}
                    for j in range(15)
                ]
            }
        }

        # Simulate what would be in JSONL
        jsonl_line = json.dumps(mcp_response)
        total_size_before += len(jsonl_line)

        # Apply truncation (what get_agent_output does)
        tool_result_msg = {
            "type": "user",
            "message": {
                "content": [{
                    "type": "tool_result",
                    "content": jsonl_line
                }]
            }
        }

        truncated = real_mcp_server.truncate_json_structure(tool_result_msg, max_length=50000)
        truncated_content = truncated['message']['content'][0]['content']
        total_size_after += len(truncated_content)

    print(f"Total size before truncation: {total_size_before} bytes ({total_size_before/1024:.1f} KB)")
    print(f"Total size after truncation: {total_size_after} bytes ({total_size_after/1024:.1f} KB)")

    reduction_pct = 100 - (total_size_after/total_size_before*100)
    print(f"Overall reduction: {reduction_pct:.1f}%")

    # Should achieve significant reduction
    assert total_size_after < total_size_before, "Truncation should reduce size"
    assert reduction_pct > 50, f"Should achieve >50% reduction in real scenario, got {reduction_pct:.1f}%"

    print("✓ End-to-end scenario shows significant size reduction")
    print()
    return True


def test_backward_compatibility_non_coordination():
    """
    Test that non-coordination_info content still works (backward compatibility).
    """
    print("=" * 80)
    print("TEST 5: Backward Compatibility - Non-Coordination Content")
    print("=" * 80)

    # Create tool_result with regular content (not coordination_info)
    regular_result = {
        "type": "user",
        "message": {
            "content": [{
                "type": "tool_result",
                "tool_use_id": "test-456",
                "content": "Regular output " * 500  # Just a long string
            }]
        }
    }

    original_size = len(regular_result['message']['content'][0]['content'])
    print(f"Original size: {original_size} bytes")

    # Apply truncation
    truncated = real_mcp_server.truncate_json_structure(regular_result, max_length=50000)

    # Should use fallback truncation for non-JSON
    assert truncated['message']['content'][0]['truncated'] is True
    truncation_type = truncated['message']['content'][0]['truncation_type']

    print(f"Truncation type: {truncation_type}")
    assert truncation_type in ['blind_string', 'blind_string_fallback'], \
        f"Should use blind truncation for non-coordination content"

    print("✓ Backward compatibility maintained")
    print()
    return True


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("COORDINATION_INFO TRUNCATION - END-TO-END INTEGRATION TESTS")
    print("=" * 80 + "\n")

    try:
        test1 = test_mcp_tool_returns_minimal_coordination_info()
        test2 = test_truncate_coordination_info_helper()
        test3 = test_truncate_json_structure_with_coordination()
        test4 = test_end_to_end_real_world_scenario()
        test5 = test_backward_compatibility_non_coordination()

        print("=" * 80)
        print("ALL INTEGRATION TESTS PASSED ✓")
        print("=" * 80)
        print("\nVerified:")
        print("  ✓ MCP tools return minimal coordination_info")
        print("  ✓ truncate_coordination_info() achieves 60-80% reduction")
        print("  ✓ truncate_json_structure() intelligently handles coordination_info")
        print("  ✓ End-to-end scenario shows significant size reduction")
        print("  ✓ Backward compatibility maintained for non-coordination content")

    except Exception as e:
        print("\n" + "=" * 80)
        print("INTEGRATION TEST FAILED ✗")
        print("=" * 80)
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
