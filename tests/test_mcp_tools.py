"""
Integration tests for MCP tools in real_mcp_server.py

Tests all 8 MCP tools with proper mocking and validation:
- create_real_task (line 1100)
- deploy_headless_agent (line 1200)
- get_real_task_status (line 1500)
- get_agent_output (line 1635)
- kill_real_agent (line 1699)
- update_agent_progress (line 2120)
- report_agent_finding (line 2261)
- spawn_child_agent (line 2321)
"""

import pytest
import json
import os
import tempfile
import shutil
from datetime import datetime
from unittest.mock import patch, MagicMock, mock_open, call
from pathlib import Path


# Import the module under test
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import real_mcp_server


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace for testing"""
    temp_dir = tempfile.mkdtemp()
    workspace_base = os.path.join(temp_dir, '.agent-workspace')
    os.makedirs(workspace_base, exist_ok=True)

    # Create registry directory
    registry_dir = os.path.join(workspace_base, 'registry')
    os.makedirs(registry_dir, exist_ok=True)

    # Create global registry
    global_registry = {
        "total_tasks": 0,
        "active_tasks": 0,
        "total_agents": 0,
        "active_agents": 0,
        "total_agents_spawned": 0,
        "tasks": {},
        "agents": {}
    }
    global_reg_path = os.path.join(registry_dir, 'GLOBAL_REGISTRY.json')
    with open(global_reg_path, 'w') as f:
        json.dump(global_registry, f)

    # Temporarily override WORKSPACE_BASE
    original_workspace_base = real_mcp_server.WORKSPACE_BASE
    real_mcp_server.WORKSPACE_BASE = workspace_base

    yield workspace_base

    # Cleanup
    real_mcp_server.WORKSPACE_BASE = original_workspace_base
    shutil.rmtree(temp_dir)


def get_mock_project_context():
    """Helper to return a valid mock project context"""
    return {
        "language": "Python",
        "frameworks": [],
        "testing_framework": "pytest",
        "package_manager": "pip",
        "project_type": "mcp_server",
        "config_files_found": ["pyproject.toml"],
        "confidence": "high",
        "source": "config_files"
    }


@pytest.fixture
def mock_task_workspace(temp_workspace):
    """Create a mock task workspace with registry"""
    task_id = "TASK-20251017-123456-abc123"
    workspace = os.path.join(temp_workspace, task_id)

    # Create task directories
    os.makedirs(os.path.join(workspace, 'progress'), exist_ok=True)
    os.makedirs(os.path.join(workspace, 'logs'), exist_ok=True)
    os.makedirs(os.path.join(workspace, 'findings'), exist_ok=True)
    os.makedirs(os.path.join(workspace, 'output'), exist_ok=True)

    # Create task registry
    registry = {
        "task_id": task_id,
        "task_description": "Test task",
        "created_at": datetime.now().isoformat(),
        "workspace": workspace,
        "workspace_base": temp_workspace,
        "status": "INITIALIZED",
        "priority": "P2",
        "agents": [],
        "agent_hierarchy": {"orchestrator": []},
        "max_agents": 10,
        "max_depth": 3,
        "max_concurrent": 5,
        "total_spawned": 0,
        "active_count": 0,
        "completed_count": 0,
        "spiral_checks": {
            "enabled": True,
            "last_check": datetime.now().isoformat(),
            "violations": 0
        },
        "orchestration_guidance": {
            "min_specialization_depth": 2,
            "recommended_child_agents_per_parent": 3,
            "specialization_domains": [],
            "complexity_score": 5
        }
    }

    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'w') as f:
        json.dump(registry, f, indent=2)

    # Update global registry to include this task
    global_reg_path = os.path.join(temp_workspace, 'registry', 'GLOBAL_REGISTRY.json')
    with open(global_reg_path, 'r') as f:
        global_reg = json.load(f)

    global_reg['total_tasks'] += 1
    global_reg['active_tasks'] += 1
    global_reg['tasks'][task_id] = {
        'description': 'Test task',
        'created_at': datetime.now().isoformat(),
        'status': 'INITIALIZED'
    }

    with open(global_reg_path, 'w') as f:
        json.dump(global_reg, f)

    return task_id, workspace, registry


# ============================================================================
# Tests for create_real_task (line 1100)
# ============================================================================

def test_create_real_task_success(temp_workspace):
    """Test successful task creation"""
    with patch('real_mcp_server.calculate_task_complexity', return_value=5):
        result = real_mcp_server.create_real_task.fn(
            description="Test task creation",
            priority="P1"
        )

    assert result["success"] is True
    assert "task_id" in result
    assert result["description"] == "Test task creation"
    assert result["priority"] == "P1"
    assert result["status"] == "INITIALIZED"

    # Verify workspace was created
    task_id = result["task_id"]
    workspace = result["workspace"]
    assert os.path.exists(workspace)
    assert os.path.exists(os.path.join(workspace, 'progress'))
    assert os.path.exists(os.path.join(workspace, 'logs'))
    assert os.path.exists(os.path.join(workspace, 'findings'))
    assert os.path.exists(os.path.join(workspace, 'output'))

    # Verify registry was created
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    assert os.path.exists(registry_path)

    with open(registry_path, 'r') as f:
        registry = json.load(f)
    assert registry["task_id"] == task_id
    assert registry["task_description"] == "Test task creation"
    assert registry["priority"] == "P1"


def test_create_real_task_with_client_cwd(temp_workspace):
    """Test task creation with client working directory"""
    # Use a valid temporary directory instead of read-only path
    import tempfile
    client_cwd = tempfile.mkdtemp()

    try:
        with patch('real_mcp_server.calculate_task_complexity', return_value=3), \
             patch('real_mcp_server.resolve_workspace_variables', return_value=client_cwd):
            result = real_mcp_server.create_real_task.fn(
                description="Client task",
                client_cwd="${workspaceFolder}"
            )

        assert result["success"] is True
        # Workspace should be created under client_cwd
        assert client_cwd in result["workspace"] or temp_workspace in result["workspace"]
    finally:
        # Cleanup
        shutil.rmtree(client_cwd, ignore_errors=True)


def test_create_real_task_default_priority(temp_workspace):
    """Test task creation with default priority"""
    with patch('real_mcp_server.calculate_task_complexity', return_value=2):
        result = real_mcp_server.create_real_task.fn(
            description="Default priority task"
        )

    assert result["success"] is True
    assert result["priority"] == "P2"  # Default priority


def test_create_real_task_updates_global_registry(temp_workspace):
    """Test that task creation updates the global registry"""
    with patch('real_mcp_server.calculate_task_complexity', return_value=4):
        result = real_mcp_server.create_real_task.fn(
            description="Global registry test"
        )

    # Check global registry
    global_reg_path = os.path.join(temp_workspace, 'registry', 'GLOBAL_REGISTRY.json')
    with open(global_reg_path, 'r') as f:
        global_reg = json.load(f)

    assert global_reg["total_tasks"] == 1
    assert global_reg["active_tasks"] == 1
    assert result["task_id"] in global_reg["tasks"]
    assert global_reg["tasks"][result["task_id"]]["description"] == "Global registry test"


# ============================================================================
# Tests for deploy_headless_agent (line 1200)
# ============================================================================

@patch('real_mcp_server.check_tmux_available', return_value=True)
@patch('real_mcp_server.subprocess.run')
@patch('real_mcp_server.detect_project_context')
def test_deploy_headless_agent_success(mock_detect_context, mock_subprocess, mock_tmux_check, mock_task_workspace):
    """Test successful agent deployment"""
    task_id, workspace, registry = mock_task_workspace

    # Mock successful tmux command
    mock_subprocess.return_value = MagicMock(returncode=0)

    # Mock project context detection
    mock_detect_context.return_value = get_mock_project_context()

    with patch('real_mcp_server.find_task_workspace', return_value=workspace):
        result = real_mcp_server.deploy_headless_agent.fn(
            task_id=task_id,
            agent_type="investigator",
            prompt="Investigate the codebase",
            parent="orchestrator"
        )

    assert result["success"] is True
    assert "agent_id" in result
    assert result["agent_type"] == "investigator"
    assert result["parent"] == "orchestrator"
    assert "tmux_session" in result


@patch('real_mcp_server.check_tmux_available', return_value=False)
def test_deploy_headless_agent_no_tmux(mock_tmux_check, mock_task_workspace):
    """Test agent deployment when tmux is not available"""
    task_id, workspace, registry = mock_task_workspace

    result = real_mcp_server.deploy_headless_agent.fn(
        task_id=task_id,
        agent_type="builder",
        prompt="Build something"
    )

    assert result["success"] is False
    assert "tmux" in result["error"].lower()


@patch('real_mcp_server.check_tmux_available', return_value=True)
def test_deploy_headless_agent_task_not_found(mock_tmux_check):
    """Test agent deployment with non-existent task"""
    with patch('real_mcp_server.find_task_workspace', return_value=None):
        result = real_mcp_server.deploy_headless_agent.fn(
            task_id="TASK-INVALID",
            agent_type="fixer",
            prompt="Fix bugs"
        )

    assert result["success"] is False
    assert "not found" in result["error"]


@patch('real_mcp_server.check_tmux_available', return_value=True)
@patch('real_mcp_server.subprocess.run')
def test_deploy_headless_agent_max_concurrent_limit(mock_subprocess, mock_tmux_check, mock_task_workspace):
    """Test agent deployment respects max concurrent limit"""
    task_id, workspace, registry = mock_task_workspace

    # Modify registry to simulate max concurrent reached
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)
    reg['active_count'] = 5  # At max concurrent
    reg['max_concurrent'] = 5
    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    with patch('real_mcp_server.find_task_workspace', return_value=workspace):
        result = real_mcp_server.deploy_headless_agent.fn(
            task_id=task_id,
            agent_type="tester",
            prompt="Run tests"
        )

    assert result["success"] is False
    assert "Too many active agents" in result["error"]


@patch('real_mcp_server.check_tmux_available', return_value=True)
@patch('real_mcp_server.subprocess.run')
def test_deploy_headless_agent_max_agents_limit(mock_subprocess, mock_tmux_check, mock_task_workspace):
    """Test agent deployment respects max agents limit"""
    task_id, workspace, registry = mock_task_workspace

    # Modify registry to simulate max agents reached
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)
    reg['total_spawned'] = 10  # At max agents
    reg['max_agents'] = 10
    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    with patch('real_mcp_server.find_task_workspace', return_value=workspace):
        result = real_mcp_server.deploy_headless_agent.fn(
            task_id=task_id,
            agent_type="analyzer",
            prompt="Analyze code"
        )

    assert result["success"] is False
    assert "max_agents" in result["error"].lower() or "max agents" in result["error"].lower()


# ============================================================================
# Tests for get_real_task_status (line 1500)
# ============================================================================

def test_get_real_task_status_success(mock_task_workspace):
    """Test getting task status successfully"""
    task_id, workspace, registry = mock_task_workspace

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.check_tmux_session_exists', return_value=True):
        result = real_mcp_server.get_real_task_status.fn(task_id=task_id)

    assert result["success"] is True
    assert result["task_id"] == task_id
    assert result["description"] == "Test task"
    assert result["status"] == "INITIALIZED"
    assert "agents" in result
    assert "hierarchy" in result
    assert "limits" in result


def test_get_real_task_status_task_not_found():
    """Test getting status of non-existent task"""
    with patch('real_mcp_server.find_task_workspace', return_value=None):
        result = real_mcp_server.get_real_task_status.fn(task_id="TASK-INVALID")

    assert result["success"] is False
    assert "not found" in result["error"]


@patch('real_mcp_server.check_tmux_session_exists', return_value=False)
def test_get_real_task_status_detects_completed_agents(mock_tmux_check, mock_task_workspace):
    """Test that status check detects completed agents via tmux session termination"""
    task_id, workspace, registry = mock_task_workspace

    # Add a running agent to registry
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)

    agent = {
        "id": "test-agent-123",
        "type": "investigator",
        "tmux_session": "agent_test-agent-123",
        "status": "running",
        "started_at": datetime.now().isoformat()
    }
    reg['agents'].append(agent)
    reg['active_count'] = 1
    reg['total_spawned'] = 1

    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    with patch('real_mcp_server.find_task_workspace', return_value=workspace):
        result = real_mcp_server.get_real_task_status.fn(task_id=task_id)

    assert result["success"] is True
    # Agent should be marked as completed
    agents_list = result["agents"]["agents_list"]
    assert len(agents_list) == 1
    assert agents_list[0]["status"] == "completed"
    assert "completed_at" in agents_list[0]


def test_get_real_task_status_with_progress_and_findings(mock_task_workspace):
    """Test status includes progress and findings data"""
    task_id, workspace, registry = mock_task_workspace

    # Add progress entries
    progress_file = os.path.join(workspace, 'progress', 'agent1_progress.jsonl')
    progress_entry = {
        "timestamp": datetime.now().isoformat(),
        "agent_id": "agent1",
        "status": "working",
        "message": "Making progress",
        "progress": 50
    }
    with open(progress_file, 'w') as f:
        f.write(json.dumps(progress_entry) + '\n')

    # Add findings
    findings_file = os.path.join(workspace, 'findings', 'agent1_findings.jsonl')
    finding_entry = {
        "timestamp": datetime.now().isoformat(),
        "agent_id": "agent1",
        "finding_type": "issue",
        "severity": "high",
        "message": "Found a bug",
        "data": {"file": "test.py", "line": 42}
    }
    with open(findings_file, 'w') as f:
        f.write(json.dumps(finding_entry) + '\n')

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.check_tmux_session_exists', return_value=True):
        result = real_mcp_server.get_real_task_status.fn(task_id=task_id)

    assert result["success"] is True
    assert "enhanced_progress" in result
    assert len(result["enhanced_progress"]["recent_updates"]) > 0
    assert len(result["enhanced_progress"]["recent_findings"]) > 0


# ============================================================================
# Tests for get_agent_output (line 1635)
# ============================================================================

def test_get_agent_output_success(mock_task_workspace):
    """Test getting agent output successfully"""
    task_id, workspace, registry = mock_task_workspace

    # Add agent to registry
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)

    agent_id = "test-agent-456"
    agent = {
        "id": agent_id,
        "type": "builder",
        "tmux_session": "agent_test-agent-456",
        "status": "running"
    }
    reg['agents'].append(agent)

    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    mock_output = "Agent output line 1\nAgent output line 2"

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.check_tmux_session_exists', return_value=True), \
         patch('real_mcp_server.get_tmux_session_output', return_value=mock_output):
        result = real_mcp_server.get_agent_output.fn(
            task_id=task_id,
            agent_id=agent_id
        )

    assert result["success"] is True
    assert result["agent_id"] == agent_id
    assert result["session_status"] == "running"
    assert result["output"] == mock_output


def test_get_agent_output_task_not_found():
    """Test getting output with non-existent task"""
    with patch('real_mcp_server.find_task_workspace', return_value=None):
        result = real_mcp_server.get_agent_output.fn(
            task_id="TASK-INVALID",
            agent_id="agent-123"
        )

    assert result["success"] is False
    assert "not found" in result["error"]


def test_get_agent_output_agent_not_found(mock_task_workspace):
    """Test getting output for non-existent agent"""
    task_id, workspace, registry = mock_task_workspace

    with patch('real_mcp_server.find_task_workspace', return_value=workspace):
        result = real_mcp_server.get_agent_output.fn(
            task_id=task_id,
            agent_id="nonexistent-agent"
        )

    assert result["success"] is False
    assert "not found" in result["error"]


def test_get_agent_output_session_terminated(mock_task_workspace):
    """Test getting output when tmux session has terminated"""
    task_id, workspace, registry = mock_task_workspace

    # Add agent to registry
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)

    agent_id = "terminated-agent"
    agent = {
        "id": agent_id,
        "type": "fixer",
        "tmux_session": "agent_terminated-agent",
        "status": "running"
    }
    reg['agents'].append(agent)

    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.check_tmux_session_exists', return_value=False):
        result = real_mcp_server.get_agent_output.fn(
            task_id=task_id,
            agent_id=agent_id
        )

    assert result["success"] is True
    assert result["session_status"] == "terminated"
    assert "terminated" in result["output"].lower()


# ============================================================================
# Tests for kill_real_agent (line 1699)
# ============================================================================

@patch('real_mcp_server.subprocess.run')
def test_kill_real_agent_success(mock_subprocess, mock_task_workspace):
    """Test killing an agent successfully"""
    task_id, workspace, registry = mock_task_workspace

    # Add agent to registry
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)

    agent_id = "agent-to-kill"
    agent = {
        "id": agent_id,
        "type": "analyzer",
        "tmux_session": "agent_agent-to-kill",
        "status": "running"
    }
    reg['agents'].append(agent)
    reg['active_count'] = 1

    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    mock_subprocess.return_value = MagicMock(returncode=0)

    with patch('real_mcp_server.find_task_workspace', return_value=workspace):
        result = real_mcp_server.kill_real_agent.fn(
            task_id=task_id,
            agent_id=agent_id,
            reason="Test termination"
        )

    assert result["success"] is True
    assert result["agent_id"] == agent_id
    assert result["reason"] == "Test termination"


def test_kill_real_agent_task_not_found():
    """Test killing agent with non-existent task"""
    with patch('real_mcp_server.find_task_workspace', return_value=None):
        result = real_mcp_server.kill_real_agent.fn(
            task_id="TASK-INVALID",
            agent_id="agent-123"
        )

    assert result["success"] is False
    assert "not found" in result["error"]


def test_kill_real_agent_agent_not_found(mock_task_workspace):
    """Test killing non-existent agent"""
    task_id, workspace, registry = mock_task_workspace

    with patch('real_mcp_server.find_task_workspace', return_value=workspace):
        result = real_mcp_server.kill_real_agent.fn(
            task_id=task_id,
            agent_id="nonexistent-agent"
        )

    assert result["success"] is False
    assert "not found" in result["error"]


# ============================================================================
# Tests for update_agent_progress (line 2120)
# ============================================================================

def test_update_agent_progress_success(mock_task_workspace):
    """Test updating agent progress successfully"""
    task_id, workspace, registry = mock_task_workspace

    # Add agent to registry
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)

    agent_id = "progress-agent"
    agent = {
        "id": agent_id,
        "type": "builder",
        "status": "running",
        "progress": 0
    }
    reg['agents'].append(agent)
    reg['active_count'] = 1

    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.get_comprehensive_task_status') as mock_comprehensive:
        mock_comprehensive.return_value = {"success": True, "task_id": task_id}

        result = real_mcp_server.update_agent_progress.fn(
            task_id=task_id,
            agent_id=agent_id,
            status="working",
            message="Building features",
            progress=50
        )

    assert result["success"] is True
    assert result["own_update"]["agent_id"] == agent_id
    assert result["own_update"]["status"] == "working"
    assert result["own_update"]["progress"] == 50
    assert result["own_update"]["message"] == "Building features"
    assert "coordination_info" in result

    # Verify progress was logged to JSONL
    progress_file = os.path.join(workspace, 'progress', f'{agent_id}_progress.jsonl')
    assert os.path.exists(progress_file)
    with open(progress_file, 'r') as f:
        lines = f.readlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["agent_id"] == agent_id
        assert entry["progress"] == 50


def test_update_agent_progress_completion(mock_task_workspace):
    """Test updating agent to completed status"""
    task_id, workspace, registry = mock_task_workspace

    # Add agent to registry
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)

    agent_id = "completing-agent"
    agent = {
        "id": agent_id,
        "type": "tester",
        "status": "working",
        "progress": 90
    }
    reg['agents'].append(agent)
    reg['active_count'] = 1
    reg['completed_count'] = 0

    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    # Mock validation function
    mock_validation = {
        "valid": True,
        "confidence": 0.95,
        "warnings": [],
        "blocking_issues": [],
        "evidence_summary": {"files_modified": 3, "findings_reported": 2}
    }

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.validate_agent_completion', return_value=mock_validation), \
         patch('real_mcp_server.get_comprehensive_task_status') as mock_comprehensive:
        mock_comprehensive.return_value = {"success": True, "task_id": task_id}

        result = real_mcp_server.update_agent_progress.fn(
            task_id=task_id,
            agent_id=agent_id,
            status="completed",
            message="All tests passed",
            progress=100
        )

    assert result["success"] is True
    assert result["own_update"]["status"] == "completed"
    assert result["own_update"]["progress"] == 100

    # Verify registry was updated
    with open(registry_path, 'r') as f:
        updated_reg = json.load(f)

    updated_agent = updated_reg['agents'][0]
    assert updated_agent["status"] == "completed"
    assert updated_agent["progress"] == 100
    assert "completed_at" in updated_agent
    assert "completion_validation" in updated_agent
    assert updated_agent["completion_validation"]["confidence"] == 0.95

    # Verify active count decreased and completed count increased
    assert updated_reg['active_count'] == 0
    assert updated_reg['completed_count'] == 1


def test_update_agent_progress_task_not_found():
    """Test updating progress with non-existent task"""
    with patch('real_mcp_server.find_task_workspace', return_value=None):
        result = real_mcp_server.update_agent_progress.fn(
            task_id="TASK-INVALID",
            agent_id="agent-123",
            status="working",
            message="Working hard"
        )

    assert result["success"] is False
    assert "not found" in result["error"]


def test_update_agent_progress_returns_coordination_info(mock_task_workspace):
    """Test that update_agent_progress returns comprehensive coordination data"""
    task_id, workspace, registry = mock_task_workspace

    # Add agent
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)

    agent_id = "coord-agent"
    agent = {"id": agent_id, "type": "coordinator", "status": "running"}
    reg['agents'].append(agent)

    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    mock_comprehensive = {
        "success": True,
        "task_id": task_id,
        "agents": {"total_spawned": 1, "active": 1, "completed": 0},
        "coordination_data": {
            "recent_progress": [],
            "recent_findings": [],
            "agent_status_summary": {}
        }
    }

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.get_comprehensive_task_status', return_value=mock_comprehensive):
        result = real_mcp_server.update_agent_progress.fn(
            task_id=task_id,
            agent_id=agent_id,
            status="working",
            message="Coordinating",
            progress=25
        )

    assert result["success"] is True
    assert "coordination_info" in result
    assert result["coordination_info"]["success"] is True
    assert "coordination_data" in result["coordination_info"]


# ============================================================================
# Tests for report_agent_finding (line 2261)
# ============================================================================

def test_report_agent_finding_success(mock_task_workspace):
    """Test reporting agent finding successfully"""
    task_id, workspace, registry = mock_task_workspace

    agent_id = "finder-agent"

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.get_comprehensive_task_status') as mock_comprehensive:
        mock_comprehensive.return_value = {"success": True, "task_id": task_id}

        result = real_mcp_server.report_agent_finding.fn(
            task_id=task_id,
            agent_id=agent_id,
            finding_type="issue",
            severity="high",
            message="Found critical bug in authentication",
            data={"file": "auth.py", "line": 127, "type": "sql_injection"}
        )

    assert result["success"] is True
    assert result["own_finding"]["agent_id"] == agent_id
    assert result["own_finding"]["finding_type"] == "issue"
    assert result["own_finding"]["severity"] == "high"
    assert result["own_finding"]["message"] == "Found critical bug in authentication"
    assert result["own_finding"]["data"]["file"] == "auth.py"
    assert "coordination_info" in result

    # Verify finding was logged to JSONL
    findings_file = os.path.join(workspace, 'findings', f'{agent_id}_findings.jsonl')
    assert os.path.exists(findings_file)
    with open(findings_file, 'r') as f:
        lines = f.readlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["agent_id"] == agent_id
        assert entry["finding_type"] == "issue"
        assert entry["severity"] == "high"


def test_report_agent_finding_with_no_data(mock_task_workspace):
    """Test reporting finding without additional data"""
    task_id, workspace, registry = mock_task_workspace

    agent_id = "insight-agent"

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.get_comprehensive_task_status') as mock_comprehensive:
        mock_comprehensive.return_value = {"success": True, "task_id": task_id}

        result = real_mcp_server.report_agent_finding.fn(
            task_id=task_id,
            agent_id=agent_id,
            finding_type="insight",
            severity="low",
            message="Discovered optimization opportunity"
        )

    assert result["success"] is True
    assert result["own_finding"]["data"] == {}


def test_report_agent_finding_task_not_found():
    """Test reporting finding with non-existent task"""
    with patch('real_mcp_server.find_task_workspace', return_value=None):
        result = real_mcp_server.report_agent_finding.fn(
            task_id="TASK-INVALID",
            agent_id="agent-123",
            finding_type="issue",
            severity="medium",
            message="Found something"
        )

    assert result["success"] is False
    assert "not found" in result["error"]


def test_report_agent_finding_returns_coordination_info(mock_task_workspace):
    """Test that report_agent_finding returns comprehensive coordination data"""
    task_id, workspace, registry = mock_task_workspace

    agent_id = "reporting-agent"

    mock_comprehensive = {
        "success": True,
        "task_id": task_id,
        "agents": {"total_spawned": 1, "active": 1, "completed": 0},
        "coordination_data": {
            "recent_progress": [],
            "recent_findings": [],
            "agent_status_summary": {}
        }
    }

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.get_comprehensive_task_status', return_value=mock_comprehensive):
        result = real_mcp_server.report_agent_finding.fn(
            task_id=task_id,
            agent_id=agent_id,
            finding_type="solution",
            severity="medium",
            message="Implemented fix"
        )

    assert result["success"] is True
    assert "coordination_info" in result
    assert result["coordination_info"]["success"] is True
    assert "coordination_data" in result["coordination_info"]


# ============================================================================
# Tests for spawn_child_agent (line 2321)
# ============================================================================

@patch('real_mcp_server.check_tmux_available', return_value=True)
@patch('real_mcp_server.subprocess.run')
@patch('real_mcp_server.detect_project_context')
def test_spawn_child_agent_success(mock_detect_context, mock_subprocess, mock_tmux_check, mock_task_workspace):
    """Test spawning child agent successfully"""
    task_id, workspace, registry = mock_task_workspace

    # Add parent agent
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)

    parent_id = "parent-agent"
    parent = {
        "id": parent_id,
        "type": "coordinator",
        "status": "running"
    }
    reg['agents'].append(parent)
    reg['agent_hierarchy']['orchestrator'].append(parent_id)
    reg['agent_hierarchy'][parent_id] = []

    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    mock_subprocess.return_value = MagicMock(returncode=0)
    mock_detect_context.return_value = get_mock_project_context()

    with patch('real_mcp_server.find_task_workspace', return_value=workspace):
        result = real_mcp_server.spawn_child_agent.fn(
            task_id=task_id,
            parent_agent_id=parent_id,
            child_agent_type="specialist",
            child_prompt="Specialize in database queries"
        )

    # spawn_child_agent delegates to deploy_headless_agent.fn
    assert result["success"] is True
    assert "agent_id" in result


@patch('real_mcp_server.check_tmux_available', return_value=True)
def test_spawn_child_agent_task_not_found(mock_tmux_check):
    """Test spawning child with non-existent task"""
    with patch('real_mcp_server.find_task_workspace', return_value=None):
        result = real_mcp_server.spawn_child_agent.fn(
            task_id="TASK-INVALID",
            parent_agent_id="parent-123",
            child_agent_type="helper",
            child_prompt="Help with something"
        )

    assert result["success"] is False
    assert "not found" in result["error"]


# ============================================================================
# Tests for .fn attribute fix (Critical Bug from docs)
# ============================================================================

@patch('real_mcp_server.check_tmux_available', return_value=True)
@patch('real_mcp_server.subprocess.run')
@patch('real_mcp_server.detect_project_context')
def test_fn_attribute_in_spawn_child_agent(mock_detect_context, mock_subprocess, mock_tmux_check, mock_task_workspace):
    """
    Test the .fn attribute fix for FastMCP tool self-invocation.

    This tests the critical bug fix documented in CLAUDE.md:
    - Line 2336: spawn_child_agent calls deploy_headless_agent.fn(...)
    - Without .fn, FastMCP FunctionTool objects are not callable
    """
    task_id, workspace, registry = mock_task_workspace

    # Add parent agent
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)

    parent_id = "parent-test-fn"
    parent = {"id": parent_id, "type": "test", "status": "running"}
    reg['agents'].append(parent)
    reg['agent_hierarchy']['orchestrator'].append(parent_id)
    reg['agent_hierarchy'][parent_id] = []

    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    mock_subprocess.return_value = MagicMock(returncode=0)
    mock_detect_context.return_value = get_mock_project_context()

    with patch('real_mcp_server.find_task_workspace', return_value=workspace):
        # This should NOT raise "'FunctionTool' object is not callable"
        result = real_mcp_server.spawn_child_agent.fn(
            task_id=task_id,
            parent_agent_id=parent_id,
            child_agent_type="fn_test_child",
            child_prompt="Test .fn attribute"
        )

    # If we get here without TypeError, the .fn fix is working
    assert result["success"] is True


def test_fn_attribute_allows_tool_self_invocation(mock_task_workspace):
    """
    Test that MCP tools can call other MCP tools using .fn attribute.

    This verifies the fix for the FastMCP self-invocation bug:
    - update_agent_progress and report_agent_finding call get_comprehensive_task_status
    - These calls must work without raising FunctionTool errors
    """
    task_id, workspace, registry = mock_task_workspace

    # Add agent
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)

    agent_id = "fn-test-agent"
    agent = {"id": agent_id, "type": "tester", "status": "running"}
    reg['agents'].append(agent)

    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    # This internally calls get_comprehensive_task_status (non-.fn version is fine for internal calls)
    with patch('real_mcp_server.find_task_workspace', return_value=workspace):
        # Should not raise TypeError about FunctionTool
        result = real_mcp_server.update_agent_progress.fn(
            task_id=task_id,
            agent_id=agent_id,
            status="working",
            message="Testing .fn invocation",
            progress=75
        )

    assert result["success"] is True

    # Same test for report_agent_finding
    with patch('real_mcp_server.find_task_workspace', return_value=workspace):
        result = real_mcp_server.report_agent_finding.fn(
            task_id=task_id,
            agent_id=agent_id,
            finding_type="insight",
            severity="low",
            message="Testing .fn in findings"
        )

    assert result["success"] is True


# ============================================================================
# Edge case and error condition tests
# ============================================================================

def test_update_agent_progress_multiple_calls_append_to_jsonl(mock_task_workspace):
    """Test that multiple progress updates append to JSONL file"""
    task_id, workspace, registry = mock_task_workspace

    # Add agent
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        reg = json.load(f)

    agent_id = "multi-progress-agent"
    agent = {"id": agent_id, "type": "builder", "status": "running", "progress": 0}
    reg['agents'].append(agent)

    with open(registry_path, 'w') as f:
        json.dump(reg, f)

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.get_comprehensive_task_status') as mock_comprehensive:
        mock_comprehensive.return_value = {"success": True, "task_id": task_id}

        # Make multiple progress updates
        for i in range(3):
            real_mcp_server.update_agent_progress.fn(
                task_id=task_id,
                agent_id=agent_id,
                status="working",
                message=f"Progress update {i}",
                progress=i * 30
            )

    # Verify all entries are in JSONL
    progress_file = os.path.join(workspace, 'progress', f'{agent_id}_progress.jsonl')
    with open(progress_file, 'r') as f:
        lines = f.readlines()
        assert len(lines) == 3
        for i, line in enumerate(lines):
            entry = json.loads(line)
            assert entry["progress"] == i * 30


def test_report_agent_finding_multiple_types(mock_task_workspace):
    """Test reporting findings of different types"""
    task_id, workspace, registry = mock_task_workspace

    agent_id = "multi-finding-agent"
    finding_types = ["issue", "solution", "insight", "recommendation"]
    severities = ["low", "medium", "high", "critical"]

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.get_comprehensive_task_status') as mock_comprehensive:
        mock_comprehensive.return_value = {"success": True, "task_id": task_id}

        for ftype, severity in zip(finding_types, severities):
            result = real_mcp_server.report_agent_finding.fn(
                task_id=task_id,
                agent_id=agent_id,
                finding_type=ftype,
                severity=severity,
                message=f"Test {ftype} finding"
            )
            assert result["success"] is True

    # Verify all findings logged
    findings_file = os.path.join(workspace, 'findings', f'{agent_id}_findings.jsonl')
    with open(findings_file, 'r') as f:
        lines = f.readlines()
        assert len(lines) == 4


def test_get_real_task_status_empty_workspace(mock_task_workspace):
    """Test getting status when no progress or findings exist"""
    task_id, workspace, registry = mock_task_workspace

    # Don't create any progress or findings files

    with patch('real_mcp_server.find_task_workspace', return_value=workspace), \
         patch('real_mcp_server.check_tmux_session_exists', return_value=True):
        result = real_mcp_server.get_real_task_status.fn(task_id=task_id)

    assert result["success"] is True
    assert result["enhanced_progress"]["total_progress_entries"] == 0
    assert result["enhanced_progress"]["total_findings"] == 0


@patch('real_mcp_server.check_tmux_available', return_value=True)
@patch('real_mcp_server.subprocess.run')
@patch('real_mcp_server.detect_project_context')
def test_deploy_agent_with_special_characters_in_prompt(mock_detect_context, mock_subprocess, mock_tmux_check, mock_task_workspace):
    """Test deploying agent with special characters in prompt"""
    task_id, workspace, registry = mock_task_workspace

    mock_subprocess.return_value = MagicMock(returncode=0)
    mock_detect_context.return_value = get_mock_project_context()

    special_prompt = "Test with 'quotes', \"double quotes\", and $special {chars}"

    with patch('real_mcp_server.find_task_workspace', return_value=workspace):
        result = real_mcp_server.deploy_headless_agent.fn(
            task_id=task_id,
            agent_type="tester",
            prompt=special_prompt
        )

    # Should handle special characters without errors
    assert result["success"] is True
