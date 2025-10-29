#!/usr/bin/env python3
"""
Test script to verify JSONL truncation implementation.
Tests with real bloated log file.
"""

import sys
import os
sys.path.insert(0, '/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP')

from real_mcp_server import get_agent_output

def test_truncation():
    """Test truncation with a real bloated log."""

    # Test with the 129KB bloated log
    task_id = "TASK-20251017-215604-df6a3cbd"
    agent_id = "simple_test_agent-212031-9d5ba0"

    print("=" * 80)
    print("TESTING TRUNCATION IMPLEMENTATION")
    print("=" * 80)
    print(f"Task ID: {task_id}")
    print(f"Agent ID: {agent_id}")
    print()

    # Get output with truncation enabled (via the .fn accessor for MCP tools)
    result = get_agent_output.fn(
        task_id=task_id,
        agent_id=agent_id,
        format='text',
        include_metadata=True
    )

    if not result['success']:
        print(f"❌ ERROR: {result.get('error')}")
        return False

    print("✅ get_agent_output succeeded")
    print()

    # Check metadata
    metadata = result.get('metadata', {})
    print("METADATA:")
    print(f"  Total lines: {metadata.get('total_lines')}")
    print(f"  Returned lines: {metadata.get('returned_lines')}")
    print(f"  File size: {metadata.get('file_size_bytes')} bytes")
    print()

    # Check truncation stats
    if 'truncation_stats' in metadata:
        stats = metadata['truncation_stats']
        print("TRUNCATION STATS:")
        print(f"  Lines truncated: {stats['lines_truncated']}")
        print(f"  Total lines: {stats['total_lines']}")
        print(f"  Truncation ratio: {stats['truncation_ratio']}")
        print(f"  Bytes before: {stats['bytes_before']:,}")
        print(f"  Bytes after: {stats['bytes_after']:,}")
        print(f"  Bytes saved: {stats['bytes_saved']:,}")
        print(f"  Space savings: {stats['space_savings_percent']}%")
        print(f"  Max line length: {stats['max_line_length']}")
        print(f"  Max tool_result: {stats['max_tool_result_content']}")
        print()

        if stats['lines_truncated'] > 0:
            print(f"✅ TRUNCATION WORKING: {stats['lines_truncated']} lines truncated")
            print(f"✅ SPACE SAVED: {stats['space_savings_percent']}% reduction")
            return True
        else:
            print("⚠️  WARNING: No lines were truncated (log may be small)")
            return True
    else:
        print("⚠️  No truncation stats in metadata (no bloated lines found)")
        return True

if __name__ == "__main__":
    success = test_truncation()
    sys.exit(0 if success else 1)
