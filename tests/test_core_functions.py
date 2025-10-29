#!/usr/bin/env python3
"""
Unit tests for core utility functions in real_mcp_server.py

Tests cover:
- find_task_workspace() (lines 47-78)
- get_workspace_base_from_task_workspace() (lines 80-92)
- get_global_registry_path() (lines 94-106)
- resolve_workspace_variables() (lines 1048-1097)
- check_tmux_available() (lines 145-152)
- check_tmux_session_exists() (lines 207-215)
- ensure_workspace() (lines 136-143)
- ensure_global_registry() (lines 108-134)
"""

import pytest
import os
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import subprocess
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
def mock_task_workspace(temp_workspace):
    """Create a mock task workspace with AGENT_REGISTRY.json."""
    task_id = "TASK-20251017-TEST"
    task_workspace = os.path.join(temp_workspace, task_id)
    os.makedirs(task_workspace, exist_ok=True)

    registry_data = {
        "task_id": task_id,
        "agents": {}
    }

    registry_path = os.path.join(task_workspace, "AGENT_REGISTRY.json")
    with open(registry_path, 'w') as f:
        json.dump(registry_data, f)

    return {
        "workspace_base": temp_workspace,
        "task_id": task_id,
        "task_workspace": task_workspace,
        "registry_path": registry_path
    }


@pytest.fixture
def mock_subprocess_success():
    """Mock subprocess.run to return success."""
    with patch('subprocess.run') as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "tmux 3.2a"
        mock_result.stderr = ""
        mock_run.return_value = mock_result
        yield mock_run


@pytest.fixture
def mock_subprocess_failure():
    """Mock subprocess.run to return failure."""
    with patch('subprocess.run') as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error"
        mock_run.return_value = mock_result
        yield mock_run


# ============================================================================
# TEST: find_task_workspace() - Lines 47-78
# ============================================================================

def test_find_task_workspace_success_default_location(mock_task_workspace):
    """Test finding task workspace in default WORKSPACE_BASE location."""
    with patch.object(real_mcp_server, 'WORKSPACE_BASE', mock_task_workspace['workspace_base']):
        result = real_mcp_server.find_task_workspace(mock_task_workspace['task_id'])
        assert result == mock_task_workspace['task_workspace']


def test_find_task_workspace_not_found():
    """Test finding non-existent task workspace returns None."""
    with patch.object(real_mcp_server, 'WORKSPACE_BASE', '/nonexistent/path'):
        result = real_mcp_server.find_task_workspace("TASK-NONEXISTENT")
        assert result is None


def test_find_task_workspace_searches_parent_directories(temp_workspace):
    """Test that find_task_workspace searches up parent directories."""
    # Create nested directory structure
    task_id = "TASK-PARENT-SEARCH"
    agent_workspace_dir = os.path.join(temp_workspace, '.agent-workspace', task_id)
    os.makedirs(agent_workspace_dir, exist_ok=True)

    registry_path = os.path.join(agent_workspace_dir, "AGENT_REGISTRY.json")
    with open(registry_path, 'w') as f:
        json.dump({"task_id": task_id}, f)

    # Create a subdirectory and set cwd there
    subdir = os.path.join(temp_workspace, 'subdir1', 'subdir2')
    os.makedirs(subdir, exist_ok=True)

    original_cwd = os.getcwd()
    try:
        os.chdir(subdir)
        # Mock WORKSPACE_BASE to not match, forcing parent directory search
        with patch.object(real_mcp_server, 'WORKSPACE_BASE', '/nonexistent'):
            result = real_mcp_server.find_task_workspace(task_id)
            # Use realpath to handle macOS symlinks (/var -> /private/var)
            assert os.path.realpath(result) == os.path.realpath(agent_workspace_dir)
    finally:
        os.chdir(original_cwd)


def test_find_task_workspace_empty_task_id():
    """Test find_task_workspace with empty task_id."""
    with patch.object(real_mcp_server, 'WORKSPACE_BASE', '/tmp'):
        result = real_mcp_server.find_task_workspace("")
        assert result is None


