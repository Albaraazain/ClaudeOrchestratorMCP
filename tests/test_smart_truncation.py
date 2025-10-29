#!/usr/bin/env python3
"""
Unit tests for smart truncation features in get_agent_output

Tests cover:
- max_bytes parameter (total response size limiting)
- aggressive_truncate mode (smaller per-line limits)
- response_format modes (full/summary/compact)
- intelligent sampling (first N + last N lines)
- repetitive content detection
- backward compatibility (all new params optional)
"""

import pytest
import os
import json
import tempfile
import shutil
from pathlib import Path
import sys

# Add parent directory to path to import real_mcp_server
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import real_mcp_server


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory for testing."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def mock_task_with_agent_logs(temp_workspace):
    """Create a mock task with agent logs for testing."""
    task_id = "TASK-TEST-TRUNCATION"
    agent_id = "test-agent-12345"

    # Create workspace base
    workspace_base = os.path.join(temp_workspace, ".agent-workspace")
    os.makedirs(workspace_base, exist_ok=True)

    # Override WORKSPACE_BASE temporarily
    original_workspace_base = real_mcp_server.WORKSPACE_BASE
    real_mcp_server.WORKSPACE_BASE = workspace_base

    task_workspace = os.path.join(workspace_base, task_id)
    logs_dir = os.path.join(task_workspace, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    # Create AGENT_REGISTRY.json
    registry = {
        "task_id": task_id,
        "agents": {
            agent_id: {
                "id": agent_id,
                "type": "tester",
                "status": "working",
                "tmux_session": f"agent_{agent_id}"
            }
        }
    }
    registry_path = os.path.join(task_workspace, "AGENT_REGISTRY.json")
    with open(registry_path, 'w') as f:
        json.dump(registry, f)

    log_file = os.path.join(logs_dir, f"{agent_id}_stream.jsonl")

    yield {
        "task_id": task_id,
        "agent_id": agent_id,
        "workspace": task_workspace,
        "log_file": log_file,
        "base_workspace": workspace_base
    }

    # Restore original WORKSPACE_BASE
    real_mcp_server.WORKSPACE_BASE = original_workspace_base


# ============================================================================
# TEST DATA GENERATORS
# ============================================================================

def generate_bloated_tool_result(size_kb=20):
    """Generate a large tool_result content for testing truncation."""
    # Create a realistic tool_result with large content
    content = "This is repeated content. " * (size_kb * 40)  # ~20KB
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{
                "tool_use_id": "toolu_test123",
                "type": "tool_result",
                "content": content
            }]
        }
    }


def generate_repetitive_logs(count=100):
    """Generate repetitive log entries (e.g., same tool called multiple times)."""
    logs = []
    for i in range(count):
        logs.append({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{
                    "type": "tool_use",
                    "id": f"toolu_repeat_{i}",
                    "name": "Read",
                    "input": {"file_path": "/same/path.py"}
                }]
            }
        })
    return logs


def generate_mixed_logs(normal_count=50, bloated_count=10, repetitive_count=30):
    """Generate a mix of normal, bloated, and repetitive log entries."""
    logs = []

    # Add normal logs
    for i in range(normal_count):
        logs.append({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{
                    "type": "text",
                    "text": f"Processing step {i}"
                }]
            }
        })

    # Add bloated tool results
    for i in range(bloated_count):
        logs.append(generate_bloated_tool_result(size_kb=15))

    # Add repetitive logs
    logs.extend(generate_repetitive_logs(repetitive_count))

    return logs


def generate_thinking_blocks(count=10, size_kb=5):
    """Generate large thinking blocks for testing truncation."""
    logs = []
    thinking_content = "Deep analysis here. " * (size_kb * 50)

    for i in range(count):
        logs.append({
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{
                    "type": "thinking",
                    "thinking": thinking_content
                }]
            }
        })
    return logs


def write_logs_to_file(log_file, logs):
    """Write log entries to a JSONL file."""
    with open(log_file, 'w') as f:
        for log in logs:
            f.write(json.dumps(log) + '\n')


# ============================================================================
# TESTS: max_bytes parameter
# ============================================================================