def test_find_task_workspace_no_registry_file(temp_workspace):
    """Test find_task_workspace when directory exists but no AGENT_REGISTRY.json."""
    task_id = "TASK-NO-REGISTRY"
    task_workspace = os.path.join(temp_workspace, task_id)
    os.makedirs(task_workspace, exist_ok=True)

    with patch.object(real_mcp_server, 'WORKSPACE_BASE', temp_workspace):
        result = real_mcp_server.find_task_workspace(task_id)
        assert result is None


# ============================================================================
# TEST: get_workspace_base_from_task_workspace() - Lines 80-92
# ============================================================================

def test_get_workspace_base_from_task_workspace_success():
    """Test extracting workspace base from task workspace path."""
    task_workspace = "/path/to/.agent-workspace/TASK-123"
    result = real_mcp_server.get_workspace_base_from_task_workspace(task_workspace)
    assert result == "/path/to/.agent-workspace"


def test_get_workspace_base_from_task_workspace_nested():
    """Test extracting workspace base from deeply nested path."""
    task_workspace = "/Users/user/projects/myproject/.agent-workspace/TASK-XYZ"
    result = real_mcp_server.get_workspace_base_from_task_workspace(task_workspace)
    assert result == "/Users/user/projects/myproject/.agent-workspace"


def test_get_workspace_base_from_task_workspace_root():
    """Test extracting workspace base when task is at root level."""
    task_workspace = "/TASK-ROOT"
    result = real_mcp_server.get_workspace_base_from_task_workspace(task_workspace)
    assert result == "/"


def test_get_workspace_base_from_task_workspace_empty_string():
    """Test get_workspace_base with empty string."""
    result = real_mcp_server.get_workspace_base_from_task_workspace("")
    assert result == ""


# ============================================================================
# TEST: get_global_registry_path() - Lines 94-106
# ============================================================================

def test_get_global_registry_path_default():
    """Test getting global registry path with default WORKSPACE_BASE."""
    with patch.object(real_mcp_server, 'WORKSPACE_BASE', '/default/workspace'):
        result = real_mcp_server.get_global_registry_path()
        assert result == "/default/workspace/registry/GLOBAL_REGISTRY.json"


def test_get_global_registry_path_custom():
    """Test getting global registry path with custom workspace_base."""
    custom_base = "/custom/workspace"
    result = real_mcp_server.get_global_registry_path(custom_base)
    assert result == "/custom/workspace/registry/GLOBAL_REGISTRY.json"


def test_get_global_registry_path_none_uses_default():
    """Test that passing None uses WORKSPACE_BASE."""
    with patch.object(real_mcp_server, 'WORKSPACE_BASE', '/default/path'):
        result = real_mcp_server.get_global_registry_path(None)
        assert result == "/default/path/registry/GLOBAL_REGISTRY.json"


# ============================================================================
# TEST: resolve_workspace_variables() - Lines 1048-1097
# ============================================================================

def test_resolve_workspace_variables_vscode_style():
    """Test resolving ${workspaceFolder} VSCode-style variable."""
    test_path = "${workspaceFolder}/subdir"
    with patch('os.getcwd', return_value='/mock/workspace'):
        result = real_mcp_server.resolve_workspace_variables(test_path)
        assert result == "/mock/workspace/subdir"


def test_resolve_workspace_variables_uppercase_style():
    """Test resolving ${WORKSPACE_FOLDER} uppercase variable."""
    test_path = "${WORKSPACE_FOLDER}/config"
    with patch('os.getcwd', return_value='/test/dir'):
        result = real_mcp_server.resolve_workspace_variables(test_path)
        assert result == "/test/dir/config"


def test_resolve_workspace_variables_env_var_style():
    """Test resolving $WORKSPACE_FOLDER environment variable style."""
    test_path = "$WORKSPACE_FOLDER/data"
    with patch('os.getcwd', return_value='/my/project'):
        result = real_mcp_server.resolve_workspace_variables(test_path)
        assert result == "/my/project/data"


def test_resolve_workspace_variables_simple_bracket_style():
    """Test resolving {workspaceFolder} simple bracket style."""
    test_path = "{workspaceFolder}/logs"
    with patch('os.getcwd', return_value='/app'):
        result = real_mcp_server.resolve_workspace_variables(test_path)
        assert result == "/app/logs"


def test_resolve_workspace_variables_absolute_path_unchanged():
    """Test that absolute paths without variables are unchanged."""
    test_path = "/absolute/path/to/file"
    result = real_mcp_server.resolve_workspace_variables(test_path)
    assert result == "/absolute/path/to/file"