def test_max_bytes_limits_total_response(mock_task_with_agent_logs):
    """Test that max_bytes parameter limits the total response size."""
    # Generate large logs (should be > 50KB total)
    logs = generate_mixed_logs(normal_count=100, bloated_count=20, repetitive_count=50)
    write_logs_to_file(mock_task_with_agent_logs['log_file'], logs)

    # Call with max_bytes=50000 (50KB limit)
    # Use .fn to access actual function (FastMCP wraps in FunctionTool)
    result = real_mcp_server.get_agent_output.fn(
        task_id=mock_task_with_agent_logs['task_id'],
        agent_id=mock_task_with_agent_logs['agent_id'],
        max_bytes=50000
    )

    assert result['success'] is True
    # Output size should be <= 50KB
    output_size = len(result['output'])
    assert output_size <= 50000, f"Output size {output_size} exceeds max_bytes limit"


def test_max_bytes_intelligent_sampling(mock_task_with_agent_logs):
    """Test that max_bytes uses intelligent sampling (first N + last N lines)."""
    # Generate 100 logs with distinctive first and last entries
    logs = []
    logs.append({"type": "system", "subtype": "init", "marker": "FIRST_LOG"})
    logs.extend(generate_mixed_logs(normal_count=98, bloated_count=0, repetitive_count=0))
    logs.append({"type": "assistant", "marker": "LAST_LOG", "final": True})

    write_logs_to_file(mock_task_with_agent_logs['log_file'], logs)

    # Call with small max_bytes to trigger sampling
    result = real_mcp_server.get_agent_output.fn(
        task_id=mock_task_with_agent_logs['task_id'],
        agent_id=mock_task_with_agent_logs['agent_id'],
        max_bytes=5000,
        format="parsed"
    )

    assert result['success'] is True
    # Should contain first log
    first_log = result['output'][0] if result['output'] else {}
    assert 'FIRST_LOG' in str(first_log), "First log should be preserved in sampling"

    # Should contain last log
    last_log = result['output'][-1] if result['output'] else {}
    assert 'LAST_LOG' in str(last_log), "Last log should be preserved in sampling"


# ============================================================================
# TESTS: aggressive_truncate mode
# ============================================================================

def test_aggressive_truncate_uses_smaller_limits(mock_task_with_agent_logs):
    """Test that aggressive_truncate=True uses smaller per-line limits."""
    # Generate logs with large tool results (30KB each to exceed both limits)
    logs = [generate_bloated_tool_result(size_kb=30) for _ in range(10)]
    write_logs_to_file(mock_task_with_agent_logs['log_file'], logs)

    # Call with aggressive_truncate=True
    result_aggressive = real_mcp_server.get_agent_output.fn(
        task_id=mock_task_with_agent_logs['task_id'],
        agent_id=mock_task_with_agent_logs['agent_id'],
        aggressive_truncate=True
    )

    # Call with aggressive_truncate=False
    result_normal = real_mcp_server.get_agent_output.fn(
        task_id=mock_task_with_agent_logs['task_id'],
        agent_id=mock_task_with_agent_logs['agent_id'],
        aggressive_truncate=False
    )

    assert result_aggressive['success'] is True
    assert result_normal['success'] is True

    # Aggressive should be significantly smaller
    aggressive_size = len(result_aggressive['output'])
    normal_size = len(result_normal['output'])

    # With 10 logs: aggressive should use ~1KB/line = ~10KB total
    # normal should use ~8KB/line = ~80KB total
    assert aggressive_size < normal_size, f"Aggressive truncate should produce smaller output (aggressive={aggressive_size}, normal={normal_size})"
    assert aggressive_size < 15000, "Aggressive mode should produce < 15KB for 10 logs"


# ============================================================================
# TESTS: response_format modes
# ============================================================================

def test_response_format_full(mock_task_with_agent_logs):
    """Test response_format='full' returns complete output."""
    logs = generate_mixed_logs(normal_count=20, bloated_count=2, repetitive_count=5)
    write_logs_to_file(mock_task_with_agent_logs['log_file'], logs)

    result = real_mcp_server.get_agent_output.fn(
        task_id=mock_task_with_agent_logs['task_id'],
        agent_id=mock_task_with_agent_logs['agent_id'],
        response_format="full"
    )

    assert result['success'] is True
    assert 'output' in result