def test_resolve_workspace_variables_none_input():
    """Test that None input returns None."""
    result = real_mcp_server.resolve_workspace_variables(None)
    assert result is None


def test_resolve_workspace_variables_empty_string():
    """Test that empty string input returns empty string."""
    result = real_mcp_server.resolve_workspace_variables("")
    assert result == ""


def test_resolve_workspace_variables_multiple_occurrences():
    """Test resolving multiple workspace variables in single path."""
    test_path = "${workspaceFolder}/build/${workspaceFolder}/output"
    with patch('os.getcwd', return_value='/project'):
        result = real_mcp_server.resolve_workspace_variables(test_path)
        assert result == "/project/build//project/output"


def test_resolve_workspace_variables_only_variable():
    """Test resolving path that is only the variable."""
    test_path = "${workspaceFolder}"
    with patch('os.getcwd', return_value='/workspace'):
        result = real_mcp_server.resolve_workspace_variables(test_path)
        assert result == "/workspace"


# ============================================================================
# TEST: check_tmux_available() - Lines 145-152
# ============================================================================

def test_check_tmux_available_success(mock_subprocess_success):
    """Test check_tmux_available when tmux is available."""
    result = real_mcp_server.check_tmux_available()
    assert result is True
    mock_subprocess_success.assert_called_once_with(
        ['tmux', '-V'],
        capture_output=True,
        text=True,
        timeout=5
    )


def test_check_tmux_available_not_found():
    """Test check_tmux_available when tmux is not installed."""
    with patch('subprocess.run', side_effect=FileNotFoundError):
        result = real_mcp_server.check_tmux_available()
        assert result is False


def test_check_tmux_available_timeout():
    """Test check_tmux_available when tmux command times out."""
    with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('tmux', 5)):
        result = real_mcp_server.check_tmux_available()
        assert result is False


def test_check_tmux_available_nonzero_return():
    """Test check_tmux_available when tmux returns non-zero exit code."""
    with patch('subprocess.run') as mock_run:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_run.return_value = mock_result
        result = real_mcp_server.check_tmux_available()
        assert result is False


# ============================================================================
# TEST: check_tmux_session_exists() - Lines 207-215
# ============================================================================

def test_check_tmux_session_exists_true(mock_subprocess_success):
    """Test check_tmux_session_exists when session exists."""
    result = real_mcp_server.check_tmux_session_exists("test-session")
    assert result is True
    mock_subprocess_success.assert_called_once_with(
        ['tmux', 'has-session', '-t', 'test-session'],
        capture_output=True,
        text=True
    )


def test_check_tmux_session_exists_false(mock_subprocess_failure):
    """Test check_tmux_session_exists when session does not exist."""
    result = real_mcp_server.check_tmux_session_exists("nonexistent-session")
    assert result is False


def test_check_tmux_session_exists_exception():
    """Test check_tmux_session_exists handles exceptions gracefully."""
    with patch('subprocess.run', side_effect=Exception("Test error")):
        result = real_mcp_server.check_tmux_session_exists("any-session")
        assert result is False


def test_check_tmux_session_exists_empty_session_name(mock_subprocess_failure):
    """Test check_tmux_session_exists with empty session name."""
    result = real_mcp_server.check_tmux_session_exists("")
    assert result is False


# ============================================================================
# TEST: ensure_global_registry() - Lines 108-134
# ============================================================================

def test_ensure_global_registry_creates_new(temp_workspace):
    """Test ensure_global_registry creates new registry when none exists."""
    registry_dir = os.path.join(temp_workspace, "registry")
    registry_path = os.path.join(registry_dir, "GLOBAL_REGISTRY.json")

    real_mcp_server.ensure_global_registry(temp_workspace)

    assert os.path.exists(registry_path)

    with open(registry_path, 'r') as f:
        data = json.load(f)

    assert "created_at" in data
    assert data["total_tasks"] == 0
    assert data["active_tasks"] == 0
    assert data["total_agents_spawned"] == 0
    assert data["active_agents"] == 0
    assert "max_concurrent_agents" in data
    assert "tasks" in data
    assert "agents" in data


def test_ensure_global_registry_uses_default(temp_workspace):
    """Test ensure_global_registry uses WORKSPACE_BASE when no param provided."""
    with patch.object(real_mcp_server, 'WORKSPACE_BASE', temp_workspace):
        registry_path = os.path.join(temp_workspace, "registry", "GLOBAL_REGISTRY.json")

        real_mcp_server.ensure_global_registry()

        assert os.path.exists(registry_path)


def test_ensure_global_registry_does_not_overwrite(temp_workspace):
    """Test ensure_global_registry does not overwrite existing registry."""
    registry_dir = os.path.join(temp_workspace, "registry")
    os.makedirs(registry_dir, exist_ok=True)
    registry_path = os.path.join(registry_dir, "GLOBAL_REGISTRY.json")

    # Create existing registry with custom data
    existing_data = {
        "created_at": "2025-01-01T00:00:00",
        "total_tasks": 42,
        "custom_field": "should_remain"
    }
    with open(registry_path, 'w') as f:
        json.dump(existing_data, f)

    real_mcp_server.ensure_global_registry(temp_workspace)

    # Verify existing data is not overwritten
    with open(registry_path, 'r') as f:
        data = json.load(f)

    assert data["total_tasks"] == 42
    assert data["custom_field"] == "should_remain"


def test_ensure_global_registry_creates_directory(temp_workspace):
    """Test ensure_global_registry creates registry directory if missing."""
    # Verify registry directory doesn't exist initially
    registry_dir = os.path.join(temp_workspace, "registry")
    assert not os.path.exists(registry_dir)

    real_mcp_server.ensure_global_registry(temp_workspace)

    # Verify directory was created
    assert os.path.exists(registry_dir)
    assert os.path.isdir(registry_dir)


# ============================================================================
# TEST: ensure_workspace() - Lines 136-143
# ============================================================================

def test_ensure_workspace_success(temp_workspace):
    """Test ensure_workspace successfully initializes workspace."""
    with patch.object(real_mcp_server, 'WORKSPACE_BASE', temp_workspace):
        real_mcp_server.ensure_workspace()

        registry_path = os.path.join(temp_workspace, "registry", "GLOBAL_REGISTRY.json")
        assert os.path.exists(registry_path)


def test_ensure_workspace_handles_errors():
    """Test ensure_workspace raises exception on error."""
    with patch.object(real_mcp_server, 'ensure_global_registry', side_effect=Exception("Test error")):
        with pytest.raises(Exception, match="Test error"):
            real_mcp_server.ensure_workspace()


def test_ensure_workspace_idempotent(temp_workspace):
    """Test ensure_workspace can be called multiple times safely."""
    with patch.object(real_mcp_server, 'WORKSPACE_BASE', temp_workspace):
        # Call multiple times
        real_mcp_server.ensure_workspace()
        real_mcp_server.ensure_workspace()
        real_mcp_server.ensure_workspace()

        # Verify registry still exists and is valid
        registry_path = os.path.join(temp_workspace, "registry", "GLOBAL_REGISTRY.json")
        assert os.path.exists(registry_path)

        with open(registry_path, 'r') as f:
            data = json.load(f)
        assert "tasks" in data


# ============================================================================
# EDGE CASES AND ERROR CONDITIONS
# ============================================================================

def test_find_task_workspace_special_characters():
    """Test find_task_workspace handles special characters in task_id."""
    special_task_id = "TASK-2025@#$%-TEST"
    with patch.object(real_mcp_server, 'WORKSPACE_BASE', '/tmp'):
        # Should not crash, just return None for non-existent path
        result = real_mcp_server.find_task_workspace(special_task_id)
        assert result is None


def test_resolve_workspace_variables_mixed_case():
    """Test resolve_workspace_variables with mixed case patterns."""
    test_path = "${workspaceFolder}/test/${WORKSPACE_FOLDER}/data"
    with patch('os.getcwd', return_value='/base'):
        result = real_mcp_server.resolve_workspace_variables(test_path)
        # Both patterns should be resolved
        assert "/base/test/" in result


def test_get_workspace_base_edge_case_single_char():
    """Test get_workspace_base with minimal path."""
    result = real_mcp_server.get_workspace_base_from_task_workspace("a")
    assert result == ""


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v"])