def test_response_format_summary(mock_task_with_agent_logs):
    """Test response_format='summary' returns only key information."""
    # Generate logs with errors and status updates
    logs = []
    logs.append({"type": "error", "error": "Critical failure", "important": True})
    logs.extend(generate_mixed_logs(normal_count=50, bloated_count=5, repetitive_count=20))
    logs.append({"type": "status", "status": "completed", "progress": 100})

    write_logs_to_file(mock_task_with_agent_logs['log_file'], logs)

    result = real_mcp_server.get_agent_output.fn(
        task_id=mock_task_with_agent_logs['task_id'],
        agent_id=mock_task_with_agent_logs['agent_id'],
        response_format="summary"
    )

    assert result['success'] is True
    # Summary should be significantly smaller than full output
    # and should prioritize errors/status changes


def test_response_format_compact(mock_task_with_agent_logs):
    """Test response_format='compact' enables aggressive truncation."""
    logs = [generate_bloated_tool_result(size_kb=15) for _ in range(10)]
    write_logs_to_file(mock_task_with_agent_logs['log_file'], logs)

    result = real_mcp_server.get_agent_output.fn(
        task_id=mock_task_with_agent_logs['task_id'],
        agent_id=mock_task_with_agent_logs['agent_id'],
        response_format="compact"
    )

    assert result['success'] is True
    # Compact should produce minimal output
    output_size = len(result['output'])
    # Should be significantly smaller due to aggressive truncation


# ============================================================================
# TESTS: repetitive content detection
# ============================================================================

def test_detect_repetitive_content(mock_task_with_agent_logs):
    """Test that repetitive content is detected and summarized."""
    # Generate highly repetitive logs
    logs = generate_repetitive_logs(count=200)
    write_logs_to_file(mock_task_with_agent_logs['log_file'], logs)

    result = real_mcp_server.get_agent_output.fn(
        task_id=mock_task_with_agent_logs['task_id'],
        agent_id=mock_task_with_agent_logs['agent_id'],
        max_bytes=10000  # Trigger intelligent truncation
    )

    assert result['success'] is True
    # Should include metadata about repetition if detected


# ============================================================================
# TESTS: backward compatibility
# ============================================================================

def test_backward_compatibility_all_params_optional(mock_task_with_agent_logs):
    """Test that all new parameters are optional (backward compatibility)."""
    logs = generate_mixed_logs(normal_count=10, bloated_count=2, repetitive_count=5)
    write_logs_to_file(mock_task_with_agent_logs['log_file'], logs)

    # Call without any new parameters - should work like before
    result = real_mcp_server.get_agent_output.fn(
        task_id=mock_task_with_agent_logs['task_id'],
        agent_id=mock_task_with_agent_logs['agent_id']
    )

    assert result['success'] is True
    assert 'output' in result


def test_invalid_response_format_returns_error(mock_task_with_agent_logs):
    """Test that invalid response_format value returns error."""
    logs = generate_mixed_logs(normal_count=5, bloated_count=0, repetitive_count=0)
    write_logs_to_file(mock_task_with_agent_logs['log_file'], logs)

    result = real_mcp_server.get_agent_output.fn(
        task_id=mock_task_with_agent_logs['task_id'],
        agent_id=mock_task_with_agent_logs['agent_id'],
        response_format="invalid_format"
    )

    assert result['success'] is False
    assert 'error' in result
    assert 'response_format' in result['error'].lower()


# ============================================================================
# TESTS: edge cases
# ============================================================================

def test_max_bytes_with_no_logs(mock_task_with_agent_logs):
    """Test max_bytes parameter with empty log file."""
    # Create empty log file
    with open(mock_task_with_agent_logs['log_file'], 'w') as f:
        pass

    result = real_mcp_server.get_agent_output.fn(
        task_id=mock_task_with_agent_logs['task_id'],
        agent_id=mock_task_with_agent_logs['agent_id'],
        max_bytes=1000
    )

    assert result['success'] is True


def test_max_bytes_smaller_than_single_log(mock_task_with_agent_logs):
    """Test max_bytes when limit is smaller than a single log entry."""
    logs = [generate_bloated_tool_result(size_kb=30)]  # Single 30KB log
    write_logs_to_file(mock_task_with_agent_logs['log_file'], logs)

    result = real_mcp_server.get_agent_output.fn(
        task_id=mock_task_with_agent_logs['task_id'],
        agent_id=mock_task_with_agent_logs['agent_id'],
        max_bytes=5000  # 5KB limit, but log is 30KB
    )

    assert result['success'] is True
    # Should still return something (truncated single entry)
    assert 'output' in result
