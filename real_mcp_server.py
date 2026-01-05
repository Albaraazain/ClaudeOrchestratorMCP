#!/usr/bin/env python3
"""
Claude Orchestrator MCP Server

A Model Context Protocol (MCP) server for managing headless Claude agent orchestration
with tmux-based background execution and comprehensive progress tracking.

Author: Claude Code Orchestrator Project
License: MIT
"""

from fastmcp import FastMCP
from typing import Dict, List, Optional, Any
import json
import os
import subprocess
import uuid
import time
import logging
from datetime import datetime
from pathlib import Path
import sys
import re
import shutil
import fcntl
import errno
import threading

# =============================================================================
# ORCHESTRATOR MODULE IMPORTS (consolidated from modular architecture)
# =============================================================================

# Registry operations
from orchestrator.registry import (
    LockedRegistryFile,
    AGENT_TERMINAL_STATUSES,
    AGENT_ACTIVE_STATUSES,
    atomic_add_agent,
    atomic_update_agent_status,
    atomic_increment_counts,
    atomic_decrement_active_count,
    atomic_mark_agents_completed,
    get_global_registry_path,
    read_registry_with_lock,
    write_registry_with_lock,
    ensure_global_registry,
    check_phase_completion,
    # Registry health functions
    registry_health_check,
    generate_health_recommendations,
    validate_and_repair_registry,
)

# Workspace management
from orchestrator.workspace import (
    WORKSPACE_BASE,
    DEFAULT_MAX_CONCURRENT,
    find_task_workspace,
    get_workspace_base_from_task_workspace,
    ensure_workspace,
    check_disk_space,
    test_write_access,
    resolve_workspace_variables,
)

# Global SQLite registry for cross-project discovery
from orchestrator import global_registry

# Project context detection
from orchestrator.context import (
    detect_project_context,
    format_project_context_prompt,
)

# Prompt generation
from orchestrator.prompts import (
    generate_specialization_recommendations,
    format_task_enrichment_prompt,
    create_orchestration_guidance_prompt,
    get_type_specific_requirements,
)

# Deployment functions
from orchestrator.deployment import (
    check_tmux_available,
    create_tmux_session,
    get_tmux_session_output,
    check_tmux_session_exists,
    kill_tmux_session,
    list_all_tmux_sessions,
    find_existing_agent,
    verify_agent_id_unique,
    generate_unique_agent_id,
)

# Task management
from orchestrator.tasks import (
    TaskValidationError,
    TaskValidationWarning,
    validate_task_parameters,
    calculate_task_complexity,
    extract_text_from_message_content,
    truncate_conversation_history,
)

# Status and output processing
from orchestrator.status import (
    read_jsonl_lines,
    tail_jsonl_efficient,
    filter_lines_regex,
    parse_jsonl_lines,
    format_output_by_type,
    collect_log_metadata,
    detect_repetitive_content,
    extract_critical_lines,
    intelligent_sample_lines,
    summarize_output,
    smart_preview_truncate,
    line_based_truncate,
    simple_truncate,
    truncate_coordination_info,
    detect_and_truncate_binary,
    is_already_truncated,
    truncate_json_structure,
    safe_json_truncate,
    # Compact formatting
    format_line_compact,
    format_lines_compact,
    # Truncation limits
    MAX_LINE_LENGTH,
    MAX_TOOL_RESULT_CONTENT,
    AGGRESSIVE_LINE_LENGTH,
    AGGRESSIVE_TOOL_RESULT,
)

# Lifecycle management
from orchestrator.lifecycle import (
    cleanup_agent_resources,
    get_minimal_coordination_info,
    get_comprehensive_coordination_info,
    validate_agent_completion,
)

# SQLite materialized state (JSONL remains source of truth)
import orchestrator.state_db as state_db

# Health monitoring daemon
from orchestrator.health_daemon import (
    get_health_daemon,
    register_task_for_monitoring,
    unregister_task_from_monitoring,
    stop_health_daemon
)

# Initialize MCP server
mcp = FastMCP("Claude Orchestrator")

# Project context detection cache
_project_context_cache: Dict[str, Dict[str, Any]] = {}

# Additional configuration (not in orchestrator module)
DEFAULT_MAX_AGENTS = int(os.getenv('CLAUDE_ORCHESTRATOR_MAX_AGENTS', '45'))
DEFAULT_MAX_DEPTH = int(os.getenv('CLAUDE_ORCHESTRATOR_MAX_DEPTH', '5'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# NOTES ON MODULAR ARCHITECTURE
# ============================================================================
# All core functionality has been extracted to orchestrator/ modules:
# - orchestrator.registry: LockedRegistryFile, atomic_*, read/write_registry_with_lock
# - orchestrator.workspace: find_task_workspace, ensure_workspace, resolve_workspace_variables
# - orchestrator.deployment: tmux functions, agent ID generation
# - orchestrator.tasks: TaskValidationError, TaskValidationWarning, validate_task_parameters
# - orchestrator.status: JSONL parsing, truncation utilities
# - orchestrator.lifecycle: cleanup_agent_resources, validate_agent_completion
# - orchestrator.context: detect_project_context, format_project_context_prompt
# - orchestrator.prompts: get_type_specific_requirements, format_task_enrichment_prompt
#
# This file (real_mcp_server.py) now serves as a thin MCP interface layer that:
# 1. Imports functions from orchestrator modules
# 2. Defines @mcp.tool() decorated endpoints
# 3. Wires up the MCP tools to module implementations
# ============================================================================


# ============================================================================
# TMUX SESSION MANAGEMENT
# ============================================================================

# NOTE: check_tmux_available, create_tmux_session, get_tmux_session_output,
# check_tmux_session_exists, kill_tmux_session, list_all_tmux_sessions
# are now imported from orchestrator.deployment module



# ============================================================================
# FUNCTIONS MOVED TO MODULES (2026-01-02 Refactoring)
# ============================================================================
# The following functions were extracted to orchestrator/ modules:
# - generate_specialization_recommendations -> orchestrator/prompts.py
# - parse_markdown_context -> orchestrator/context.py
# - detect_project_context -> orchestrator/context.py
# - format_project_context_prompt -> orchestrator/context.py
# - format_task_enrichment_prompt -> orchestrator/prompts.py
# - create_orchestration_guidance_prompt -> orchestrator/prompts.py
# - get_investigator/builder/fixer_requirements -> orchestrator/prompts.py
# - get_universal_protocol -> orchestrator/prompts.py
# - get_type_specific_requirements -> orchestrator/prompts.py
# - resolve_workspace_variables -> orchestrator/workspace.py
# All are now imported at the top of this file from orchestrator modules.
# ============================================================================




# ============================================================================
@mcp.tool
def create_real_task(
    description: str,
    priority: str = "P2",
    phases: Optional[List[Dict[str, Any]]] = None,
    client_cwd: str = None,
    background_context: Optional[str] = None,
    expected_deliverables: Optional[List[str]] = None,
    success_criteria: Optional[List[str]] = None,
    constraints: Optional[List[str]] = None,
    relevant_files: Optional[List[str]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """
    Create an orchestration task with mandatory phases.

    IMPORTANT: Phases are MANDATORY. The orchestrator must think and plan phases
    upfront. No auto-defaults are created - if phases are not provided, the task
    creation will fail with PHASES_REQUIRED error.

    Phase State Machine (8 states):
        PENDING -> ACTIVE -> AWAITING_REVIEW -> UNDER_REVIEW -> APPROVED
                                             -> REJECTED -> REVISING -> ACTIVE
                                             -> ESCALATED

    Args:
        description: Description of the task
        priority: Task priority (P0-P4)
        phases: REQUIRED - List of phase definitions. Each phase needs 'name', optional 'description'.
        client_cwd: IMPORTANT - The client's working directory where agents should run.
                    Pass the current project path so agents operate in the correct location.
                    If not provided, agents may run in the wrong directory.
        background_context: Optional background information
        expected_deliverables: Optional list of expected deliverables
        success_criteria: Optional list of success criteria
        constraints: Optional list of constraints
        relevant_files: Optional list of relevant file paths
        conversation_history: Optional conversation context

    Example phases:
        [
            {"name": "Investigation", "description": "Research the codebase"},
            {"name": "Implementation", "description": "Write the code"},
            {"name": "Testing", "description": "Verify everything works"}
        ]

    Returns:
        Task creation result with phases, validation warnings, and enhancement flags
    """
    # Debug log incoming parameters to help diagnose cross-project issues
    logger.info(f"create_real_task called: description={description[:50]}..., phases={len(phases) if phases else 0}, client_cwd={client_cwd}")

    try:
        ensure_workspace()

        # Use client's working directory if provided, otherwise use server's WORKSPACE_BASE
        if client_cwd:
            # Resolve template variables (e.g., ${workspaceFolder} -> actual path)
            client_cwd = resolve_workspace_variables(client_cwd)
            workspace_base = os.path.join(client_cwd, '.agent-workspace')
            logger.info(f"Using client workspace: {workspace_base}")
        else:
            workspace_base = resolve_workspace_variables(WORKSPACE_BASE)
            logger.info(f"Using server workspace: {workspace_base}")

        # Ensure client workspace directory exists
        os.makedirs(workspace_base, exist_ok=True)
    except Exception as e:
        logger.error(f"create_real_task workspace setup failed: {e}")
        return {
            "success": False,
            "error": f"Workspace setup failed: {str(e)}",
            "hint": "Check if client_cwd is a valid path and you have write permissions"
        }

    # Ensure global registry exists in this workspace
    ensure_global_registry(workspace_base)

    # Validate and process enhancement parameters
    validation_warnings = []
    has_enhanced_context = False
    task_context = {}

    # Validate background_context
    if background_context is not None:
        if not isinstance(background_context, str):
            validation_warnings.append("background_context must be a string, ignoring invalid value")
        elif len(background_context.strip()) == 0:
            validation_warnings.append("background_context is empty, ignoring")
        else:
            task_context['background_context'] = background_context.strip()
            has_enhanced_context = True

    # Validate expected_deliverables
    if expected_deliverables is not None:
        if not isinstance(expected_deliverables, list):
            validation_warnings.append("expected_deliverables must be a list, ignoring invalid value")
        elif len(expected_deliverables) == 0:
            validation_warnings.append("expected_deliverables is empty, ignoring")
        elif not all(isinstance(d, str) and len(d.strip()) > 0 for d in expected_deliverables):
            validation_warnings.append("expected_deliverables contains invalid items (must be non-empty strings), filtering")
            valid_deliverables = [d.strip() for d in expected_deliverables if isinstance(d, str) and len(d.strip()) > 0]
            if valid_deliverables:
                task_context['expected_deliverables'] = valid_deliverables
                has_enhanced_context = True
        else:
            task_context['expected_deliverables'] = [d.strip() for d in expected_deliverables]
            has_enhanced_context = True

    # Validate success_criteria
    if success_criteria is not None:
        if not isinstance(success_criteria, list):
            validation_warnings.append("success_criteria must be a list, ignoring invalid value")
        elif len(success_criteria) == 0:
            validation_warnings.append("success_criteria is empty, ignoring")
        elif not all(isinstance(c, str) and len(c.strip()) > 0 for c in success_criteria):
            validation_warnings.append("success_criteria contains invalid items (must be non-empty strings), filtering")
            valid_criteria = [c.strip() for c in success_criteria if isinstance(c, str) and len(c.strip()) > 0]
            if valid_criteria:
                task_context['success_criteria'] = valid_criteria
                has_enhanced_context = True
        else:
            task_context['success_criteria'] = [c.strip() for c in success_criteria]
            has_enhanced_context = True

    # Validate constraints
    if constraints is not None:
        if not isinstance(constraints, list):
            validation_warnings.append("constraints must be a list, ignoring invalid value")
        elif len(constraints) == 0:
            validation_warnings.append("constraints is empty, ignoring")
        elif not all(isinstance(c, str) and len(c.strip()) > 0 for c in constraints):
            validation_warnings.append("constraints contains invalid items (must be non-empty strings), filtering")
            valid_constraints = [c.strip() for c in constraints if isinstance(c, str) and len(c.strip()) > 0]
            if valid_constraints:
                task_context['constraints'] = valid_constraints
                has_enhanced_context = True
        else:
            task_context['constraints'] = [c.strip() for c in constraints]
            has_enhanced_context = True

    # Validate relevant_files
    if relevant_files is not None:
        if not isinstance(relevant_files, list):
            validation_warnings.append("relevant_files must be a list, ignoring invalid value")
        elif len(relevant_files) == 0:
            validation_warnings.append("relevant_files is empty, ignoring")
        elif not all(isinstance(f, str) and len(f.strip()) > 0 for f in relevant_files):
            validation_warnings.append("relevant_files contains invalid items (must be non-empty strings), filtering")
            valid_files = [f.strip() for f in relevant_files if isinstance(f, str) and len(f.strip()) > 0]
            if valid_files:
                task_context['relevant_files'] = valid_files
                has_enhanced_context = True
        else:
            task_context['relevant_files'] = [f.strip() for f in relevant_files]
            has_enhanced_context = True

    # Validate and process conversation_history
    if conversation_history is not None:
        if not isinstance(conversation_history, list):
            validation_warnings.append("conversation_history must be a list, ignoring invalid value")
        elif len(conversation_history) == 0:
            validation_warnings.append("conversation_history is empty, ignoring")
        else:
            # Validate each message structure
            validated_messages = []
            for i, msg in enumerate(conversation_history):
                if not isinstance(msg, dict):
                    validation_warnings.append(f"conversation_history[{i}] must be a dict, skipping")
                    continue

                if 'role' not in msg or 'content' not in msg:
                    validation_warnings.append(f"conversation_history[{i}] missing required fields (role, content), skipping")
                    continue

                role = str(msg['role']).strip().lower()
                if role not in ['user', 'assistant', 'orchestrator']:
                    validation_warnings.append(f"conversation_history[{i}] has invalid role '{role}', skipping")
                    continue

                content = str(msg['content']).strip()
                if not content:
                    validation_warnings.append(f"conversation_history[{i}] has empty content, skipping")
                    continue

                # Auto-generate timestamp if missing
                timestamp = msg.get('timestamp', datetime.now().isoformat())

                validated_messages.append({
                    'role': role,
                    'content': content,
                    'timestamp': timestamp
                })

            if validated_messages:
                # Apply intelligent truncation
                truncated_history = truncate_conversation_history(validated_messages)
                task_context['conversation_history'] = truncated_history
                has_enhanced_context = True
            else:
                validation_warnings.append("All conversation_history messages were invalid, ignoring")

    # Generate task ID
    task_id = f"TASK-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    workspace = f"{workspace_base}/{task_id}"
    
    # Create task workspace
    os.makedirs(f"{workspace}/progress", exist_ok=True)
    os.makedirs(f"{workspace}/logs", exist_ok=True)
    os.makedirs(f"{workspace}/findings", exist_ok=True)
    os.makedirs(f"{workspace}/output", exist_ok=True)
    os.makedirs(f"{workspace}/handovers", exist_ok=True)

    # Process phases - MANDATORY: Phases must be explicitly defined
    # The orchestrator MUST think and plan phases upfront - no auto-defaults allowed
    if not phases or len(phases) == 0:
        return {
            "success": False,
            "error": "PHASES_REQUIRED: You must define phases for this task.",
            "hint": "Break down your task into logical phases (e.g., Investigation, Implementation, Testing). "
                    "Each phase should have a 'name' and optional 'description'. "
                    "For scoped reviews, add 'deliverables' and 'success_criteria' arrays per phase.",
            "example": [
                {
                    "name": "Phase 1: Investigation",
                    "description": "Research and understand the problem",
                    "deliverables": ["Analysis report", "Architecture diagram"],
                    "success_criteria": ["All components identified", "Dependencies mapped"]
                },
                {
                    "name": "Phase 2: Implementation",
                    "description": "Write the code",
                    "deliverables": ["Core module implemented", "Unit tests written"],
                    "success_criteria": ["All functions working", "Tests passing"]
                },
                {
                    "name": "Phase 3: Verification",
                    "description": "Test and verify the solution",
                    "deliverables": ["Integration tests", "Documentation"],
                    "success_criteria": ["All tests pass", "No regressions"]
                }
            ]
        }
    else:
        # Validate and enrich provided phases
        enriched_phases = []
        for i, phase in enumerate(phases):
            if not isinstance(phase, dict):
                return {"success": False, "error": f"Phase {i+1} must be a dictionary"}
            if not phase.get('name'):
                return {"success": False, "error": f"Phase {i+1} missing required 'name' field"}

            # Accept per-phase deliverables and success_criteria for scoped reviewer context
            phase_deliverables = phase.get('deliverables', [])
            phase_success_criteria = phase.get('success_criteria', [])

            # Validate they are lists if provided
            if phase_deliverables and not isinstance(phase_deliverables, list):
                return {"success": False, "error": f"Phase {i+1} deliverables must be a list"}
            if phase_success_criteria and not isinstance(phase_success_criteria, list):
                return {"success": False, "error": f"Phase {i+1} success_criteria must be a list"}

            enriched_phases.append({
                "id": f"phase-{uuid.uuid4().hex[:8]}",
                "order": i + 1,
                "name": phase.get('name'),
                "description": phase.get('description', ''),
                "deliverables": phase_deliverables,
                "success_criteria": phase_success_criteria,
                "status": "ACTIVE" if i == 0 else "PENDING",
                "created_at": datetime.now().isoformat(),
                "started_at": datetime.now().isoformat() if i == 0 else None
            })

    # Create task registry
    registry = {
        "task_id": task_id,
        "task_description": description,
        "created_at": datetime.now().isoformat(),
        "workspace": workspace,
        "workspace_base": workspace_base,
        "client_cwd": client_cwd,
        "status": "INITIALIZED",
        "priority": priority,
        "phases": enriched_phases,
        "current_phase_index": 0,
        "agents": [],
        "agent_hierarchy": {"orchestrator": []},
        "max_agents": DEFAULT_MAX_AGENTS,
        "max_depth": DEFAULT_MAX_DEPTH,
        "max_concurrent": DEFAULT_MAX_CONCURRENT,
        "total_spawned": 0,
        "active_count": 0,
        "completed_count": 0,
        "reviews": [],
        "orchestration_guidance": {
            "min_specialization_depth": 2,  # Encourage at least 2 layers (practical minimum)
            "recommended_child_agents_per_parent": 3,  # Each parent should spawn ~3 children (manageable)
            "specialization_domains": [],  # Dynamic list of identified domains
            "complexity_score": calculate_task_complexity(description)
        },
        "spiral_checks": {
            "enabled": True,
            "last_check": datetime.now().isoformat(),
            "violations": 0
        }
    }

    # Add task_context to registry only if enhancement fields provided
    if has_enhanced_context:
        registry['task_context'] = task_context

    with open(f"{workspace}/AGENT_REGISTRY.json", 'w') as f:
        json.dump(registry, f, indent=2)

    # MIGRATION FIX: Immediately sync task to SQLite after creating registry
    try:
        state_db.reconcile_task_workspace(workspace)
        logger.info(f"Task {task_id} synced to state_db")
    except Exception as e:
        logger.warning(f"Failed to sync task {task_id} to state_db: {e}")

    # Register in global SQLite registry for cross-project discovery
    # This replaces the buggy JSON-based cross-project registration
    try:
        global_registry.register_task(
            task_id=task_id,
            workspace_base=workspace_base,
            description=description,
            status="INITIALIZED",
            priority=priority
        )
        logger.info(f"Task {task_id} registered in global SQLite registry")
    except Exception as e:
        logger.warning(f"Failed to register task in global registry: {e}")

    # Update global registry (in the same workspace_base where task was created)
    global_reg_path = get_global_registry_path(workspace_base)
    with open(global_reg_path, 'r') as f:
        global_reg = json.load(f)
    
    # MIGRATION FIX: Don't increment counts - derive from SQLite
    # These counts are never decremented causing stale accumulation
    # global_reg['total_tasks'] += 1
    # global_reg['active_tasks'] += 1
    global_reg['tasks'][task_id] = {
        'description': description,
        'created_at': datetime.now().isoformat(),
        'status': 'INITIALIZED',
        'has_enhanced_context': has_enhanced_context
    }

    # Add counts for quick reference if enhanced context present
    if has_enhanced_context:
        global_reg['tasks'][task_id]['deliverables_count'] = len(task_context.get('expected_deliverables', []))
        global_reg['tasks'][task_id]['success_criteria_count'] = len(task_context.get('success_criteria', []))
    
    # Store workspace location for cross-project discovery
    global_reg['tasks'][task_id]['workspace'] = workspace
    global_reg['tasks'][task_id]['workspace_base'] = workspace_base
    
    with open(global_reg_path, 'w') as f:
        json.dump(global_reg, f, indent=2)
    
    # If task was created in a non-default workspace (client_cwd), 
    # ALSO register it in the default WORKSPACE_BASE global registry for cross-project discovery
    if client_cwd and workspace_base != resolve_workspace_variables(WORKSPACE_BASE):
        try:
            default_workspace_base = resolve_workspace_variables(WORKSPACE_BASE)
            ensure_global_registry(default_workspace_base)
            default_global_reg_path = get_global_registry_path(default_workspace_base)
            
            with open(default_global_reg_path, 'r') as f:
                default_global_reg = json.load(f)
            
            # Add task reference with workspace location
            if task_id not in default_global_reg.get('tasks', {}):
                default_global_reg.setdefault('tasks', {})[task_id] = {
                    'description': description,
                    'created_at': datetime.now().isoformat(),
                    'status': 'INITIALIZED',
                    'has_enhanced_context': has_enhanced_context,
                    'workspace': workspace,  # Store actual workspace location
                    'workspace_base': workspace_base,
                    'client_cwd': client_cwd,  # Store client_cwd for reference
                    'cross_project_reference': True  # Flag this as a reference from another workspace
                }
                
                if has_enhanced_context:
                    default_global_reg['tasks'][task_id]['deliverables_count'] = len(task_context.get('expected_deliverables', []))
                    default_global_reg['tasks'][task_id]['success_criteria_count'] = len(task_context.get('success_criteria', []))
                
                with open(default_global_reg_path, 'w') as f:
                    json.dump(default_global_reg, f, indent=2)
                
                logger.info(f"Registered task {task_id} in default global registry for cross-project discovery")
        except Exception as e:
            logger.warning(f"Failed to register task in default global registry: {e}")
            # Non-fatal - task is still properly registered in its own workspace
    
    # Build return value with phases and enhanced context info
    first_phase_name = enriched_phases[0]['name'] if enriched_phases else "Phase 1"
    result = {
        "success": True,
        "task_id": task_id,
        "description": description,
        "priority": priority,
        "workspace": workspace,
        "status": "INITIALIZED",
        "phases_count": len(enriched_phases),
        "current_phase": first_phase_name,
        "phases": [{"name": p['name'], "status": p['status']} for p in enriched_phases],
        "has_enhanced_context": has_enhanced_context,
        # GUIDANCE: Tell orchestrator what to do next
        "guidance": {
            "current_state": "task_initialized",
            "next_action": f"Deploy agents for '{first_phase_name}' phase using deploy_opus_agent/deploy_sonnet_agent",
            "available_actions": [
                f"deploy_opus_agent/deploy_sonnet_agent - Deploy agents to work on '{first_phase_name}'",
                "get_real_task_status - Check full task details",
                "get_phase_status - View current phase state"
            ],
            "warnings": validation_warnings if validation_warnings else None,
            "blocked_reason": None,
            "context": {
                "first_phase": first_phase_name,
                "total_phases": len(enriched_phases),
                "workspace": workspace
            }
        }
    }

    # Include validation warnings if any
    if validation_warnings:
        result['validation_warnings'] = validation_warnings

    # Include task_context fields in response if provided
    if has_enhanced_context:
        for key, value in task_context.items():
            result[key] = value

    # Register task for health monitoring
    try:
        register_task_for_monitoring(task_id, workspace_base)
        logger.info(f"Registered task {task_id} for health monitoring")
    except Exception as e:
        logger.warning(f"Failed to register task {task_id} for health monitoring: {e}")
        # Non-critical - continue without health monitoring

    return result

@mcp.tool
def deploy_opus_agent(
    task_id: str,
    agent_type: str,
    prompt: str,
    parent: str = "orchestrator",
    phase_index: Optional[int] = None
) -> Dict[str, Any]:
    """
    Deploy a Claude OPUS agent for COMPLEX tasks requiring deep reasoning.

    USE OPUS FOR:
    - Complex reasoning and architecture decisions
    - Security analysis and vulnerability assessment
    - Difficult bugs requiring multi-step debugging
    - UI implementation with design considerations
    - Critical code review and quality gates
    - Multi-step planning and coordination
    - Tasks requiring judgment and decision-making

    Args:
        task_id: Task ID to deploy agent for
        agent_type: Type of agent (investigator, fixer, architect, etc.)
        prompt: Instructions for the agent
        parent: Parent agent ID
        phase_index: Phase index (auto-set to current phase if None)

    Returns:
        Agent deployment result
    """
    return deploy_claude_tmux_agent(task_id, agent_type, prompt, parent, phase_index, "claude-opus-4-5")


@mcp.tool
def deploy_sonnet_agent(
    task_id: str,
    agent_type: str,
    prompt: str,
    parent: str = "orchestrator",
    phase_index: Optional[int] = None
) -> Dict[str, Any]:
    """
    Deploy a Claude SONNET agent for MODERATE tasks requiring speed and efficiency.

    USE SONNET FOR:
    - Codebase research and exploration
    - File searches and pattern matching
    - Documentation reading and summarization
    - Simple bug fixes with clear solutions
    - Data gathering and validation
    - Straightforward implementations
    - Test execution and verification
    - Web searches and information retrieval

    Args:
        task_id: Task ID to deploy agent for
        agent_type: Type of agent (researcher, validator, tester, etc.)
        prompt: Instructions for the agent
        parent: Parent agent ID
        phase_index: Phase index (auto-set to current phase if None)

    Returns:
        Agent deployment result
    """
    return deploy_claude_tmux_agent(task_id, agent_type, prompt, parent, phase_index, "claude-sonnet-4-5")


def deploy_claude_tmux_agent(
    task_id: str,
    agent_type: str,
    prompt: str,
    parent: str = "orchestrator",
    phase_index: Optional[int] = None,
    model: str = "claude-opus-4-5"
) -> Dict[str, Any]:
    """
    Deploy a headless Claude agent using tmux for background execution.

    Original deployment method using tmux sessions and claude CLI.

    Args:
        task_id: Task ID to deploy agent for
        agent_type: Type of agent (investigator, fixer, etc.)
        prompt: Instructions for the agent
        parent: Parent agent ID
        phase_index: Phase index this agent belongs to (auto-set from registry if None)
        model: Claude model to use - "claude-opus-4-5" (default) or "claude-sonnet-4-5" (faster, cheaper)

    Returns:
        Agent deployment result
    """
    # Validate model parameter - use explicit 4.5 model names
    valid_models = ["claude-opus-4-5", "claude-sonnet-4-5"]
    if model not in valid_models:
        logger.warning(f"Invalid model '{model}', defaulting to 'claude-opus-4-5'. Valid: {valid_models}")
        model = "claude-opus-4-5"
    if not check_tmux_available():
        logger.error("tmux not available for agent deployment")
        return {
            "success": False,
            "error": "tmux is not available - required for background execution"
        }
    
    # Find the task workspace (may be in client or server location)
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
    
    registry_path = f"{workspace}/AGENT_REGISTRY.json"

    # CRITICAL: Consolidate ALL registry operations under a single lock to prevent race conditions
    # This prevents concurrent agent deployments from corrupting registry counts
    try:
        with LockedRegistryFile(registry_path) as (registry, registry_file):
            # DEFENSIVE: Recalculate active_count from actual agent statuses to auto-heal inconsistencies
            # This fixes cases where agents complete without proper decrement (e.g., reviewer bug fixed above)
            active_statuses = ['running', 'working', 'blocked']
            actual_active = sum(1 for a in registry.get('agents', []) if a.get('status') in active_statuses)
            if registry.get('active_count', 0) != actual_active:
                logger.warning(f"ACTIVE_COUNT_HEAL: Correcting active_count from {registry.get('active_count')} to {actual_active} (actual)")
                registry['active_count'] = actual_active

            # Anti-spiral checks
            if registry['active_count'] >= registry['max_concurrent']:
                return {
                    "success": False,
                    "error": f"Too many active agents ({registry['active_count']}/{registry['max_concurrent']})"
                }

            if registry['total_spawned'] >= registry['max_agents']:
                return {
                    "success": False,
                    "error": f"Max agents reached ({registry['total_spawned']}/{registry['max_agents']})"
                }

            # Check for duplicate agents (deduplication)
            existing_agent = find_existing_agent(task_id, agent_type, registry)
            if existing_agent:
                logger.warning(f"Agent type '{agent_type}' already exists for task {task_id}: {existing_agent['id']}")
                return {
                    "success": False,
                    "error": f"Agent of type '{agent_type}' already running for this task",
                    "existing_agent_id": existing_agent['id'],
                    "existing_agent_status": existing_agent['status'],
                    "note": "Use the existing agent or wait for it to complete before spawning a new one"
                }

            # Load global registry for unique ID verification (separate lock)
            workspace_base = get_workspace_base_from_task_workspace(workspace)
            global_reg_path = get_global_registry_path(workspace_base)

            try:
                with LockedRegistryFile(global_reg_path) as (global_registry, global_file):
                    # Generate unique agent ID with collision detection
                    try:
                        agent_id = generate_unique_agent_id(agent_type, registry, global_registry)
                    except RuntimeError as e:
                        logger.error(f"Failed to generate unique agent ID: {e}")
                        return {
                            "success": False,
                            "error": str(e)
                        }

                    # Keep global registry loaded for later update
                    global_registry_snapshot = dict(global_registry)
            except TimeoutError as e:
                logger.error(f"Timeout acquiring global registry lock: {e}")
                return {
                    "success": False,
                    "error": "Global registry locked - too many concurrent deployments"
                }

            session_name = f"agent_{agent_id}"

            # Calculate agent depth based on parent (using already-loaded registry)
            depth = 1 if parent == "orchestrator" else 2
            if parent != "orchestrator":
                for agent in registry['agents']:
                    if agent['id'] == parent:
                        depth = agent.get('depth', 1) + 1
                        break

            # Get task description for orchestration guidance (using already-loaded registry)
            task_description = registry.get('task_description', '')
            max_depth = registry.get('max_depth', 5)

            # AUTO-SET phase_index if not provided - ensures all agents tagged to current phase
            if phase_index is None:
                phase_index = registry.get('current_phase_index', 0)
                logger.info(f"Auto-assigning agent {agent_id} to phase {phase_index}")

            # Store registry reference for later use (still within lock)
            task_registry = registry

    except TimeoutError as e:
        logger.error(f"Timeout acquiring registry lock for deployment: {e}")
        return {
            "success": False,
            "error": "Registry locked - too many concurrent deployments"
        }

    orchestration_prompt = create_orchestration_guidance_prompt(agent_type, task_description, depth, max_depth)

    # Build task enrichment context from registry
    try:
        enrichment_prompt = format_task_enrichment_prompt(task_registry)
    except Exception as e:
        logger.error(f"Error in format_task_enrichment_prompt: {e}")
        logger.error(f"task_registry keys: {task_registry.keys()}")
        if 'task_context' in task_registry:
            logger.error(f"task_context keys: {task_registry['task_context'].keys()}")
            for key, value in task_registry['task_context'].items():
                logger.error(f"  {key}: type={type(value)}, value={str(value)[:100]}")
        raise

    # Detect project context from CLIENT's project directory (not MCP server's cwd)
    client_project_dir = task_registry.get('client_cwd')
    if client_project_dir:
        logger.info(f"Agent {agent_id} working dir from registry client_cwd: {client_project_dir}")
    else:
        # Fallback: extract from workspace path if client_cwd not stored
        # workspace = "/path/to/client/project/.agent-workspace/TASK-xxx"
        # client_project_dir = "/path/to/client/project"
        workspace_parent = os.path.dirname(workspace)
        if workspace_parent.endswith('.agent-workspace'):
            client_project_dir = os.path.dirname(workspace_parent)
            logger.info(f"Agent {agent_id} working dir extracted from workspace path: {client_project_dir}")
        else:
            # Workspace is in server's WORKSPACE_BASE, use that as fallback
            # WARNING: This means agents will run in MCP server's directory, not client's
            client_project_dir = os.getcwd()
            logger.warning(f"WORKING_DIR_FALLBACK: Agent {agent_id} using MCP server cwd '{client_project_dir}' - "
                          f"client_cwd was not stored in registry. Agents may run in wrong directory!")

    project_context = detect_project_context(client_project_dir)
    context_prompt = format_project_context_prompt(project_context)

    # Get type-specific requirements for this agent type
    type_requirements = get_type_specific_requirements(agent_type)

    # Create comprehensive agent prompt with MCP self-reporting capabilities
    agent_prompt = f"""You are a headless Claude agent in an orchestrator system.

🤖 AGENT IDENTITY:
- Agent ID: {agent_id}
- Agent Type: {agent_type}
- Task ID: {task_id}
- Parent Agent: {parent}
- Depth Level: {depth}
- Workspace: {workspace}

📝 YOUR MISSION:
{prompt}
{enrichment_prompt}
{context_prompt}

{type_requirements}

{orchestration_prompt}

🔗 MCP SELF-REPORTING WITH COORDINATION - You MUST use these MCP functions to report progress:

1. PROGRESS UPDATES (every few minutes):
```
mcp__claude-orchestrator__update_agent_progress
Parameters: 
- task_id: "{task_id}"
- agent_id: "{agent_id}"  
- status: "working" | "blocked" | "completed" | "error"
- message: "Description of current work"
- progress: 0-100 (percentage)

RETURNS: Your update confirmation + comprehensive status of ALL agents for coordination!
- coordination_info.agents: Status of all other agents
- coordination_info.coordination_data.recent_progress: Latest progress from all agents
- coordination_info.coordination_data.recent_findings: Latest discoveries from all agents
```

2. REPORT FINDINGS (whenever you discover something important):
```
mcp__claude-orchestrator__report_agent_finding
Parameters:
- task_id: "{task_id}"
- agent_id: "{agent_id}"
- finding_type: "issue" | "solution" | "insight" | "recommendation"
- severity: "low" | "medium" | "high" | "critical"  
- message: "What you discovered"
- data: {{"any": "additional info"}}

RETURNS: Your finding confirmation + comprehensive status of ALL agents for coordination!
- coordination_info.agents: Status of all other agents
- coordination_info.coordination_data.recent_progress: Latest progress from all agents
- coordination_info.coordination_data.recent_findings: Latest discoveries from all agents
```

💡 COORDINATION ADVANTAGE: Every time you update progress or report a finding, you'll receive:
- Complete status of all other agents working on this task
- Their latest progress updates and discoveries
- Opportunity to coordinate and avoid duplicate work
- Insights to build upon others' findings

3. SPAWN CHILD AGENTS (if you need specialized help):
```
mcp__claude-orchestrator__spawn_opus_child_agent or spawn_sonnet_child_agent
Parameters:
- task_id: "{task_id}"
- parent_agent_id: "{agent_id}"
- child_agent_type: "investigator" | "builder" | "fixer" | etc
- child_prompt: "Specific task for the child agent"
```

🚨 CRITICAL PROTOCOL:
1. START by calling update_agent_progress with status="working", progress=0
2. REGULARLY update progress every few minutes
3. REPORT key findings as you discover them
4. SPAWN child agents if you need specialized help
5. END by calling update_agent_progress with status="completed", progress=100

⚠️ REPORTING REQUIREMENTS:
- Update progress EVERY 3-5 minutes minimum
- Progress must be REALISTIC and match actual work done
- Completion requires EVIDENCE: files modified, tests passed, findings documented
- If you don't report for 5+ minutes, you'll be flagged as stalled
- BEFORE claiming done: perform self-review and list what could be improved

🚫 DO NOT USE THESE TOOLS (they waste tokens and return nothing useful):
- get_agent_output - This is for ORCHESTRATOR monitoring only, not agent coordination
- Peer agent logs are NOT accessible to you - use findings/progress instead

You are working independently but can coordinate through the MCP orchestrator system.

═══════════════════════════════════════════════════════════════════════════════
⚡ MANDATORY COMPLETION STEP - YOUR WORK IS NOT FINISHED UNTIL YOU DO THIS ⚡
═══════════════════════════════════════════════════════════════════════════════

Before you stop working, you MUST call:

```
mcp__claude-orchestrator__update_agent_progress(
    task_id="{task_id}",
    agent_id="{agent_id}",
    status="completed",
    message="<SUMMARY: List what you accomplished and any key findings>",
    progress=100
)
```

IF YOU DO NOT CALL THIS:
- The system will think you are still working
- The phase CANNOT proceed to review
- Other agents will wait indefinitely for you
- The orchestrator will be stuck

COMPLETE YOUR WORK AND REPORT STATUS!
═══════════════════════════════════════════════════════════════════════════════

BEGIN YOUR WORK NOW!
"""

    # Resource tracking variables for cleanup on failure
    prompt_file_created = None
    tmux_session_created = None
    registry_updated = False
    global_registry_updated = False

    try:
        # Pre-flight checks before deployment
        import shutil

        # Check disk space (minimum 100MB required)
        try:
            disk_stat = shutil.disk_usage(workspace)
            free_mb = disk_stat.free / (1024 * 1024)
            if free_mb < 100:
                logger.error(f"Insufficient disk space: {free_mb:.1f}MB available (need 100MB)")
                return {
                    "success": False,
                    "error": f"Insufficient disk space: {free_mb:.1f}MB available, need at least 100MB"
                }
        except Exception as e:
            logger.warning(f"Could not check disk space: {e}")

        # Create logs directory and test write access
        logs_dir = f"{workspace}/logs"
        try:
            os.makedirs(logs_dir, exist_ok=True)
            # Test write access
            test_file = f"{logs_dir}/.write_test_{uuid.uuid4().hex[:8]}"
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
        except Exception as e:
            logger.error(f"Workspace logs directory not writable: {e}")
            return {
                "success": False,
                "error": f"Workspace logs directory not writable: {e}. Check permissions or mount status."
            }

        # Store agent prompt in file for tmux execution with absolute path
        prompt_file = os.path.abspath(f"{workspace}/agent_prompt_{agent_id}.txt")
        with open(prompt_file, 'w') as f:
            f.write(agent_prompt)
        prompt_file_created = prompt_file  # Track for cleanup on failure

        # Run Claude in the CLIENT's project directory, not the MCP server's cwd
        # client_project_dir was extracted earlier from task_registry.get('client_cwd') or workspace path
        calling_project_dir = client_project_dir
        claude_executable = os.getenv('CLAUDE_EXECUTABLE', 'npx -y @anthropic-ai/claude-code')
        # Build claude flags with dynamic model selection (opus=best reasoning, sonnet=faster/cheaper)
        base_flags = '--print --output-format stream-json --verbose --dangerously-skip-permissions'
        claude_flags = f'{base_flags} --model {model}'
        logger.info(f"Deploying agent {agent_id} with model: {model}")

        # JSONL log file path - unique per agent_id
        log_file = f"{logs_dir}/{agent_id}_stream.jsonl"

        # Escape the prompt for shell and pass as argument (not stdin redirection)
        escaped_prompt = agent_prompt.replace("'", "'\"'\"'")
        # Add tee pipe to capture Claude stream-json output to persistent log
        claude_command = f"cd '{calling_project_dir}' && {claude_executable} {claude_flags} '{escaped_prompt}' | tee '{log_file}'"
        
        # Create the session in the calling project directory
        session_result = create_tmux_session(
            session_name=session_name,
            command=claude_command,
            working_dir=calling_project_dir
        )

        if not session_result["success"]:
            return {
                "success": False,
                "error": f"Failed to create agent session: {session_result['error']}"
            }

        tmux_session_created = session_name  # Track for cleanup on failure

        # Give Claude a moment to start
        time.sleep(2)

        # Check if session is still running
        if not check_tmux_session_exists(session_name):
            # Clean up orphaned prompt file since tmux session failed
            if prompt_file_created and os.path.exists(prompt_file_created):
                try:
                    os.remove(prompt_file_created)
                    logger.info(f"Cleaned up orphaned prompt file: {prompt_file_created}")
                except Exception as cleanup_err:
                    logger.error(f"Failed to remove orphaned prompt file: {cleanup_err}")

            return {
                "success": False,
                "error": "Agent session terminated immediately after creation"
            }
        
        # CRITICAL: Atomically update BOTH registries to prevent race conditions
        # This ensures agent deployment is all-or-nothing
        agent_data = {
            "id": agent_id,
            "type": agent_type,
            "model": model,  # Track which model this agent uses (opus/sonnet)
            "tmux_session": session_name,
            "parent": parent,
            "depth": depth,  # Use the calculated depth
            "phase_index": phase_index,  # PHASE ENFORCEMENT: Tag agent to phase for auto-completion tracking
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "progress": 0,
            "last_update": datetime.now().isoformat(),
            "prompt": prompt[:200] + "..." if len(prompt) > 200 else prompt,
            "tracked_files": {
                "prompt_file": prompt_file,
                "log_file": log_file,
                "progress_file": f"{workspace}/progress/{agent_id}_progress.jsonl",
                "findings_file": f"{workspace}/findings/{agent_id}_findings.jsonl",
                "deploy_log": f"{workspace}/logs/deploy_{agent_id}.json"
            }
        }

        # Update local registry with atomic locking
        try:
            with LockedRegistryFile(registry_path) as (registry, f):
                registry['agents'].append(agent_data)
                registry['total_spawned'] += 1
                registry['active_count'] += 1

                # Update hierarchy
                if parent not in registry['agent_hierarchy']:
                    registry['agent_hierarchy'][parent] = []
                registry['agent_hierarchy'][parent].append(agent_id)

                # LIFECYCLE: Transition task to ACTIVE on first agent deployment
                if registry['active_count'] == 1:  # This is the first active agent
                    try:
                        workspace_base = get_workspace_base_from_task_workspace(workspace)
                        if state_db.transition_task_to_active(workspace_base=workspace_base, task_id=task_id):
                            logger.info(f"[LIFECYCLE] Task {task_id} transitioned to ACTIVE on first agent deployment")
                            registry['status'] = 'ACTIVE'  # Update registry status to match
                    except Exception as e:
                        logger.warning(f"[LIFECYCLE] Failed to transition task to ACTIVE: {e}")

                # Write atomically
                f.seek(0)
                f.write(json.dumps(registry, indent=2))
                f.truncate()
                registry_updated = True  # Track for cleanup awareness
        except TimeoutError as e:
            logger.error(f"Timeout acquiring registry lock for update: {e}")
            # Clean up tmux session since deployment failed
            if tmux_session_created:
                try:
                    subprocess.run(['tmux', 'kill-session', '-t', session_name],
                                 capture_output=True, timeout=5)
                    logger.info(f"Killed orphaned tmux session after lock timeout: {session_name}")
                except Exception:
                    pass
            return {
                "success": False,
                "error": "Registry locked - deployment failed"
            }

        # Update global registry with atomic locking
        workspace_base = get_workspace_base_from_task_workspace(workspace)
        global_reg_path = get_global_registry_path(workspace_base)

        try:
            with LockedRegistryFile(global_reg_path) as (global_reg, f):
                # MIGRATION FIX: Don't increment counts - derive from SQLite
                # global_reg['total_agents_spawned'] += 1
                # global_reg['active_agents'] += 1
                global_reg['agents'][agent_id] = {
                    'task_id': task_id,
                    'type': agent_type,
                    'parent': parent,
                    'status': 'running',  # Initial status - CRITICAL for cleanup detection
                    'started_at': datetime.now().isoformat(),
                    'tmux_session': session_name
                }

                # MIGRATION FIX: Don't write global registry - state_db is source of truth
                # f.seek(0)
                # f.write(json.dumps(global_reg, indent=2))
                # f.truncate()
                global_registry_updated = True  # Track for cleanup awareness
        except TimeoutError as e:
            logger.error(f"Timeout acquiring global registry lock: {e}")
            # Rollback local registry since global failed
            try:
                with LockedRegistryFile(registry_path) as (registry, f):
                    # Remove the agent we just added
                    registry['agents'] = [a for a in registry['agents'] if a['id'] != agent_id]
                    registry['total_spawned'] -= 1
                    registry['active_count'] -= 1
                    if parent in registry['agent_hierarchy']:
                        registry['agent_hierarchy'][parent].remove(agent_id)

                    f.seek(0)
                    f.write(json.dumps(registry, indent=2))
                    f.truncate()
                    logger.info(f"Rolled back local registry after global registry lock timeout")
            except Exception as rollback_err:
                logger.error(f"Failed to rollback local registry: {rollback_err}")

            # Clean up tmux session
            if tmux_session_created:
                try:
                    subprocess.run(['tmux', 'kill-session', '-t', session_name],
                                 capture_output=True, timeout=5)
                    logger.info(f"Killed orphaned tmux session after global lock timeout: {session_name}")
                except Exception:
                    pass

            return {
                "success": False,
                "error": "Global registry locked - deployment failed and rolled back"
            }

        # Log successful deployment
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": "agent_deployed",
            "agent_id": agent_id,
            "model": model,
            "tmux_session": session_name,
            "command": claude_command[:100] + "...",
            "success": True,
            "session_creation": session_result
        }
        
        with open(f"{workspace}/logs/deploy_{agent_id}.json", 'w') as f:
            json.dump(log_entry, f, indent=2)

        # MIGRATION FIX: Sync agent to SQLite after deployment
        try:
            state_db.reconcile_task_workspace(workspace)
            logger.info(f"Agent {agent_id} synced to state_db")
        except Exception as e:
            logger.warning(f"Failed to sync agent {agent_id} to state_db: {e}")

        return {
            "success": True,
            "agent_id": agent_id,
            "tmux_session": session_name,
            "type": agent_type,
            "model": model,  # Model used for this agent (opus/sonnet)
            "parent": parent,
            "task_id": task_id,
            "status": "deployed",
            "workspace": workspace,
            "deployment_method": "tmux session",
            # GUIDANCE: Tell orchestrator what to do next
            "guidance": {
                "current_state": "agent_deployed",
                "next_action": f"Monitor agent progress using get_agent_output or deploy more agents",
                "available_actions": [
                    f"get_agent_output - Monitor agent {agent_id}",
                    "deploy_opus_agent/deploy_sonnet_agent - Deploy additional agents",
                    "check_phase_progress - Check if phase is ready for review",
                    "get_real_task_status - View all agents status"
                ],
                "warnings": None,
                "blocked_reason": None,
                "context": {
                    "agent_id": agent_id,
                    "agent_type": agent_type,
                    "model": model,
                    "tmux_session": session_name
                }
            }
        }

    except Exception as e:
        logger.error(f"Agent deployment failed: {e}")
        logger.error(f"Cleaning up orphaned resources...")

        # Clean up tmux session if it was created
        if tmux_session_created:
            try:
                subprocess.run(['tmux', 'kill-session', '-t', tmux_session_created],
                             capture_output=True, timeout=5)
                logger.info(f"Killed orphaned tmux session: {tmux_session_created}")
            except Exception as cleanup_err:
                logger.error(f"Failed to kill tmux session: {cleanup_err}")

        # Remove orphaned prompt file
        if prompt_file_created and os.path.exists(prompt_file_created):
            try:
                os.remove(prompt_file_created)
                logger.info(f"Removed orphaned prompt file: {prompt_file_created}")
            except Exception as cleanup_err:
                logger.error(f"Failed to remove prompt file: {cleanup_err}")

        # Rollback registry changes (THIS WILL BE IMPROVED BY file_locking_implementer)
        # For now, log that registry may be corrupted
        if registry_updated or global_registry_updated:
            logger.error(f"Registry was partially updated before failure - may need manual cleanup")

        return {
            "success": False,
            "error": f"Failed to deploy agent: {str(e)}",
            "cleanup_performed": True,
            "resources_cleaned": {
                "tmux_session": tmux_session_created,
                "prompt_file": prompt_file_created
            }
        }


@mcp.tool
def get_real_task_status(task_id: str) -> Dict[str, Any]:
    """
    Get detailed status of a real task and its agents.
    
    Args:
        task_id: Task ID to query
    
    Returns:
        Complete task status
    """
    # Find the task workspace (may be in client or server location)
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
    
    registry_path = f"{workspace}/AGENT_REGISTRY.json"

    # CRITICAL: Use LockedRegistryFile to prevent race conditions
    # Multiple status checks can run concurrently - without locking, we get:
    # - Lost updates (active_count decremented multiple times for same agent)
    # - Corrupted counters (read-modify-write races)
    agents_completed = []

    # IMPORTANT: Check ALL active statuses, not just 'running'
    # Agents change to 'working' when they start, so we must check all active states
    active_statuses_to_check = {'running', 'working', 'blocked'}

    try:
        with LockedRegistryFile(registry_path) as (registry, f):
            # Update agent statuses based on tmux sessions
            for agent in registry['agents']:
                agent_status = agent.get('status', '')
                # Check if agent is in an active status AND has a tmux session
                if agent_status in active_statuses_to_check and 'tmux_session' in agent:
                    # Check if tmux session still exists
                    if not check_tmux_session_exists(agent['tmux_session']):
                        agent['status'] = 'completed'
                        agent['completed_at'] = datetime.now().isoformat()
                        agent['completion_reason'] = 'tmux_session_terminated'
                        registry['active_count'] = max(0, registry['active_count'] - 1)
                        registry['completed_count'] = registry.get('completed_count', 0) + 1
                        agents_completed.append(agent['id'])
                        logger.info(f"Detected agent {agent['id']} completed (tmux session terminated, was {agent_status})")

            # Write back atomically while still holding lock
            f.seek(0)
            f.write(json.dumps(registry, indent=2))
            f.truncate()
    except TimeoutError as e:
        logger.error(f"Timeout acquiring lock on task registry: {e}")
        return {"success": False, "error": "Registry locked by another process"}
    except FileNotFoundError:
        return {"success": False, "error": f"Registry file not found: {registry_path}"}

    # Update global registry for agents that completed (also with locking)
    if agents_completed:
        try:
            workspace_base = get_workspace_base_from_task_workspace(workspace)
            global_reg_path = get_global_registry_path(workspace_base)
            if os.path.exists(global_reg_path):
                with LockedRegistryFile(global_reg_path) as (global_reg, gf):
                    for agent_id in agents_completed:
                        if agent_id in global_reg.get('agents', {}):
                            global_reg['agents'][agent_id]['status'] = 'completed'
                            global_reg['agents'][agent_id]['completed_at'] = datetime.now().isoformat()
                            global_reg['active_agents'] = max(0, global_reg.get('active_agents', 0) - 1)

                    gf.seek(0)
                    gf.write(json.dumps(global_reg, indent=2))
                    gf.truncate()

                logger.info(f"Global registry updated: {len(agents_completed)} agents completed, active agents: {global_reg['active_agents']}")
        except Exception as e:
            logger.error(f"Failed to update global registry for completed agents: {e}")
    
    # Enhanced progress tracking - read JSONL files  
    progress_entries = []
    findings_entries = []
    
    # Read all progress JSONL files
    progress_dir = f"{workspace}/progress"
    if os.path.exists(progress_dir):
        for file in os.listdir(progress_dir):
            if file.endswith('_progress.jsonl'):
                try:
                    with open(f"{progress_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    progress = json.loads(line)
                                    progress_entries.append(progress)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Read all findings JSONL files
    findings_dir = f"{workspace}/findings"
    if os.path.exists(findings_dir):
        for file in os.listdir(findings_dir):
            if file.endswith('_findings.jsonl'):
                try:
                    with open(f"{findings_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    finding = json.loads(line)
                                    findings_entries.append(finding)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Sort by timestamp
    progress_entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    findings_entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    # Add phase tracking info
    phases = registry.get('phases', [])
    current_phase_index = registry.get('current_phase_index', 0)
    current_phase = phases[current_phase_index] if current_phase_index < len(phases) else None

    # Check phase completion status
    phase_completion = None
    if current_phase:
        phase_id = current_phase.get('id')
        phase_agents = [a for a in registry.get('agents', []) if a.get('phase_id') == phase_id]
        completed_agents = [a for a in phase_agents if a.get('status') in AGENT_TERMINAL_STATUSES]
        pending_agents = [a.get('id') for a in phase_agents if a.get('status') not in AGENT_TERMINAL_STATUSES]

        all_complete = len(phase_agents) > 0 and len(completed_agents) == len(phase_agents)
        phase_completion = {
            "all_agents_done": all_complete,
            "total_agents": len(phase_agents),
            "completed_agents": len(completed_agents),
            "pending_agents": pending_agents,
            "ready_for_review": all_complete and current_phase.get('status') == 'ACTIVE'
        }

    # Generate contextual guidance based on current state
    phase_status = current_phase.get('status') if current_phase else 'UNKNOWN'
    phase_name = current_phase.get('name') if current_phase else 'Unknown'
    active_count = registry.get('active_count', 0)

    # Determine guidance based on phase status and agent states
    if phase_status == 'ACTIVE':
        if active_count > 0:
            guidance = {
                "current_state": "phase_active_agents_working",
                "next_action": f"Wait for {active_count} agents to complete or monitor with get_agent_output",
                "available_actions": [
                    "get_agent_output - Monitor specific agent logs",
                    "check_phase_progress - Check if ready for review",
                    "deploy_opus_agent/deploy_sonnet_agent - Add more agents if needed"
                ],
                "warnings": None,
                "blocked_reason": None
            }
        elif phase_completion and phase_completion.get('all_agents_done'):
            guidance = {
                "current_state": "phase_active_all_done",
                "next_action": "Phase will auto-submit for review. Use check_phase_progress to verify.",
                "available_actions": [
                    "check_phase_progress - Verify phase completion",
                    "get_phase_status - View phase details"
                ],
                "warnings": None,
                "blocked_reason": None
            }
        else:
            guidance = {
                "current_state": "phase_active_no_agents",
                "next_action": f"Deploy agents for '{phase_name}' phase using deploy_opus_agent/deploy_sonnet_agent",
                "available_actions": [
                    "deploy_opus_agent/deploy_sonnet_agent - Deploy phase agents",
                    "get_phase_status - View phase requirements"
                ],
                "warnings": None,
                "blocked_reason": None
            }
    elif phase_status == 'AWAITING_REVIEW':
        guidance = {
            "current_state": "phase_awaiting_review",
            "next_action": "Reviewers will be auto-spawned. Wait for UNDER_REVIEW status.",
            "available_actions": [
                "get_phase_status - Check review status",
                "trigger_agentic_review - Manually trigger if not started"
            ],
            "warnings": None,
            "blocked_reason": None
        }
    elif phase_status == 'UNDER_REVIEW':
        guidance = {
            "current_state": "phase_under_review",
            "next_action": "Wait for reviewer verdicts. Check progress with get_review_status.",
            "available_actions": [
                "get_review_status - Check reviewer verdicts",
                "get_agent_output - Monitor reviewer agents",
                "abort_stalled_review - Abort if reviewers stalled"
            ],
            "warnings": None,
            "blocked_reason": None
        }
    elif phase_status == 'APPROVED':
        next_phase = phases[current_phase_index + 1] if current_phase_index + 1 < len(phases) else None
        if next_phase:
            guidance = {
                "current_state": "phase_approved_has_next",
                "next_action": f"Advance to '{next_phase.get('name')}' using advance_to_next_phase",
                "available_actions": [
                    "advance_to_next_phase - Move to next phase",
                    "get_phase_handover - Review phase handover"
                ],
                "warnings": None,
                "blocked_reason": None
            }
        else:
            guidance = {
                "current_state": "task_complete",
                "next_action": "All phases completed. Task is finished.",
                "available_actions": [
                    "get_phase_handover - Review final deliverables"
                ],
                "warnings": None,
                "blocked_reason": None
            }
    elif phase_status == 'REJECTED':
        guidance = {
            "current_state": "phase_rejected",
            "next_action": "Review rejection reasons and deploy fix agents",
            "available_actions": [
                "get_review_status - View rejection feedback",
                "deploy_opus_agent/deploy_sonnet_agent - Deploy agents to fix issues"
            ],
            "warnings": ["Phase was rejected by reviewers"],
            "blocked_reason": "Review rejected - fixes required before re-submission"
        }
    elif phase_status == 'REVISING':
        guidance = {
            "current_state": "phase_revising",
            "next_action": "Deploy agents to fix issues, then phase will auto-resubmit",
            "available_actions": [
                "deploy_opus_agent/deploy_sonnet_agent - Deploy fix agents",
                "get_review_status - View required fixes"
            ],
            "warnings": None,
            "blocked_reason": None
        }
    elif phase_status == 'ESCALATED':
        guidance = {
            "current_state": "phase_escalated",
            "next_action": "Manual intervention required - all reviewers failed",
            "available_actions": [
                "approve_phase_review(force_escalated=True) - Force approval",
                "trigger_agentic_review - Retry with new reviewers"
            ],
            "warnings": ["All reviewers crashed without submitting verdicts"],
            "blocked_reason": "Escalated - manual decision required"
        }
    else:
        guidance = {
            "current_state": f"phase_{phase_status.lower()}",
            "next_action": "Check phase status for details",
            "available_actions": [
                "get_phase_status - View current phase state"
            ],
            "warnings": None,
            "blocked_reason": None
        }

    return {
        "success": True,
        "task_id": task_id,
        "description": registry.get('task_description'),
        "status": registry.get('status'),
        "workspace": workspace,
        "phases": {
            "total": len(phases),
            "current_index": current_phase_index,
            "current_phase": current_phase.get('name') if current_phase else None,
            "current_status": current_phase.get('status') if current_phase else None,
            "completion": phase_completion,
            "all_phases": [{"name": p.get('name'), "status": p.get('status')} for p in phases]
        },
        "agents": {
            "total_spawned": registry.get('total_spawned', 0),
            "active": registry.get('active_count', 0),
            "completed": registry.get('completed_count', 0),
            "agents_list": registry.get('agents', [])
        },
        "hierarchy": registry.get('agent_hierarchy', {}),
        "enhanced_progress": {
            "recent_updates": progress_entries[:10],  # Last 10 progress updates
            "recent_findings": findings_entries[:5],   # Last 5 findings
            "total_progress_entries": len(progress_entries),
            "total_findings": len(findings_entries),
            "progress_frequency": len(progress_entries) / max((registry.get('total_spawned', 1) * 10), 1)  # Updates per agent per 10-min window
        },
        "spiral_status": registry.get('spiral_checks', {}),
        "limits": {
            "max_agents": registry.get('max_agents', 10),
            "max_concurrent": registry.get('max_concurrent', 5),
            "max_depth": registry.get('max_depth', 3)
        },
        # GUIDANCE: Tell orchestrator what to do next
        "guidance": guidance
    }

@mcp.tool
def get_agent_output(
    task_id: str,
    agent_id: str,
    tail: Optional[int] = None,
    filter: Optional[str] = None,
    format: str = "text",
    include_metadata: bool = False,
    max_bytes: Optional[int] = None,
    aggressive_truncate: bool = False,
    response_format: str = "full",
    recent_lines: Optional[int] = None
) -> Dict[str, Any]:
    """
    Get agent's recent activity in compact human-readable format.

    USE THIS TO MONITOR WHAT AN AGENT IS DOING:
    - See recent tool calls: [TOOL] Bash: npm run dev
    - See results: [RESULT] Server running on port 5173
    - See progress: [MCP] update_agent_progress: working - 85%
    - See errors: [ERROR] Exit code 1

    RECOMMENDED: Use response_format="recent" (default) for efficient monitoring.
    Returns last 20 lines in compact format (~99% smaller than raw logs).

    Example output:
        [TOOL] Bash: npm install
        [RESULT] added 175 packages
        [MCP] update_agent_progress: working - Installing dependencies
        [ASST] Now let me create the project structure

    Args:
        task_id: Task ID containing the agent
        agent_id: Agent ID to get output from
        response_format: RECOMMENDED "recent" - compact human-readable format
                         - "recent": Last 20 lines, compact format (RECOMMENDED)
                         - "full": Full raw JSONL output (huge, avoid)
                         - "compact": Aggressive JSON truncation
                         - "summary": Only errors and key findings
        recent_lines: Override number of lines (default 20 for "recent" mode)
        format: Legacy - ignored for "recent" mode
        include_metadata: Include stats about log file
        tail: Legacy - use recent_lines instead
        filter: Regex pattern to filter output lines

    Returns:
        Dict with compact output and session status
    """
    # Validate format parameter
    if format not in ["text", "jsonl", "parsed"]:
        return {
            "success": False,
            "error": f"Invalid format '{format}'. Must be 'text', 'jsonl', or 'parsed'",
            "agent_id": agent_id
        }

    # Validate response_format parameter
    if response_format not in ["full", "summary", "compact", "recent"]:
        return {
            "success": False,
            "error": f"Invalid response_format '{response_format}'. Must be 'full', 'summary', 'compact', or 'recent'",
            "agent_id": agent_id
        }

    # Apply response_format overrides
    if response_format == "compact":
        aggressive_truncate = True
    elif response_format == "recent":
        # Use recent_lines mode with smart defaults
        if recent_lines is None:
            recent_lines = 20  # Default for "what's happening now" monitoring
        aggressive_truncate = True
    elif response_format == "summary":
        # Summary format will be handled later after reading lines
        pass

    # Determine truncation limits based on aggressive_truncate flag
    line_limit = AGGRESSIVE_LINE_LENGTH if aggressive_truncate else MAX_LINE_LENGTH
    tool_result_limit = AGGRESSIVE_TOOL_RESULT if aggressive_truncate else MAX_TOOL_RESULT_CONTENT

    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }

    # Load agent registry
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    try:
        with open(registry_path, 'r') as f:
            registry = json.load(f)
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read agent registry: {e}"
        }

    # Find agent in list
    agent = None
    for a in registry['agents']:
        if a['id'] == agent_id:
            agent = a
            break

    if not agent:
        return {
            "success": False,
            "error": f"Agent {agent_id} not found",
            "agent_id": agent_id
        }

    # Try reading from JSONL log file first
    log_path = f"{workspace}/logs/{agent_id}_stream.jsonl"
    source = "jsonl_log"
    session_status = "unknown"

    if os.path.exists(log_path):
        try:
            # Claude/tmux log handling
            # Determine how many lines to read
            # Priority: tail > recent_lines > all
            lines_to_read = tail if (tail and tail > 0) else recent_lines

            if lines_to_read and lines_to_read > 0:
                lines = tail_jsonl_efficient(log_path, lines_to_read)
            else:
                lines = read_jsonl_lines(log_path)

            # Store original line count before filtering
            original_lines = lines.copy()

            # Apply filter if specified
            if filter:
                lines, filter_error = filter_lines_regex(lines, filter)
                if filter_error:
                    return {
                        "success": False,
                        "error": filter_error,
                        "error_type": "invalid_regex",
                        "agent_id": agent_id
                    }

            # Handle summary format early (before truncation)
            if response_format == "summary":
                summary_output = summarize_output(lines)
                return {
                    "success": True,
                    "agent_id": agent_id,
                    "session_status": "unknown",  # Will be determined below if needed
                    "output": summary_output,
                    "source": source,
                    "format": "summary",
                    "metadata": {
                        "total_lines_analyzed": len(lines),
                        "response_format": "summary"
                    }
                }

            # Apply per-line truncation to prevent log bloat
            truncated_lines = []
            truncation_stats = {
                "lines_truncated": 0,
                "bytes_before": 0,
                "bytes_after": 0,
                "aggressive_mode": aggressive_truncate
            }

            for line in lines:
                original_size = len(line)
                truncation_stats["bytes_before"] += original_size

                if original_size > line_limit:
                    truncated_line = safe_json_truncate(line, line_limit)
                    truncated_lines.append(truncated_line)
                    truncation_stats["lines_truncated"] += 1
                    truncation_stats["bytes_after"] += len(truncated_line)
                else:
                    truncated_lines.append(line)
                    truncation_stats["bytes_after"] += original_size

            # Use truncated lines for output
            lines = truncated_lines

            # Apply intelligent sampling if max_bytes specified
            sampling_stats = None
            if max_bytes and max_bytes > 0:
                # Analyze content for repetition
                content_analysis = detect_repetitive_content(lines)

                # Apply intelligent sampling
                lines, sampling_stats = intelligent_sample_lines(lines, max_bytes, content_analysis)

                # Add analysis to truncation stats for metadata
                if sampling_stats and sampling_stats.get('sampled'):
                    truncation_stats['sampling_applied'] = True
                    truncation_stats['content_analysis'] = {
                        'has_repetition': content_analysis.get('has_repetition'),
                        'repetitive_tools': list(content_analysis.get('repetitive_tools', {}).keys())
                    }

            # Format output
            try:
                # For "recent" mode, use compact human-readable format
                if response_format == "recent":
                    output = format_lines_compact(lines)
                    parse_errors = []
                else:
                    output, parse_errors = format_output_by_type(lines, format)
            except ValueError as e:
                return {
                    "success": False,
                    "error": str(e),
                    "agent_id": agent_id
                }

            # Determine session status based on tmux
            if 'tmux_session' in agent:
                if check_tmux_session_exists(agent['tmux_session']):
                    session_status = "running"
                else:
                    session_status = "terminated"
            else:
                session_status = "completed"

            # Build response
            response = {
                "success": True,
                "agent_id": agent_id,
                "session_status": session_status,
                "output": output,
                "source": source
            }

            # Add metadata if requested
            if include_metadata:
                metadata = collect_log_metadata(
                    log_path,
                    original_lines,
                    lines,
                    parse_errors,
                    source
                )
                if filter:
                    metadata["filter_pattern"] = filter
                    metadata["matched_lines"] = len(lines)

                # Add truncation statistics
                if truncation_stats["lines_truncated"] > 0 or truncation_stats.get("aggressive_mode"):
                    bytes_saved = truncation_stats["bytes_before"] - truncation_stats["bytes_after"]
                    metadata["truncation_stats"] = {
                        "lines_truncated": truncation_stats["lines_truncated"],
                        "total_lines": len(original_lines),
                        "truncation_ratio": round(truncation_stats["lines_truncated"] / len(original_lines), 3) if len(original_lines) > 0 else 0,
                        "bytes_saved": bytes_saved,
                        "bytes_before": truncation_stats["bytes_before"],
                        "bytes_after": truncation_stats["bytes_after"],
                        "space_savings_percent": round((bytes_saved / truncation_stats["bytes_before"]) * 100, 1) if truncation_stats["bytes_before"] > 0 else 0,
                        "max_line_length": line_limit,
                        "max_tool_result_content": tool_result_limit,
                        "aggressive_mode": aggressive_truncate
                    }
                    # Add content analysis if sampling was applied
                    if truncation_stats.get("sampling_applied"):
                        metadata["truncation_stats"]["content_analysis"] = truncation_stats["content_analysis"]

                # Add sampling statistics if intelligent sampling was applied
                if sampling_stats and sampling_stats.get('sampled'):
                    metadata["sampling_stats"] = sampling_stats
                    metadata["max_bytes_limit"] = max_bytes

                # Add response format info
                metadata["response_format"] = response_format
                if aggressive_truncate:
                    metadata["aggressive_truncate"] = True

                response["metadata"] = metadata

            # Keep tmux_session field for backward compatibility
            if 'tmux_session' in agent:
                response["tmux_session"] = agent['tmux_session']

            return response

        except Exception as e:
            logger.warning(f"Error reading JSONL log {log_path}: {e}, falling back to tmux")
            # Fall through to tmux fallback

    # Fallback to tmux (backward compatibility)
    source = "tmux_session"

    if 'tmux_session' not in agent:
        return {
            "success": False,
            "error": f"Agent {agent_id} has no JSONL log and no tmux session",
            "agent_id": agent_id
        }

    session_name = agent['tmux_session']

    if not check_tmux_session_exists(session_name):
        return {
            "success": True,
            "agent_id": agent_id,
            "session_status": "terminated",
            "output": "" if format != "parsed" else [],
            "source": source,
            "tmux_session": session_name
        }

    # Get tmux output
    tmux_output = get_tmux_session_output(session_name)

    # Split into lines for processing
    lines = [line for line in tmux_output.split('\n') if line.strip()]

    # Apply filter if specified
    if filter:
        lines, filter_error = filter_lines_regex(lines, filter)
        if filter_error:
            return {
                "success": False,
                "error": filter_error,
                "error_type": "invalid_regex",
                "agent_id": agent_id
            }

    # Apply tail if specified
    if tail and tail > 0:
        lines = lines[-tail:]

    # Format output (tmux output is text, not JSONL)
    if format == "text" or format == "jsonl":
        output = '\n'.join(lines)
    elif format == "parsed":
        # Try to parse as JSONL, but don't fail if it's not
        parsed = []
        for line in lines:
            try:
                parsed.append(json.loads(line))
            except:
                # Not valid JSON, include as-is
                parsed.append({"text": line, "source": "tmux_unparsed"})
        output = parsed
    else:
        output = '\n'.join(lines)

    response = {
        "success": True,
        "agent_id": agent_id,
        "tmux_session": session_name,
        "session_status": "running",
        "output": output,
        "source": source
    }

    # Add metadata if requested
    if include_metadata:
        metadata = {
            "log_source": source,
            "total_lines": len(tmux_output.split('\n')),
            "returned_lines": len(lines)
        }
        if filter:
            metadata["filter_pattern"] = filter
            metadata["matched_lines"] = len(lines)
        response["metadata"] = metadata

    return response

@mcp.tool
def kill_real_agent(task_id: str, agent_id: str, reason: str = "Manual termination") -> Dict[str, Any]:
    """
    Terminate a running agent (tmux session).

    Args:
        task_id: Task containing the agent
        agent_id: Agent to terminate
        reason: Reason for termination

    Returns:
        Termination status
    """
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }

    # =========================================================================
    # SQLite-backed status path (JSONL is the source of truth)
    # =========================================================================
    # This avoids registry lock contention and eliminates drift from mutable counters.
    workspace_base = get_workspace_base_from_task_workspace(workspace)
    try:
        state_db.reconcile_task_workspace(workspace)
    except Exception as e:
        logger.warning(f"State DB reconcile failed for {task_id}: {e}")

    snapshot = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id) or {}
    phases = snapshot.get("phases", []) or []
    current_phase_index = int(snapshot.get("current_phase_index") or 0)
    current_phase = phases[current_phase_index] if current_phase_index < len(phases) else None
    phase_status = (current_phase or {}).get("status", "UNKNOWN")

    phase_state = state_db.load_phase_snapshot(
        workspace_base=workspace_base,
        task_id=task_id,
        phase_index=current_phase_index,
    )
    phase_completion = {
        "ready_for_review": bool(phase_state.get("counts", {}).get("all_done")) and phase_status == "ACTIVE",
        "pending_agents": int(phase_state.get("counts", {}).get("pending", 0)),
        "completed_agents": int(phase_state.get("counts", {}).get("completed", 0)),
        "failed_agents": int(phase_state.get("counts", {}).get("failed", 0)),
    }

    # Best-effort registry read for non-critical fields (hierarchy/spiral/limits).
    registry = {}
    try:
        with open(f"{workspace}/AGENT_REGISTRY.json", "r", encoding="utf-8", errors="ignore") as f:
            registry = json.load(f) or {}
    except Exception:
        registry = {}

    if phase_status == "ACTIVE":
        if int(phase_state.get("counts", {}).get("total", 0)) == 0:
            guidance = {
                "current_state": "phase_active_no_agents",
                "next_action": "No agents deployed. Use deploy_opus_agent/deploy_sonnet_agent to start work.",
                "available_actions": ["deploy_opus_agent/deploy_sonnet_agent - Deploy agents for current phase"],
                "warnings": None,
                "blocked_reason": None,
            }
        elif phase_completion["pending_agents"] > 0:
            guidance = {
                "current_state": "phase_active_working",
                "next_action": f"Wait for {phase_completion['pending_agents']} agents to complete",
                "available_actions": [
                    "get_agent_output - Monitor agent progress",
                    "check_phase_progress - Check if ready for review",
                ],
                "warnings": None,
                "blocked_reason": None,
            }
        else:
            guidance = {
                "current_state": "phase_active_ready_for_review",
                "next_action": "All agents terminal. System will auto-submit for review when registry lock is available.",
                "available_actions": [
                    "check_phase_progress - Verify phase completion",
                    "get_phase_status - View phase details",
                ],
                "warnings": None,
                "blocked_reason": None,
            }
    else:
        guidance = {
            "current_state": f"phase_{str(phase_status).lower()}",
            "next_action": "Check phase status for details",
            "available_actions": ["get_phase_status - View current phase state"],
            "warnings": None,
            "blocked_reason": None,
        }

    try:
        recent_updates = state_db.load_recent_progress_latest(
            workspace_base=workspace_base, task_id=task_id, limit=10
        )
    except Exception:
        recent_updates = []

    counts = snapshot.get("counts") or {}
    agents_list = snapshot.get("agents") or []
    total_spawned = max(int(registry.get("total_spawned", 0) or 0), int(counts.get("total", 0) or 0))

    return {
        "success": True,
        "task_id": task_id,
        "description": (snapshot.get("description") or registry.get("task_description") or ""),
        "status": (snapshot.get("status") or registry.get("status") or "INITIALIZED"),
        "workspace": workspace,
        "phases": {
            "total": len(phases),
            "current_index": current_phase_index,
            "current_phase": current_phase.get("name") if current_phase else None,
            "current_status": phase_status,
            "completion": phase_completion,
            "all_phases": [{"name": p.get("name"), "status": p.get("status")} for p in phases],
        },
        "agents": {
            "total_spawned": total_spawned,
            "active": int(counts.get("active", 0) or 0),
            "completed": int(counts.get("completed", 0) or 0),
            "agents_list": agents_list,
        },
        "hierarchy": registry.get("agent_hierarchy", {}) or {},
        "enhanced_progress": {
            "recent_updates": recent_updates,
            "total_progress_entries": len(recent_updates),
        },
        "spiral_status": registry.get("spiral_checks", {}) or {},
        "limits": {
            "max_agents": registry.get("max_agents", 45),
            "max_concurrent": registry.get("max_concurrent", DEFAULT_MAX_CONCURRENT),
            "max_depth": registry.get("max_depth", DEFAULT_MAX_DEPTH),
        },
        "guidance": guidance,
        "notes": {
            "source_of_truth": "JSONL",
            "materialized_state": "SQLite (WAL)",
            "registry_role": "best-effort metadata cache",
        },
    }

    registry_path = f"{workspace}/AGENT_REGISTRY.json"

    # Read registry with file locking to prevent race conditions
    registry = read_registry_with_lock(registry_path)

    # Find agent
    agent = None
    for a in registry['agents']:
        if a['id'] == agent_id:
            agent = a
            break

    if not agent:
        return {
            "success": False,
            "error": f"Agent {agent_id} not found"
        }

    try:
        # Kill tmux session
        session_name = agent.get('tmux_session')

        # Perform comprehensive resource cleanup using cleanup_agent_resources
        cleanup_result = cleanup_agent_resources(
            workspace=workspace,
            agent_id=agent_id,
            agent_data=agent,
            keep_logs=True  # Archive logs instead of deleting
        )

        # Track cleanup status
        killed = cleanup_result.get('tmux_session_killed', False)

        # Update registry
        previous_status = agent.get('status')
        agent['status'] = 'terminated'
        agent['terminated_at'] = datetime.now().isoformat()
        agent['termination_reason'] = reason

        # JSONL is the source of truth: append a terminal progress entry.
        try:
            progress_file = f"{workspace}/progress/{agent_id}_progress.jsonl"
            os.makedirs(f"{workspace}/progress", exist_ok=True)
            progress_entry = {
                "timestamp": agent["terminated_at"],
                "agent_id": agent_id,
                "status": "terminated",
                "message": f"Agent terminated: {reason}",
                "progress": int(agent.get("progress", 0) or 0),
            }
            with open(progress_file, "a", encoding="utf-8") as pf:
                pf.write(json.dumps(progress_entry) + "\n")
            # Materialize terminal status into SQLite for consistent reads.
            try:
                workspace_base = get_workspace_base_from_task_workspace(workspace)
                state_db.reconcile_task_workspace(workspace)
                state_db.record_progress(
                    workspace_base=workspace_base,
                    task_id=task_id,
                    agent_id=agent_id,
                    timestamp=progress_entry["timestamp"],
                    status=progress_entry["status"],
                    message=progress_entry["message"],
                    progress=progress_entry["progress"],
                )
            except Exception as e:
                logger.warning(f"State DB termination update failed for {task_id}/{agent_id}: {e}")
        except Exception as e:
            logger.warning(f"Failed to append termination progress entry for {agent_id}: {e}")
        
        # Only decrement if agent was in active status
        active_statuses = ['running', 'working', 'blocked']
        if previous_status in active_statuses:
            registry['active_count'] = max(0, registry['active_count'] - 1)

        # MIGRATION FIX: Use state_db instead of write_registry_with_lock
        # Mark agent as terminal in SQLite (this is the source of truth)
        try:
            workspace_base = get_workspace_base_from_task_workspace(workspace)
            state_db.mark_agent_terminal(
                workspace_base=workspace_base,
                agent_id=agent_id,
                status='terminated',
                reason=reason,
                auto_rollup=True  # Check if task should transition
            )
            # Note: We don't write to registry JSON anymore - SQLite is source of truth
            logger.info(f"Agent {agent_id} marked as terminated in state_db")
        except Exception as e:
            logger.error(f"Failed to mark agent terminal in state_db: {e}")
            # Fall back to registry write if state_db fails
            write_registry_with_lock(registry_path, registry)

        # MIGRATION FIX: Global registry is deprecated - state_db handles all state
        # The global registry update is no longer needed as state_db tracks all agents
        # Removing global registry update entirely
        logger.debug(f"Skipping global registry update - state_db is source of truth")
        
        return {
            "success": True,
            "agent_id": agent_id,
            "tmux_session": session_name,
            "session_killed": killed,
            "reason": reason,
            "status": "terminated",
            "cleanup": cleanup_result
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to terminate agent: {str(e)}"
        }

def cleanup_agent_resources(
    workspace: str,
    agent_id: str,
    agent_data: Dict[str, Any],
    keep_logs: bool = True,
    kill_tmux: bool = True
) -> Dict[str, Any]:
    """
    Clean up all resources associated with a completed/terminated agent.

    This function performs comprehensive cleanup of:
    - Tmux session (if still running)
    - JSONL log file handles (flush and close)
    - Temporary prompt files
    - Progress/findings JSONL files (archive or delete)
    - Verification of zombie processes

    Args:
        workspace: Task workspace path (e.g., .agent-workspace/TASK-xxx)
        agent_id: Agent ID to clean up
        agent_data: Agent registry data dictionary
        keep_logs: If True, archive logs to workspace/archive/. If False, delete them.

    Returns:
        Dict with cleanup results for each resource type:
        {
            "success": True/False,
            "tmux_session_killed": True/False,
            "prompt_file_deleted": True/False,
            "log_files_archived": True/False,
            "verified_no_zombies": True/False,
            "errors": [...],  # List of any errors encountered
            "archived_files": [...]  # List of archived file paths
        }
    """
    cleanup_results = {
        "success": True,
        "tmux_session_killed": False,
        "prompt_file_deleted": False,
        "log_files_archived": False,
        "verified_no_zombies": False,
        "errors": [],
        "archived_files": []
    }

    try:
        # 1. Kill tmux session if still running with retry mechanism (optional)
        session_name = agent_data.get('tmux_session')
        if session_name:
            if check_tmux_session_exists(session_name):
                if not kill_tmux:
                    cleanup_results["tmux_session_killed"] = False
                    cleanup_results["errors"].append(
                        f"Skipped tmux kill for {session_name} (kill_tmux=False)"
                    )
                    logger.info(f"Cleanup: Skipping tmux kill for {session_name} (kill_tmux=False)")
                else:
                    logger.info(f"Cleanup: Killing tmux session {session_name} for agent {agent_id}")
                    killed = kill_tmux_session(session_name)

                if kill_tmux and killed:
                    # Retry mechanism with escalating delays to ensure processes terminate
                    max_retries = 3
                    retry_delays = [0.5, 1.0, 2.0]  # Escalating delays in seconds
                    processes_terminated = False

                    for attempt in range(max_retries):
                        time.sleep(retry_delays[attempt])

                        # Check if processes still exist
                        try:
                            ps_result = subprocess.run(
                                ['ps', 'aux'],
                                capture_output=True,
                                text=True,
                                timeout=5
                            )

                            if ps_result.returncode == 0:
                                agent_processes = [
                                    line for line in ps_result.stdout.split('\n')
                                    if agent_id in line and 'claude' in line.lower()
                                ]

                                if len(agent_processes) == 0:
                                    processes_terminated = True
                                    cleanup_results["tmux_session_killed"] = True
                                    logger.info(f"Cleanup: Verified processes terminated for {agent_id} after {attempt + 1} attempt(s)")
                                    break
                                elif attempt < max_retries - 1:
                                    logger.warning(f"Cleanup: Found {len(agent_processes)} processes for {agent_id}, waiting (attempt {attempt + 1}/{max_retries})")
                                else:
                                    # Final attempt: escalate to SIGKILL for stubborn processes
                                    logger.error(f"Cleanup: Processes won't die gracefully, escalating to SIGKILL for {agent_id}")
                                    killed_count = 0
                                    for proc_line in agent_processes:
                                        try:
                                            # Extract PID (second column in ps aux output)
                                            pid = int(proc_line.split()[1])
                                            os.kill(pid, 9)  # SIGKILL
                                            killed_count += 1
                                            logger.info(f"Cleanup: Sent SIGKILL to process {pid}")
                                        except (ValueError, IndexError, ProcessLookupError, PermissionError) as e:
                                            logger.warning(f"Cleanup: Failed to kill process: {e}")

                                    if killed_count > 0:
                                        # Wait briefly after SIGKILL
                                        time.sleep(0.5)
                                        cleanup_results["tmux_session_killed"] = True
                                        cleanup_results["escalated_to_sigkill"] = True
                                        logger.warning(f"Cleanup: Escalated to SIGKILL for {killed_count} processes")
                            else:
                                logger.warning(f"Cleanup: ps command failed with return code {ps_result.returncode}")
                        except subprocess.TimeoutExpired:
                            logger.warning(f"Cleanup: ps command timed out during retry {attempt + 1}")
                        except Exception as e:
                            logger.warning(f"Cleanup: Error checking processes during retry {attempt + 1}: {e}")

                    if kill_tmux and not processes_terminated and not cleanup_results.get("escalated_to_sigkill"):
                        cleanup_results["tmux_session_killed"] = False
                        cleanup_results["errors"].append(f"Failed to verify process termination for {agent_id} after {max_retries} retries")
                elif kill_tmux:
                    cleanup_results["tmux_session_killed"] = False
                    cleanup_results["errors"].append(f"Failed to kill tmux session {session_name}")
            else:
                # Session already gone
                cleanup_results["tmux_session_killed"] = True
                logger.info(f"Cleanup: Tmux session {session_name} already terminated")

        # 2. Delete temporary prompt file (no longer needed after agent starts)
        prompt_file = os.path.abspath(f"{workspace}/agent_prompt_{agent_id}.txt")
        if os.path.exists(prompt_file):
            try:
                os.remove(prompt_file)
                cleanup_results["prompt_file_deleted"] = True
                logger.info(f"Cleanup: Deleted prompt file {prompt_file}")
            except Exception as e:
                error_msg = f"Failed to delete prompt file {prompt_file}: {e}"
                cleanup_results["errors"].append(error_msg)
                logger.warning(error_msg)
        else:
            # Prompt file already deleted or never existed
            cleanup_results["prompt_file_deleted"] = True

        # 3. Archive or delete JSONL log files
        logs_dir = f"{workspace}/logs"
        progress_dir = f"{workspace}/progress"
        findings_dir = f"{workspace}/findings"

        files_to_process = [
            (f"{logs_dir}/{agent_id}_stream.jsonl", "stream log"),
            (f"{progress_dir}/{agent_id}_progress.jsonl", "progress log"),
            (f"{findings_dir}/{agent_id}_findings.jsonl", "findings log")
        ]

        if keep_logs:
            # Archive logs to workspace/archive/ directory
            archive_dir = f"{workspace}/archive"
            try:
                os.makedirs(archive_dir, exist_ok=True)
                logger.info(f"Cleanup: Created archive directory {archive_dir}")
            except Exception as e:
                error_msg = f"Failed to create archive directory {archive_dir}: {e}"
                cleanup_results["errors"].append(error_msg)
                logger.error(error_msg)
                keep_logs = False  # Fall back to deletion if archiving fails

            if keep_logs:
                # CRITICAL FIX: Give time for any writing processes to finish and flush buffers
                # JSONL writers may have buffered data not yet written to disk
                # Without this sleep, shutil.move can cause data corruption or incomplete logs
                time.sleep(0.2)
                logger.info("Cleanup: Waited 200ms for file handles to flush before archiving")

                for src_path, file_type in files_to_process:
                    if os.path.exists(src_path):
                        dst_path = f"{archive_dir}/{os.path.basename(src_path)}"
                        try:
                            # Verify file is not currently being written to by checking size stability
                            initial_size = os.path.getsize(src_path)
                            time.sleep(0.05)  # Brief check
                            final_size = os.path.getsize(src_path)

                            if initial_size != final_size:
                                # File still being written, wait a bit more
                                logger.warning(f"Cleanup: {file_type} still being written, waiting...")
                                time.sleep(0.2)

                            import shutil
                            shutil.move(src_path, dst_path)
                            cleanup_results["archived_files"].append(dst_path)
                            logger.info(f"Cleanup: Archived {file_type} to {dst_path}")
                        except OSError as e:
                            # File locked, permission denied, or other OS-level issues
                            error_msg = f"OS error archiving {file_type} {src_path}: {e}"
                            cleanup_results["errors"].append(error_msg)
                            logger.warning(error_msg)
                        except Exception as e:
                            error_msg = f"Failed to archive {file_type} {src_path}: {e}"
                            cleanup_results["errors"].append(error_msg)
                            logger.warning(error_msg)

                # Mark successful if at least one file was archived
                cleanup_results["log_files_archived"] = len(cleanup_results["archived_files"]) > 0
        else:
            # Delete log files instead of archiving
            for src_path, file_type in files_to_process:
                if os.path.exists(src_path):
                    try:
                        os.remove(src_path)
                        logger.info(f"Cleanup: Deleted {file_type} {src_path}")
                    except Exception as e:
                        error_msg = f"Failed to delete {file_type} {src_path}: {e}"
                        cleanup_results["errors"].append(error_msg)
                        logger.warning(error_msg)

            cleanup_results["log_files_archived"] = True  # Deletion counts as "processed"

        # 4. Verify no zombie processes remain
        # Check for lingering Claude processes tied to this agent
        try:
            ps_result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if ps_result.returncode == 0:
                # Look for processes containing both agent_id and 'claude'
                agent_processes = [
                    line for line in ps_result.stdout.split('\n')
                    if agent_id in line and 'claude' in line.lower()
                ]

                if len(agent_processes) == 0:
                    cleanup_results["verified_no_zombies"] = True
                    logger.info(f"Cleanup: Verified no zombie processes for agent {agent_id}")
                else:
                    warning_msg = f"Found {len(agent_processes)} lingering processes for agent {agent_id}"
                    cleanup_results["errors"].append(warning_msg)
                    cleanup_results["zombie_processes"] = len(agent_processes)
                    cleanup_results["zombie_process_details"] = agent_processes[:3]  # First 3 for debugging
                    logger.warning(f"Cleanup: {warning_msg}")
            else:
                error_msg = f"ps command failed with return code {ps_result.returncode}"
                cleanup_results["errors"].append(error_msg)
                logger.warning(f"Cleanup: {error_msg}")
        except subprocess.TimeoutExpired:
            error_msg = "ps command timed out after 5 seconds"
            cleanup_results["errors"].append(error_msg)
            logger.warning(f"Cleanup: {error_msg}")
        except Exception as e:
            error_msg = f"Failed to verify zombie processes: {e}"
            cleanup_results["errors"].append(error_msg)
            logger.warning(f"Cleanup: {error_msg}")

        # 5. Determine overall success
        # Success if critical operations completed (tmux killed, files processed)
        critical_operations = [
            cleanup_results["tmux_session_killed"],
            cleanup_results["prompt_file_deleted"],
            cleanup_results["log_files_archived"]
        ]
        cleanup_results["success"] = all(critical_operations)

        if cleanup_results["success"]:
            logger.info(f"Cleanup: Successfully cleaned up all resources for agent {agent_id}")
        else:
            logger.warning(f"Cleanup: Partial cleanup for agent {agent_id}, errors: {cleanup_results['errors']}")

        return cleanup_results

    except Exception as e:
        # Catch-all for unexpected errors
        error_msg = f"Unexpected error during cleanup: {str(e)}"
        logger.error(f"Cleanup: {error_msg}")
        cleanup_results["success"] = False
        cleanup_results["errors"].append(error_msg)
        return cleanup_results

def get_enhanced_coordination_response(
    task_id: str,
    requesting_agent_id: str,
    detail_level: str = "standard"
) -> Dict[str, Any]:
    """
    Get enhanced coordination response using the new structured format.

    This provides agents with:
    - Formatted text response optimized for LLM parsing
    - Peer status and progress visibility
    - Conflict detection and recommendations
    - Relevance-scored findings

    Args:
        task_id: Task ID
        requesting_agent_id: ID of agent requesting coordination
        detail_level: "minimal", "standard", or "full"

    Returns:
        Dict with formatted_response (text) and raw_data (dict)
    """
    from orchestrator.coordination import build_coordination_response

    # Find workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found",
            "formatted_response": f"ERROR: Task {task_id} not found"
        }

    registry_path = f"{workspace}/AGENT_REGISTRY.json"

    try:
        # Read registry
        with open(registry_path, 'r') as f:
            registry = json.load(f)
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read registry: {e}",
            "formatted_response": f"ERROR: Failed to read task registry"
        }

    # Collect all findings
    all_findings = []
    findings_dir = f"{workspace}/findings"
    if os.path.exists(findings_dir):
        for file in os.listdir(findings_dir):
            if file.endswith('_findings.jsonl'):
                try:
                    with open(f"{findings_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    # Extract agent type from filename if not in entry
                                    if 'agent_type' not in entry:
                                        agent_id = file.replace('_findings.jsonl', '')
                                        for agent in registry.get('agents', []):
                                            if agent['id'] == agent_id:
                                                entry['agent_type'] = agent.get('type', 'unknown')
                                                break
                                    all_findings.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue

    # Collect all progress entries
    all_progress = []
    progress_dir = f"{workspace}/progress"
    if os.path.exists(progress_dir):
        for file in os.listdir(progress_dir):
            if file.endswith('_progress.jsonl'):
                try:
                    with open(f"{progress_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    all_progress.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue

    # Sort by timestamp
    all_findings.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    all_progress.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

    # Build the coordination response
    try:
        response = build_coordination_response(
            task_id=task_id,
            requesting_agent_id=requesting_agent_id,
            registry=registry,
            findings=all_findings,
            progress_entries=all_progress
        )

        # Format the text response
        formatted_text = response.format_text_response(detail_level)

        return {
            "success": True,
            "formatted_response": formatted_text,
            "raw_data": response.to_dict(),
            "response_size": len(formatted_text),
            "detail_level": detail_level
        }

    except Exception as e:
        logger.error(f"Failed to build coordination response: {e}")
        return {
            "success": False,
            "error": str(e),
            "formatted_response": f"ERROR: Failed to build coordination response - {str(e)}"
        }

def get_minimal_coordination_info(task_id: str) -> Dict[str, Any]:
    """
    Get minimal coordination info for MCP tool responses.
    Returns only essential data to prevent log bloat (1-2KB vs 35KB+).

    Returns:
    - success status
    - recent_findings (last 3 only)
    - agent_count summary

    Excludes:
    - Full agent prompts (multi-KB each)
    - Full progress history
    - Full findings history
    - Complete agent status details

    Args:
        task_id: Task ID

    Returns:
        Minimal coordination data (~1-2KB)
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {"success": False, "error": f"Task {task_id} not found"}

    registry_path = f"{workspace}/AGENT_REGISTRY.json"

    try:
        with open(registry_path, 'r') as f:
            registry = json.load(f)
    except:
        return {"success": False, "error": "Failed to read registry"}

    # Read only recent findings (last 3)
    recent_findings = []
    findings_dir = f"{workspace}/findings"
    if os.path.exists(findings_dir):
        all_findings = []
        for file in os.listdir(findings_dir):
            if file.endswith('_findings.jsonl'):
                try:
                    with open(f"{findings_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    all_findings.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue

        all_findings.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        recent_findings = all_findings[:3]  # Only last 3

    return {
        "success": True,
        "task_id": task_id,
        "agent_counts": {
            "total_spawned": registry.get('total_spawned', 0),
            "active": registry.get('active_count', 0),
            "completed": registry.get('completed_count', 0)
        },
        "recent_findings": recent_findings
    }

def get_comprehensive_coordination_info(
    task_id: str,
    max_findings_per_agent: int = 10,
    max_progress_per_agent: int = 5,
    find_task_workspace=None,
) -> Dict[str, Any]:
    """
    Get comprehensive coordination info for enhanced agent collaboration.
    Returns ALL peer data to enable full visibility and prevent duplicate work.

    Returns:
    - Full agent status details (who's working on what)
    - ALL findings grouped by agent (up to max_findings_per_agent per agent)
    - Recent progress from all agents (up to max_progress_per_agent per agent)
    - Summary of work distribution

    This enables agents to:
    - See everything peers have discovered
    - Understand current work distribution
    - Avoid duplicate investigations
    - Build on others' findings

    Args:
        task_id: Task ID
        max_findings_per_agent: Max findings to include per agent (default 10)
        max_progress_per_agent: Max progress updates per agent (default 5)

    Returns:
        Comprehensive coordination data for LLM consumption
    """
    # Use the passed function or default to global
    find_workspace = find_task_workspace if find_task_workspace is None else find_task_workspace

    workspace = find_workspace(task_id)
    if not workspace:
        return {"success": False, "error": f"Task {task_id} not found"}

    registry_path = f"{workspace}/AGENT_REGISTRY.json"

    # CRITICAL: Use LockedRegistryFile to prevent race conditions
    try:
        with LockedRegistryFile(registry_path) as (registry, f):
            # 1. Get all agents with current status
            agents_status = []
            for agent in registry.get('agents', []):
                agents_status.append({
                    "id": agent.get("id"),
                    "type": agent.get("type"),
                    "status": agent.get("status"),
                    "progress": agent.get("progress", 0),
                    "last_update": agent.get("last_update"),
                    "parent": agent.get("parent", "orchestrator")
                })
    except TimeoutError:
        return {"success": False, "error": "Registry locked - too many concurrent reads"}
    except Exception as e:
        return {"success": False, "error": f"Failed to read registry: {e}"}

    # 2. Get ALL findings grouped by agent
    findings_by_agent = {}
    findings_dir = f"{workspace}/findings"
    if os.path.exists(findings_dir):
        for file in os.listdir(findings_dir):
            if file.endswith('_findings.jsonl'):
                agent_id = file.replace('_findings.jsonl', '')
                agent_findings = []
                try:
                    with open(f"{findings_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    agent_findings.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue

                # Sort by timestamp and limit
                agent_findings.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
                findings_by_agent[agent_id] = agent_findings[:max_findings_per_agent]

    # 3. Get recent progress from all agents
    progress_by_agent = {}
    progress_dir = f"{workspace}/progress"
    if os.path.exists(progress_dir):
        for file in os.listdir(progress_dir):
            if file.endswith('_progress.jsonl'):
                agent_id = file.replace('_progress.jsonl', '')
                agent_progress = []
                try:
                    with open(f"{progress_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    agent_progress.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue

                # Sort by timestamp and get recent ones
                agent_progress.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
                progress_by_agent[agent_id] = agent_progress[:max_progress_per_agent]

    # 4. Create work distribution summary
    work_summary = {
        "total_agents": len(agents_status),
        "active_agents": len([a for a in agents_status if a.get("status") in ["working", "running", "blocked"]]),
        "completed_agents": len([a for a in agents_status if a.get("status") == "completed"]),
        "blocked_agents": len([a for a in agents_status if a.get("status") == "blocked"]),
        "total_findings": sum(len(findings) for findings in findings_by_agent.values()),
        "agents_with_findings": len(findings_by_agent)
    }

    return {
        "success": True,
        "task_id": task_id,
        "work_summary": work_summary,
        "agents": agents_status,
        "findings_by_agent": findings_by_agent,
        "progress_by_agent": progress_by_agent,
        "coordination_data": {
            "message": "Full peer visibility enabled for comprehensive coordination",
            "total_findings_available": sum(len(f) for f in findings_by_agent.values()),
            "total_progress_available": sum(len(p) for p in progress_by_agent.values())
        }
    }

def validate_agent_completion(workspace: str, agent_id: str, agent_type: str, message: str, registry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate agent completion claims with 4-layer validation.
    Architecture designed by architect-184627-99b952.

    Layers:
    1. Workspace evidence (files modified, findings reported)
    2. Type-specific validation (different requirements per agent type)
    3. Message content validation (evidence keywords, minimum length)
    4. Progress pattern validation (detect fake progress)

    Args:
        workspace: Task workspace path
        agent_id: Agent claiming completion
        agent_type: Type of agent (investigator, builder, fixer, etc.)
        message: Completion message
        registry: Task registry with agent data

    Returns:
        {
            "valid": bool,
            "confidence": float (0-1),
            "warnings": list[str],
            "blocking_issues": list[str],
            "evidence_summary": dict
        }
    """
    warnings = []
    blocking_issues = []
    evidence_summary = {}

    # Find agent in registry
    agent = None
    for a in registry.get('agents', []):
        if a['id'] == agent_id:
            agent = a
            break

    if not agent:
        blocking_issues.append(f"Agent {agent_id} not found in registry")
        return {
            "valid": False,
            "confidence": 0.0,
            "warnings": warnings,
            "blocking_issues": blocking_issues,
            "evidence_summary": evidence_summary
        }

    agent_start_time = agent.get('started_at')
    if not agent_start_time:
        warnings.append("Agent has no start time recorded")

    # LAYER 1: Workspace Evidence Checks
    evidence_summary['workspace_evidence'] = {}

    # Check for files created/modified in workspace
    modified_files = []
    try:
        import glob
        from datetime import datetime as dt
        workspace_files = glob.glob(f'{workspace}/**/*', recursive=True)
        if agent_start_time:
            start_dt = dt.fromisoformat(agent_start_time.replace('Z', '+00:00'))
            for f in workspace_files:
                if os.path.isfile(f):
                    try:
                        if os.path.getmtime(f) > start_dt.timestamp():
                            modified_files.append(f)
                    except:
                        pass
        evidence_summary['workspace_evidence']['modified_files_count'] = len(modified_files)

        if len(modified_files) == 0:
            warnings.append("No files created or modified in workspace - limited evidence of work")
    except Exception as e:
        logger.warning(f"Error checking workspace files: {e}")
        warnings.append(f"Could not verify workspace files: {e}")

    # Check progress entries count
    progress_file = f"{workspace}/progress/{agent_id}_progress.jsonl"
    progress_entries = []
    try:
        if os.path.exists(progress_file):
            with open(progress_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entry = json.loads(line)
                            progress_entries.append(entry)
                        except:
                            pass
        evidence_summary['workspace_evidence']['progress_entries_count'] = len(progress_entries)

        if len(progress_entries) < 3:
            warnings.append(f"Only {len(progress_entries)} progress updates - expected at least 3")
    except Exception as e:
        logger.warning(f"Error reading progress file: {e}")
        warnings.append(f"Could not verify progress history: {e}")

    # Check findings reported (for investigators)
    findings_file = f"{workspace}/findings/{agent_id}_findings.jsonl"
    finding_count = 0
    try:
        if os.path.exists(findings_file):
            with open(findings_file, 'r') as f:
                for line in f:
                    if line.strip():
                        finding_count += 1
        evidence_summary['workspace_evidence']['findings_count'] = finding_count
    except Exception as e:
        logger.warning(f"Error reading findings file: {e}")

    # LAYER 2: Type-Specific Validation
    evidence_summary['type_specific'] = {}

    if agent_type == 'investigator':
        evidence_summary['type_specific']['type'] = 'investigator'
        evidence_summary['type_specific']['findings_required'] = True

        if finding_count == 0:
            warnings.append("Investigator should report findings - no findings file found")
        elif finding_count < 3:
            warnings.append(f"Only {finding_count} findings reported - expected 3+ for thorough investigation")
        else:
            evidence_summary['type_specific']['findings_ok'] = True

    elif agent_type == 'builder':
        evidence_summary['type_specific']['type'] = 'builder'
        evidence_summary['type_specific']['artifacts_expected'] = True

        if len(progress_entries) < 5:
            warnings.append(f"Builder has fewer than 5 progress updates ({len(progress_entries)}) - expected more for implementation work")

        # Check for test-related evidence in message
        test_keywords = ['test', 'pass', 'fail', 'verify', 'check']
        has_test_evidence = any(kw in message.lower() for kw in test_keywords)
        evidence_summary['type_specific']['test_evidence'] = has_test_evidence
        if not has_test_evidence:
            warnings.append("Builder message lacks test/verification keywords")

    elif agent_type == 'fixer':
        evidence_summary['type_specific']['type'] = 'fixer'
        evidence_summary['type_specific']['verification_expected'] = True

        if len(progress_entries) < 4:
            warnings.append(f"Fixer has fewer than 4 progress updates ({len(progress_entries)})")

        # Check for fix verification evidence
        fix_keywords = ['fix', 'repair', 'resolve', 'correct', 'verify', 'test']
        has_fix_evidence = any(kw in message.lower() for kw in fix_keywords)
        evidence_summary['type_specific']['fix_evidence'] = has_fix_evidence
        if not has_fix_evidence:
            warnings.append("Fixer message lacks fix/verification keywords")

    # LAYER 3: Message Content Validation
    evidence_summary['message_validation'] = {}
    evidence_summary['message_validation']['length'] = len(message)

    if len(message) < 50:
        warnings.append(f"Completion message too short ({len(message)} chars) - should describe what was completed and how it was verified")

    # Check for suspicious phrases
    suspicious_phrases = ['TODO', 'not implemented', 'mock', 'placeholder', 'fake', 'dummy']
    found_suspicious = []
    for phrase in suspicious_phrases:
        if phrase.lower() in message.lower():
            found_suspicious.append(phrase)

    if found_suspicious:
        warnings.append(f"Message contains suspicious phrases: {', '.join(found_suspicious)} - indicates incomplete work")

    evidence_summary['message_validation']['suspicious_phrases_found'] = found_suspicious

    # Check for evidence keywords
    evidence_keywords = ['created', 'modified', 'tested', 'verified', 'found', 'fixed', 'implemented', 'reported', 'analyzed', 'documented']
    found_keywords = [kw for kw in evidence_keywords if kw in message.lower()]
    evidence_summary['message_validation']['evidence_keywords_found'] = found_keywords

    if len(found_keywords) == 0:
        warnings.append("Message lacks evidence keywords - should describe concrete actions taken")

    # LAYER 4: Progress Pattern Validation
    evidence_summary['progress_pattern'] = {}

    if len(progress_entries) < 3:
        warnings.append("Only start and end progress updates - no intermediate work shown")
        evidence_summary['progress_pattern']['pattern'] = 'suspicious_minimal'
    else:
        evidence_summary['progress_pattern']['pattern'] = 'normal'

    # Check time elapsed
    if agent_start_time and len(progress_entries) > 0:
        try:
            from datetime import datetime as dt
            start_dt = dt.fromisoformat(agent_start_time.replace('Z', '+00:00'))
            end_dt = dt.fromisoformat(progress_entries[-1]['timestamp'].replace('Z', '+00:00'))
            elapsed_seconds = (end_dt - start_dt).total_seconds()
            evidence_summary['progress_pattern']['elapsed_seconds'] = elapsed_seconds

            if elapsed_seconds < 120:
                warnings.append(f"Completed in {elapsed_seconds:.0f} seconds - suspiciously fast for quality work")
                evidence_summary['progress_pattern']['speed'] = 'too_fast'
            elif elapsed_seconds < 180:
                warnings.append(f"Completed in {elapsed_seconds:.0f} seconds - consider spending more time on quality")
                evidence_summary['progress_pattern']['speed'] = 'fast'
            else:
                evidence_summary['progress_pattern']['speed'] = 'reasonable'
        except Exception as e:
            logger.warning(f"Error calculating time elapsed: {e}")

    # Check for 'working' status updates
    working_updates = [e for e in progress_entries if e.get('status') == 'working']
    evidence_summary['progress_pattern']['working_updates_count'] = len(working_updates)

    if len(working_updates) == 0 and len(progress_entries) > 1:
        warnings.append("No 'working' status updates - agent may have skipped actual work phase")

    # Calculate confidence score
    # Start with 1.0, subtract for each warning/issue
    confidence = 1.0
    confidence -= len(warnings) * 0.1  # Each warning reduces confidence by 10%
    confidence -= len(blocking_issues) * 0.3  # Each blocking issue reduces by 30%
    confidence = max(0.0, min(1.0, confidence))  # Clamp to [0, 1]

    # Determine if valid (in WARNING mode, always valid unless critical blocking issues)
    # Critical blocking issues: agent not found, major evidence missing
    valid = len(blocking_issues) == 0

    return {
        "valid": valid,
        "confidence": confidence,
        "warnings": warnings,
        "blocking_issues": blocking_issues,
        "evidence_summary": evidence_summary
    }


@mcp.tool
def update_agent_progress(task_id: str, agent_id: str, status: str, message: str, progress: int = 0) -> Dict[str, Any]:
    """
    Update agent progress - called by agents themselves to self-report.
    Returns comprehensive status of all agents for coordination.
    
    Args:
        task_id: Task ID
        agent_id: Agent ID reporting progress  
        status: Current status (working/blocked/completed/etc)
        message: Status message describing current work
        progress: Progress percentage (0-100)
    
    Returns:
        Update result with comprehensive task status for coordination
    """
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
    
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    
    # Log progress update
    progress_file = f"{workspace}/progress/{agent_id}_progress.jsonl"
    os.makedirs(f"{workspace}/progress", exist_ok=True)
    
    progress_timestamp = datetime.now().isoformat()
    progress_entry = {
        "timestamp": progress_timestamp,
        "agent_id": agent_id,
        "status": status,
        "message": message,
        "progress": progress
    }
    
    with open(progress_file, 'a') as f:
        f.write(json.dumps(progress_entry) + '\n')

    # Best-effort materialization: JSONL is truth, SQLite is the fast read model.
    # Do not fail progress reporting just because the registry file is locked.
    workspace_base = get_workspace_base_from_task_workspace(workspace)
    try:
        state_db.reconcile_task_workspace(workspace)
        state_db.record_progress(
            workspace_base=workspace_base,
            task_id=task_id,
            agent_id=agent_id,
            timestamp=progress_timestamp,
            status=status,
            message=message,
            progress=progress,
        )
    except Exception as e:
        logger.warning(f"State DB update failed for {task_id}/{agent_id}: {e}")
    
    # Define status categories outside the lock for reuse
    active_statuses = ['running', 'working', 'blocked']
    terminal_statuses = ['completed', 'terminated', 'error', 'failed']
    previous_status = None  # Will be set inside lock
    pending_review = None  # Will be set if phase auto-completes
    cleanup_needed = False  # Run cleanup after lock (non-destructive)
    agent_phase_index = None  # Used for phase enforcement outside lock
    registry_lock_failed = False

    # CRITICAL: Use LockedRegistryFile to prevent race conditions
    # Multiple agents can update progress concurrently - without locking, we get:
    # - Lost updates (agent status overwritten)
    # - Corrupted counters (active_count decremented multiple times)
    # - Validation data lost between read and write
    try:
        with LockedRegistryFile(registry_path) as (registry, f):
            # Find and update agent
            agent_found = None
            for agent in registry['agents']:
                if agent['id'] == agent_id:
                    previous_status = agent.get('status')
                    agent['last_update'] = datetime.now().isoformat()
                    agent['status'] = status
                    agent['progress'] = progress
                    agent_found = agent
                    agent_phase_index = agent.get('phase_index')
                    break

            # VALIDATION: When agent claims completion, validate the claim
            if status == 'completed' and agent_found:
                agent_type = agent_found.get('type', 'unknown')

                # Run 4-layer validation
                validation = validate_agent_completion(workspace, agent_id, agent_type, message, registry)

                # In WARNING mode: log but don't block completion
                if not validation['valid'] or validation['warnings']:
                    logger.warning(f"Completion validation for {agent_id}: confidence={validation['confidence']:.2f}, "
                                 f"warnings={len(validation['warnings'])}, blocking_issues={len(validation['blocking_issues'])}")
                    logger.warning(f"Validation warnings: {validation['warnings']}")
                    if validation['blocking_issues']:
                        logger.warning(f"Blocking issues: {validation['blocking_issues']}")

                # Store validation results in agent record for future reference
                agent_found['completion_validation'] = {
                    'confidence': validation['confidence'],
                    'warnings': validation['warnings'],
                    'blocking_issues': validation['blocking_issues'],
                    'evidence_summary': validation['evidence_summary'],
                    'validated_at': datetime.now().isoformat()
                }

                logger.info(f"Agent {agent_id} completion validated: confidence={validation['confidence']:.2f}, "
                           f"{len(validation['warnings'])} warnings, {len(validation['blocking_issues'])} blocking issues")

                # Mark completion timestamp
                agent_found['completed_at'] = datetime.now().isoformat()

            # UPDATE COUNTS: Decrement when transitioning from active -> terminal state.
            # IMPORTANT: Do not perform slow/side-effecting work while holding the registry lock.
            if previous_status in active_statuses and status in terminal_statuses:
                registry['active_count'] = max(0, registry.get('active_count', 0) - 1)
                if status == 'completed':
                    registry['completed_count'] = registry.get('completed_count', 0) + 1
                logger.info(
                    f"Agent {agent_id} transitioned from {previous_status} to {status}. "
                    f"Active count: {registry['active_count']}"
                )

                # LIFECYCLE: Check if all agents are terminal and transition task to COMPLETED
                all_terminal = True
                for a in registry['agents']:
                    if a.get('status') not in terminal_statuses:
                        all_terminal = False
                        break

                if all_terminal and len(registry['agents']) > 0:
                    try:
                        workspace_base = get_workspace_base_from_task_workspace(workspace)
                        if state_db.transition_task_to_completed(workspace_base=workspace_base, task_id=task_id):
                            logger.info(f"[LIFECYCLE] Task {task_id} transitioned to COMPLETED - all agents terminal")
                            registry['status'] = 'COMPLETED'  # Update registry status to match
                    except Exception as e:
                        logger.warning(f"[LIFECYCLE] Failed to transition task to COMPLETED: {e}")

                # Run cleanup after we persist the registry update.
                cleanup_needed = True
                if agent_found:
                    agent_found['auto_cleanup_scheduled_at'] = datetime.now().isoformat()

            # MIGRATION FIX: Don't write to registry - state_db is source of truth
            # The state_db.record_progress call at line 3119 already persisted this update
            # Commenting out registry write to prevent stale data accumulation
            # f.seek(0)
            # f.write(json.dumps(registry, indent=2))
            # f.truncate()

            # Store pending auto-review info for spawning reviewers after lock release
            pending_review = registry.get('_pending_auto_review')

    except TimeoutError as e:
        logger.error(f"Timeout acquiring registry lock for update_agent_progress: {e}")
        registry_lock_failed = True
    except Exception as e:
        logger.error(f"Unexpected error updating registry for update_agent_progress: {e}")
        registry_lock_failed = True

    # ===== AUTOMATIC PHASE ENFORCEMENT (SQLite/JSONL truth) =====
    # Determine phase completion using JSONL-derived state, then transition phase in registry (best-effort).
    def _maybe_auto_submit_phase_for_review() -> Optional[Dict[str, Any]]:
        try:
            if status not in terminal_statuses:
                return None
            if agent_phase_index is None:
                return None

            # Ensure SQLite state is up to date before evaluating.
            state_db.reconcile_task_workspace(workspace)
            phase_state = state_db.load_phase_snapshot(
                workspace_base=workspace_base,
                task_id=task_id,
                phase_index=int(agent_phase_index),
            )
            if not phase_state.get("counts", {}).get("all_done"):
                return None

            registry_path_local = os.path.join(workspace, "AGENT_REGISTRY.json")
            with LockedRegistryFile(registry_path_local) as (reg, rf):
                phases = reg.get("phases", []) or []
                current_idx = int(reg.get("current_phase_index") or 0)
                if current_idx != int(agent_phase_index):
                    return None
                if current_idx >= len(phases):
                    return None
                current_phase = phases[current_idx]
                if current_phase.get("status") != "ACTIVE":
                    return None

                # Transition phase to review.
                current_phase["status"] = "AWAITING_REVIEW"
                current_phase["auto_submitted_at"] = datetime.now().isoformat()
                current_phase["auto_submitted_reason"] = (
                    f"All {phase_state['counts']['total']} agents terminal (SQLite/JSONL truth)"
                )

                # Store pending reviewer spawn info.
                reg["_pending_auto_review"] = {
                    "phase_index": int(agent_phase_index),
                    "phase_name": current_phase.get("name", f"Phase {int(agent_phase_index) + 1}"),
                    "task_id": task_id,
                    "completed_agents": int(phase_state["counts"]["completed"]),
                    "failed_agents": int(phase_state["counts"]["failed"]),
                }

                # MIGRATION FIX: Don't write to registry - state_db handles phase transitions
                # rf.seek(0)
                # rf.write(json.dumps(reg, indent=2))
                # rf.truncate()

                return reg.get("_pending_auto_review")
        except TimeoutError:
            # Registry lock busy - retry later (non-fatal).
            return None
        except Exception as e:
            logger.error(f"AUTO-PHASE-ENFORCEMENT: Failed to evaluate/transition phase: {e}")
            return None

    if not pending_review:
        # If registry update failed, derive phase_index from SQLite so phase enforcement can still work.
        if agent_phase_index is None:
            try:
                snap = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id) or {}
                for a in snap.get("agents", []) or []:
                    if a.get("agent_id") == agent_id or a.get("id") == agent_id:
                        agent_phase_index = a.get("phase_index")
                        break
            except Exception:
                pass
        pending_review = _maybe_auto_submit_phase_for_review()

        # If the phase is complete but the registry lock was contended, retry in the background so phases
        # can still advance even if no further agent progress updates occur.
        if not pending_review and status in terminal_statuses and agent_phase_index is not None:
            def _review_retry_worker() -> None:
                try:
                    import time

                    for _ in range(10):  # ~30s total
                        pr = _maybe_auto_submit_phase_for_review()
                        if pr:
                            try:
                                logger.info(
                                    f"AUTO-PHASE-ENFORCEMENT: Retried phase transition succeeded for phase {pr.get('phase_index')}"
                                )
                                _auto_spawn_phase_reviewers(
                                    task_id=pr["task_id"],
                                    phase_index=pr["phase_index"],
                                    phase_name=pr["phase_name"],
                                    completed_agents=pr["completed_agents"],
                                    failed_agents=pr["failed_agents"],
                                    workspace=workspace,
                                )
                            except Exception as e:
                                logger.error(f"AUTO-PHASE-ENFORCEMENT: Retry reviewer spawn failed: {e}")
                            return
                        time.sleep(3)
                except Exception:
                    return

            threading.Thread(target=_review_retry_worker, daemon=True).start()
    
    # UPDATE GLOBAL REGISTRY: Sync the global registry's active agent count
    # CRITICAL: Use LockedRegistryFile here too to prevent global registry corruption
    try:
        workspace_base = get_workspace_base_from_task_workspace(workspace)
        global_reg_path = get_global_registry_path(workspace_base)
        if os.path.exists(global_reg_path):
            with LockedRegistryFile(global_reg_path) as (global_reg, gf):
                # Update agent status in global registry
                if agent_id in global_reg.get('agents', {}):
                    global_reg['agents'][agent_id]['status'] = status
                    global_reg['agents'][agent_id]['last_update'] = datetime.now().isoformat()

                    # If transitioned to terminal state, update global active count
                    if previous_status in active_statuses and status in terminal_statuses:
                        global_reg['active_agents'] = max(0, global_reg.get('active_agents', 0) - 1)
                        if status == 'completed':
                            global_reg['agents'][agent_id]['completed_at'] = datetime.now().isoformat()
                        logger.info(f"Global registry updated: Active agents: {global_reg['active_agents']}")

                    # Write back atomically
                    gf.seek(0)
                    gf.write(json.dumps(global_reg, indent=2))
                    gf.truncate()
    except TimeoutError as e:
        logger.error(f"Timeout acquiring global registry lock: {e}")
        # Non-fatal: continue even if global registry update fails
    except Exception as e:
        logger.error(f"Failed to update global registry: {e}")

    # ===== ASYNC NON-DESTRUCTIVE CLEANUP =====
    # Historical bug: cleanup ran inside the registry lock and could prevent the registry update
    # from being written, and/or kill the calling tmux session before the tool_result was received.
    # We now persist the registry first, then do best-effort cleanup asynchronously without killing tmux.
    if cleanup_needed:
        def _cleanup_worker():
            try:
                time.sleep(2)

                registry_path_local = f"{workspace}/AGENT_REGISTRY.json"
                agent_data = None
                try:
                    reg = read_registry_with_lock(registry_path_local)
                    if reg:
                        for a in reg.get('agents', []):
                            if a.get('id') == agent_id:
                                agent_data = a
                                break
                except Exception:
                    agent_data = None

                if not agent_data:
                    return

                cleanup_result = cleanup_agent_resources(
                    workspace=workspace,
                    agent_id=agent_id,
                    agent_data=agent_data,
                    keep_logs=True,
                    kill_tmux=False,
                )

                # Persist cleanup result (separate atomic update)
                try:
                    with LockedRegistryFile(registry_path_local) as (reg2, f2):
                        for a in reg2.get('agents', []):
                            if a.get('id') == agent_id:
                                a['auto_cleanup_result'] = cleanup_result
                                a['auto_cleanup_timestamp'] = datetime.now().isoformat()
                                break
                        f2.seek(0)
                        f2.write(json.dumps(reg2, indent=2))
                        f2.truncate()
                except Exception as cleanup_update_err:
                    logger.warning(f"Could not persist cleanup result for {agent_id}: {cleanup_update_err}")
            except Exception as e:
                logger.error(f"Async cleanup failed for {agent_id}: {e}")

        threading.Thread(target=_cleanup_worker, daemon=True).start()

    # ===== AUTO-SPAWN REVIEWERS FOR PHASE ENFORCEMENT =====
    # If a phase just auto-completed, spawn independent reviewer agents
    if pending_review:
        try:
            logger.info(f"AUTO-PHASE-ENFORCEMENT: Spawning reviewers for phase {pending_review['phase_index']}")
            auto_review_result = _auto_spawn_phase_reviewers(
                task_id=pending_review['task_id'],
                phase_index=pending_review['phase_index'],
                phase_name=pending_review['phase_name'],
                completed_agents=pending_review['completed_agents'],
                failed_agents=pending_review['failed_agents'],
                workspace=workspace
            )
            logger.info(f"AUTO-PHASE-ENFORCEMENT: Reviewer spawn result: {auto_review_result}")
        except Exception as e:
            logger.error(f"AUTO-PHASE-ENFORCEMENT: Failed to spawn reviewers: {e}")

    # LEAN RESPONSE: Only return own update + guidance to fetch peer info explicitly
    # This prevents O(n²) context bloat from returning all peer data on every call
    response = {
        "success": True,
        "own_update": {
            "agent_id": agent_id,
            "status": status,
            "progress": progress,
            "message": message,
            "timestamp": progress_entry["timestamp"]
        },
        "coordination_guidance": {
            "message": "To see what other agents are working on and avoid duplicate work, call get_task_findings",
            "tool": "get_task_findings",
            "parameters": {
                "task_id": task_id,
                "summary_only": True
            },
            "tip": "Use 'since' parameter with a timestamp to get only NEW findings since your last check"
        }
    }

    # Add completion reminder if not yet completed
    if status != "completed":
        response["important_reminder"] = (
            "CRITICAL: You MUST call update_agent_progress with status='completed' when you finish your work. "
            "If you don't, the phase cannot advance and other agents will be blocked waiting for you. "
            "Your work is not counted until you report completion."
        )

    if registry_lock_failed:
        response["warnings"] = response.get("warnings") or []
        response["warnings"].append(
            "Registry update was skipped due to lock contention; JSONL + SQLite state was updated successfully."
        )

    return response

@mcp.tool  
def report_agent_finding(task_id: str, agent_id: str, finding_type: str, severity: str, message: str, data: dict = None) -> Dict[str, Any]:
    """
    Report a finding/discovery - called by agents to share discoveries.
    Returns comprehensive status of all agents for coordination.
    
    Args:
        task_id: Task ID
        agent_id: Agent ID reporting finding
        finding_type: Type of finding (issue/solution/insight/etc)
        severity: Severity level (low/medium/high/critical)  
        message: Finding description
        data: Additional finding data
    
    Returns:
        Report result with comprehensive task status for coordination
    """
    if data is None:
        data = {}
    
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
        
    findings_file = f"{workspace}/findings/{agent_id}_findings.jsonl"
    os.makedirs(f"{workspace}/findings", exist_ok=True)
    
    finding_entry = {
        "timestamp": datetime.now().isoformat(),
        "agent_id": agent_id,
        "finding_type": finding_type,
        "severity": severity,
        "message": message,
        "data": data
    }
    
    with open(findings_file, 'a') as f:
        f.write(json.dumps(finding_entry) + '\n')

    # MIGRATION FIX: Also record finding in state_db for materialized state
    try:
        workspace_base = get_workspace_base_from_task_workspace(workspace)
        state_db.record_agent_finding(
            workspace_base=workspace_base,
            task_id=task_id,
            agent_id=agent_id,
            finding_type=finding_type,
            severity=severity,
            message=message,
            data=data
        )
        logger.debug(f"Finding recorded in state_db for agent {agent_id}")
    except Exception as e:
        logger.warning(f"Failed to record finding in state_db: {e}")

    # LEAN RESPONSE: Only return own finding + guidance to fetch peer info explicitly
    # This prevents O(n²) context bloat from returning all peer data on every call
    return {
        "success": True,
        "own_finding": {
            "agent_id": agent_id,
            "finding_type": finding_type,
            "severity": severity,
            "message": message,
            "timestamp": finding_entry["timestamp"],
            "data": data
        },
        "coordination_guidance": {
            "message": "To see findings from other agents and coordinate effectively, call get_task_findings",
            "tool": "get_task_findings",
            "parameters": {
                "task_id": task_id,
                "summary_only": True
            },
            "tip": "Use 'since' parameter with a timestamp to get only NEW findings since your last check"
        },
        "important_reminder": (
            "CRITICAL: When you finish your work, you MUST call update_agent_progress with status='completed'. "
            "If you don't, the phase cannot advance and other agents will be blocked waiting for you. "
            "Your work is not counted until you report completion."
        )
    }

@mcp.tool
def spawn_opus_child_agent(task_id: str, parent_agent_id: str, child_agent_type: str, child_prompt: str) -> Dict[str, Any]:
    """
    Spawn an OPUS child agent for COMPLEX sub-tasks requiring deep reasoning.

    USE OPUS CHILD FOR:
    - Complex sub-task reasoning and decisions
    - Security-critical child operations
    - Difficult debugging that requires judgment
    - Architecture decisions within the parent's scope
    - Critical code modifications

    Args:
        task_id: Parent task ID
        parent_agent_id: ID of parent agent spawning this child
        child_agent_type: Type of child agent
        child_prompt: Prompt for child agent

    Returns:
        Child agent spawn result
    """
    return deploy_claude_tmux_agent(task_id, child_agent_type, child_prompt, parent_agent_id, None, "claude-opus-4-5")


@mcp.tool
def spawn_sonnet_child_agent(task_id: str, parent_agent_id: str, child_agent_type: str, child_prompt: str) -> Dict[str, Any]:
    """
    Spawn a SONNET child agent for MODERATE sub-tasks requiring speed.

    USE SONNET CHILD FOR:
    - Quick research or file lookups
    - Simple validations and checks
    - Documentation tasks
    - Data gathering for parent agent
    - Straightforward implementations

    Args:
        task_id: Parent task ID
        parent_agent_id: ID of parent agent spawning this child
        child_agent_type: Type of child agent
        child_prompt: Prompt for child agent

    Returns:
        Child agent spawn result
    """
    return deploy_claude_tmux_agent(task_id, child_agent_type, child_prompt, parent_agent_id, None, "claude-sonnet-4-5")


@mcp.tool
def get_task_findings(
    task_id: str,
    agent_id: Optional[str] = None,
    finding_type: Optional[str] = None,
    severity: Optional[str] = None,
    since: Optional[str] = None,
    summary_only: bool = False,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Get findings from task agents - use this to coordinate with peers.

    IMPORTANT: Call this to see what other agents have discovered.
    Use the 'since' parameter to get only NEW findings since your last check
    to avoid re-reading the same data and wasting context.

    Args:
        task_id: Task ID
        agent_id: Optional - filter to specific agent's findings
        finding_type: Optional - filter by type (issue/solution/insight/blocker)
        severity: Optional - filter by severity (low/medium/high/critical)
        since: Optional ISO timestamp - only return findings after this time
        summary_only: If True, return compact summary instead of full findings
        limit: Max findings to return (default 50)

    Returns:
        Findings from agents, optionally filtered
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {"success": False, "error": f"Task {task_id} not found"}

    findings_dir = f"{workspace}/findings"
    archive_dir = f"{workspace}/archive"

    # Check both findings/ and archive/ directories for findings files
    # Auto-cleanup moves findings to archive/, so we need to search both
    findings_dirs_to_search = []
    if os.path.exists(findings_dir):
        findings_dirs_to_search.append(findings_dir)
    if os.path.exists(archive_dir):
        findings_dirs_to_search.append(archive_dir)

    if not findings_dirs_to_search:
        return {
            "success": True,
            "findings": [],
            "summary": {"total": 0, "by_severity": {}, "by_agent": {}},
            "message": "No findings reported yet"
        }

    all_findings = []
    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
        except ValueError:
            return {"success": False, "error": f"Invalid 'since' timestamp format: {since}"}

    # Read findings files from both findings/ and archive/ directories
    for search_dir in findings_dirs_to_search:
        for file in os.listdir(search_dir):
            if not file.endswith('_findings.jsonl'):
                continue

            file_agent_id = file.replace('_findings.jsonl', '')

            # Filter by agent if specified
            if agent_id and file_agent_id != agent_id:
                continue

            try:
                with open(f"{search_dir}/{file}", 'r') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)

                            # Apply since filter
                            if since_dt:
                                entry_time = datetime.fromisoformat(entry.get('timestamp', '').replace('Z', '+00:00'))
                                if entry_time <= since_dt:
                                    continue

                            # Apply type filter
                            if finding_type and entry.get('finding_type') != finding_type:
                                continue

                            # Apply severity filter
                            if severity and entry.get('severity') != severity:
                                continue

                            all_findings.append(entry)
                        except (json.JSONDecodeError, ValueError):
                            continue
            except Exception as e:
                logger.warning(f"Error reading findings file {file}: {e}")
                continue

    # Sort by timestamp (newest first) and limit
    all_findings.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    all_findings = all_findings[:limit]

    # Build summary stats
    summary = {
        "total": len(all_findings),
        "by_severity": {},
        "by_agent": {},
        "by_type": {}
    }

    for f in all_findings:
        sev = f.get('severity', 'unknown')
        agt = f.get('agent_id', 'unknown')
        ftype = f.get('finding_type', 'unknown')

        summary["by_severity"][sev] = summary["by_severity"].get(sev, 0) + 1
        summary["by_agent"][agt] = summary["by_agent"].get(agt, 0) + 1
        summary["by_type"][ftype] = summary["by_type"].get(ftype, 0) + 1

    if summary_only:
        # Return compact summary for quick coordination checks
        agent_summaries = []
        for agt, count in summary["by_agent"].items():
            agent_findings = [f for f in all_findings if f.get('agent_id') == agt]
            critical_count = len([f for f in agent_findings if f.get('severity') == 'critical'])
            high_count = len([f for f in agent_findings if f.get('severity') == 'high'])

            agent_summaries.append({
                "agent_id": agt,
                "finding_count": count,
                "critical": critical_count,
                "high": high_count,
                "latest_message": agent_findings[0].get('message', '')[:100] if agent_findings else ''
            })

        return {
            "success": True,
            "summary": summary,
            "agent_summaries": agent_summaries,
            "since": since,
            "tip": "Call with summary_only=False to get full finding details"
        }

    return {
        "success": True,
        "findings": all_findings,
        "summary": summary,
        "since": since,
        "current_time": datetime.now().isoformat(),
        "tip": "Save current_time and pass as 'since' on next call to get only new findings"
    }


@mcp.resource("tasks://list")  
def list_real_tasks() -> str:
    """List all real tasks."""
    ensure_workspace()
    
    global_reg_path = f"{WORKSPACE_BASE}/registry/GLOBAL_REGISTRY.json"
    if not os.path.exists(global_reg_path):
        return json.dumps({"tasks": [], "message": "No tasks found"})
    
    with open(global_reg_path, 'r') as f:
        global_reg = json.load(f)
    
    return json.dumps(global_reg, indent=2)

@mcp.resource("task://{task_id}/status")
def get_task_resource(task_id: str) -> str:
    """Get task details as resource."""
    result = get_real_task_status(task_id)
    return json.dumps(result, indent=2)

@mcp.resource("task://{task_id}/progress-timeline")  
def get_task_progress_timeline(task_id: str) -> str:
    """Get comprehensive progress timeline for a task."""
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"error": f"Task {task_id} not found in any workspace location"}, indent=2)
    
    all_progress = []
    all_findings = []
    
    # Read all progress files
    progress_dir = f"{workspace}/progress"
    if os.path.exists(progress_dir):
        for file in os.listdir(progress_dir):
            if file.endswith('_progress.jsonl'):
                try:
                    with open(f"{progress_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    all_progress.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Read all findings files
    findings_dir = f"{workspace}/findings" 
    if os.path.exists(findings_dir):
        for file in os.listdir(findings_dir):
            if file.endswith('_findings.jsonl'):
                try:
                    with open(f"{findings_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    all_findings.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Sort by timestamp
    all_progress.sort(key=lambda x: x.get('timestamp', ''))
    all_findings.sort(key=lambda x: x.get('timestamp', ''))
    
    # Create combined timeline
    timeline = []
    for progress in all_progress:
        timeline.append({**progress, "entry_type": "progress"})
    for finding in all_findings:
        timeline.append({**finding, "entry_type": "finding"})
    
    timeline.sort(key=lambda x: x.get('timestamp', ''))
    
    return json.dumps({
        "task_id": task_id,
        "timeline": timeline,
        "summary": {
            "total_progress_entries": len(all_progress),
            "total_findings": len(all_findings),
            "timeline_span": {
                "start": timeline[0]["timestamp"] if timeline else None,
                "end": timeline[-1]["timestamp"] if timeline else None
            },
            "agents_active": len(set(entry.get("agent_id") for entry in timeline if entry.get("agent_id")))
        }
    }, indent=2)

def startup_registry_validation():
    """
    Run registry validation on MCP server startup.

    This automatically repairs any zombie agents or count mismatches
    that may have accumulated from previous crashes or race conditions.
    """
    logger.info("Running startup registry validation...")

    try:
        # Find all task registries
        workspace_base = WORKSPACE_BASE
        registries_to_check = []

        workspace_path = Path(workspace_base)
        for task_dir in workspace_path.glob('TASK-*'):
            registry_file = task_dir / 'AGENT_REGISTRY.json'
            if registry_file.exists():
                registries_to_check.append(str(registry_file))

        if not registries_to_check:
            logger.info("No task registries found - skipping validation")
            return

        logger.info(f"Found {len(registries_to_check)} registries to validate")

        # Validate and repair each registry
        total_zombies = 0
        total_corrections = 0

        for registry_path in registries_to_check:
            try:
                result = validate_and_repair_registry(registry_path, dry_run=False)
                if result['success']:
                    if result['zombies_terminated'] > 0 or result['count_corrected']:
                        total_zombies += result['zombies_terminated']
                        if result['count_corrected']:
                            total_corrections += 1
                        logger.info(f"Repaired {registry_path}: {result['summary']}")
                else:
                    logger.warning(f"Failed to repair {registry_path}: {result.get('error')}")
            except Exception as e:
                logger.error(f"Error validating {registry_path}: {e}")
                continue

        if total_zombies > 0 or total_corrections > 0:
            logger.info(f"Startup validation complete: terminated {total_zombies} zombies, "
                       f"corrected {total_corrections} registries")
        else:
            logger.info("Startup validation complete: all registries healthy")

    except Exception as e:
        logger.error(f"Startup validation failed: {e}")
        # Don't crash the server if validation fails
        pass

# ============================================================================
# PHASE, HANDOVER, AND REVIEW TOOLS (Native Sequential Phase Architecture)
# ============================================================================

# Import from orchestrator module for new features
from orchestrator import (
    # Handover
    HandoverDocument, HANDOVER_MAX_TOKENS, save_handover, load_handover,
    format_handover_markdown, auto_generate_handover, collect_phase_findings,
    # Review
    ReviewAgent, ReviewFinding, ReviewConfig, ReviewStatus, ReviewVerdict,
    REVIEW_VERDICTS, REVIEW_FINDING_TYPES,
    create_review_agent, submit_review_verdict, calculate_aggregate_verdict,
    trigger_phase_review, create_review_record, get_phase_reviews,
    # Phase validation
    PHASE_STATUSES, PhaseValidationError, create_default_phase, validate_phases,
    ensure_task_has_phases,
    # Phase completion tracking
    AGENT_TERMINAL_STATUSES, check_phase_completion,
)


@mcp.tool()
def get_phase_status(task_id: str) -> str:
    """
    Get current phase status for a task.

    Returns the current phase, its status, available transitions, and detailed guidance.
    IMPORTANT: This is the primary tool for understanding what to do next.
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    if not os.path.exists(registry_path):
        return json.dumps({"success": False, "error": "Registry not found"})

    # SQLite-backed phase view (JSONL truth) to avoid registry drift.
    workspace_base = get_workspace_base_from_task_workspace(workspace)
    try:
        state_db.reconcile_task_workspace(workspace)
    except Exception as e:
        logger.warning(f"State DB reconcile failed for {task_id}: {e}")

    snapshot = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id) or {}
    phases = snapshot.get("phases", []) or []
    current_idx = int(snapshot.get("current_phase_index") or 0)

    if not phases:
        return json.dumps({"success": True, "has_phases": False, "message": "Task has no phases defined"})

    current_phase = phases[current_idx] if current_idx < len(phases) else None
    phase_status = (current_phase or {}).get("status", "UNKNOWN")

    phase_state = state_db.load_phase_snapshot(
        workspace_base=workspace_base,
        task_id=task_id,
        phase_index=current_idx,
    )
    completed_agents = int(phase_state.get("counts", {}).get("completed", 0))
    pending_agents = int(phase_state.get("counts", {}).get("pending", 0))
    failed_agents = int(phase_state.get("counts", {}).get("failed", 0))

    # Optional: enrich with review details from registry (metadata only).
    review_details = None
    try:
        with open(registry_path, "r", encoding="utf-8", errors="ignore") as f:
            registry = json.load(f) or {}
        reviews = registry.get("reviews", []) or []
        active_id = (registry.get("phases", []) or [{}])[current_idx].get("active_review_id") if registry.get("phases") else None
        active_review = None
        for rev in reviews:
            if active_id and rev.get("review_id") == active_id:
                active_review = rev
                break
        if active_review:
            verdicts = active_review.get("verdicts", []) or []
            all_findings = []
            for v in verdicts:
                all_findings.extend(v.get("findings", []) or [])
            critical_findings = [f for f in all_findings if f.get("severity") == "critical"]
            high_findings = [f for f in all_findings if f.get("severity") == "high"]
            blockers = [f for f in all_findings if f.get("type") == "blocker"]
            review_details = {
                "review_id": active_review.get("review_id"),
                "status": active_review.get("status"),
                "reviewers_submitted": len(verdicts),
                "reviewers_expected": active_review.get("num_reviewers", 0),
                "final_verdict": active_review.get("final_verdict"),
                "findings_summary": {
                    "total": len(all_findings),
                    "critical": len(critical_findings),
                    "high": len(high_findings),
                    "blockers": len(blockers),
                },
                "blocker_messages": [b.get("message", "") for b in blockers[:5]],
                "critical_messages": [c.get("message", "") for c in critical_findings[:5]],
            }
    except Exception:
        review_details = None

    # Guidance (mirrors prior semantics, but uses SQLite counts).
    guidance = {"status": phase_status, "action": "", "blocked_reason": None}
    if phase_status == "ACTIVE":
        if int(phase_state.get("counts", {}).get("total", 0)) == 0:
            guidance["action"] = "DEPLOY AGENTS: No agents deployed. Use deploy_opus_agent/deploy_sonnet_agent to start work."
        elif pending_agents > 0:
            guidance["action"] = f"WAIT: {pending_agents} agents still working. Monitor with get_agent_output."
        else:
            guidance["action"] = "REVIEW PENDING: All agents done. System will auto-trigger review."
    elif phase_status == "AWAITING_REVIEW":
        guidance["action"] = "REVIEWERS SPAWNING: Agentic reviewers being deployed. Wait for UNDER_REVIEW status."
    elif phase_status == "UNDER_REVIEW":
        if review_details:
            submitted = review_details.get("reviewers_submitted", 0)
            expected = review_details.get("reviewers_expected", 0)
            guidance["action"] = f"REVIEW IN PROGRESS: {submitted}/{expected} reviewers submitted. Wait for verdicts."
        else:
            guidance["action"] = "REVIEW IN PROGRESS: Waiting for reviewer verdicts."
    elif phase_status == "APPROVED":
        if current_idx < len(phases) - 1:
            next_phase_name = phases[current_idx + 1].get("name", f"Phase {current_idx + 2}")
            guidance["action"] = f"PROCEED: Phase approved. Use advance_to_next_phase to start '{next_phase_name}'."
        else:
            guidance["action"] = "TASK COMPLETE: All phases approved. Task finished successfully."
    elif phase_status == "REVISING":
        if review_details and review_details.get("blocker_messages"):
            guidance["action"] = "FIX REQUIRED: Address blockers and re-submit for review."
            guidance["blocked_reason"] = review_details.get("blocker_messages")
        else:
            guidance["action"] = "REVISIONS NEEDED: Reviewers requested changes. Deploy agents to fix issues."
    elif phase_status == "REJECTED":
        guidance["action"] = "PHASE REJECTED: Critical issues found. Review findings and deploy fix agents."
        if review_details:
            guidance["blocked_reason"] = review_details.get("critical_messages", [])
    elif phase_status == "ESCALATED":
        guidance["action"] = "ESCALATED - MANUAL INTERVENTION REQUIRED: Check registry for details."
        guidance["blocked_reason"] = "Escalated"
        guidance["escalated"] = True
    else:
        guidance["action"] = f"UNKNOWN STATE: Phase in '{phase_status}'. Check registry manually."

    return json.dumps(
        {
            "success": True,
            "has_phases": True,
            "total_phases": len(phases),
            "current_phase_index": current_idx,
            "current_phase": {
                "name": current_phase.get("name") if current_phase else None,
                "status": phase_status,
                "description": current_phase.get("description") if current_phase else None,
            },
            "agents": {
                "total": int(phase_state.get("counts", {}).get("total", 0)),
                "completed": completed_agents,
                "pending": pending_agents,
                "failed": failed_agents,
            },
            "review": review_details,
            "guidance": guidance,
            "phases_summary": [{"order": i + 1, "name": p.get("name"), "status": p.get("status")} for i, p in enumerate(phases)],
        },
        indent=2,
    )

    with open(registry_path, 'r') as f:
        registry = json.load(f)

    phases = registry.get('phases', [])
    current_idx = registry.get('current_phase_index', 0)

    if not phases:
        return json.dumps({
            "success": True,
            "has_phases": False,
            "message": "Task has no phases defined"
        })

    current_phase = phases[current_idx] if current_idx < len(phases) else None
    phase_status = current_phase.get('status', 'UNKNOWN') if current_phase else None

    # Get phase agents
    phase_agents = [a for a in registry.get('agents', []) if a.get('phase_index') == current_idx]
    completed_agents = len([a for a in phase_agents if a.get('status') == 'completed'])
    pending_agents = len([a for a in phase_agents if a.get('status') not in ['completed', 'failed', 'error', 'terminated']])
    failed_agents = len([a for a in phase_agents if a.get('status') in ['failed', 'error', 'terminated']])

    # Check for active review
    reviews = registry.get('reviews', [])
    active_review = None
    review_details = None
    for rev in reviews:
        if rev.get('review_id') == current_phase.get('active_review_id'):
            active_review = rev
            break

    # Build detailed review info
    if active_review:
        verdicts = active_review.get('verdicts', [])
        all_findings = []
        for v in verdicts:
            all_findings.extend(v.get('findings', []))

        # Categorize findings by severity
        critical_findings = [f for f in all_findings if f.get('severity') == 'critical']
        high_findings = [f for f in all_findings if f.get('severity') == 'high']
        blockers = [f for f in all_findings if f.get('type') == 'blocker']

        review_details = {
            "review_id": active_review.get('review_id'),
            "status": active_review.get('status'),
            "reviewers_submitted": len(verdicts),
            "reviewers_expected": active_review.get('num_reviewers', 0),
            "final_verdict": active_review.get('final_verdict'),
            "findings_summary": {
                "total": len(all_findings),
                "critical": len(critical_findings),
                "high": len(high_findings),
                "blockers": len(blockers)
            },
            "blocker_messages": [b.get('message', '') for b in blockers[:5]],  # Top 5 blockers
            "critical_messages": [c.get('message', '') for c in critical_findings[:5]]  # Top 5 critical
        }

    # Generate actionable guidance based on current state
    guidance = {"status": phase_status, "action": "", "blocked_reason": None}

    if phase_status == 'ACTIVE':
        if len(phase_agents) == 0:
            guidance["action"] = "DEPLOY AGENTS: No agents deployed. Use deploy_opus_agent/deploy_sonnet_agent to start work."
        elif pending_agents > 0:
            guidance["action"] = f"WAIT: {pending_agents} agents still working. Monitor with get_agent_output."
        else:
            guidance["action"] = "REVIEW PENDING: All agents done. System will auto-trigger review."
    elif phase_status == 'AWAITING_REVIEW':
        guidance["action"] = "REVIEWERS SPAWNING: Agentic reviewers being deployed. Wait for UNDER_REVIEW status."
    elif phase_status == 'UNDER_REVIEW':
        if review_details:
            submitted = review_details['reviewers_submitted']
            expected = review_details['reviewers_expected']
            guidance["action"] = f"REVIEW IN PROGRESS: {submitted}/{expected} reviewers submitted. Wait for verdicts."
        else:
            guidance["action"] = "REVIEW IN PROGRESS: Waiting for reviewer verdicts."
    elif phase_status == 'APPROVED':
        if current_idx < len(phases) - 1:
            next_phase_name = phases[current_idx + 1].get('name', f'Phase {current_idx + 2}')
            guidance["action"] = f"PROCEED: Phase approved. Use advance_to_next_phase to start '{next_phase_name}'."
        else:
            guidance["action"] = "TASK COMPLETE: All phases approved. Task finished successfully."
    elif phase_status == 'REVISING':
        if review_details and review_details.get('blocker_messages'):
            guidance["action"] = "FIX REQUIRED: Address blockers and re-submit for review."
            guidance["blocked_reason"] = review_details['blocker_messages']
        else:
            guidance["action"] = "REVISIONS NEEDED: Reviewers requested changes. Deploy agents to fix issues."
    elif phase_status == 'REJECTED':
        guidance["action"] = "PHASE REJECTED: Critical issues found. Review findings and deploy fix agents."
        if review_details:
            guidance["blocked_reason"] = review_details.get('critical_messages', [])
    elif phase_status == 'ESCALATED':
        # This happens when all reviewers crashed without submitting verdicts
        escalation_reason = current_phase.get('escalation_reason', 'All reviewers crashed')
        guidance["action"] = f"ESCALATED - MANUAL INTERVENTION REQUIRED: {escalation_reason}. Options: (1) Use abort_stalled_review and trigger_agentic_review to retry with new reviewers, (2) Use approve_phase_review with force flag if work is actually complete."
        guidance["blocked_reason"] = escalation_reason
        guidance["escalated"] = True
    else:
        guidance["action"] = f"UNKNOWN STATE: Phase in '{phase_status}'. Check registry manually."

    return json.dumps({
        "success": True,
        "has_phases": True,
        "total_phases": len(phases),
        "current_phase_index": current_idx,
        "current_phase": {
            "name": current_phase.get('name') if current_phase else None,
            "status": phase_status,
            "description": current_phase.get('description') if current_phase else None
        },
        "agents": {
            "total": len(phase_agents),
            "completed": completed_agents,
            "pending": pending_agents,
            "failed": failed_agents
        },
        "review": review_details,
        "guidance": guidance,
        "phases_summary": [
            {"order": p.get('order'), "name": p.get('name'), "status": p.get('status')}
            for p in phases
        ]
    }, indent=2)


@mcp.tool()
def check_phase_progress(task_id: str) -> str:
    """
    Check if current phase is ready for review.

    Returns detailed phase completion status including:
    - All agents done (ready_for_review)
    - Pending agents still working
    - Recommended next action

    This is the primary tool for monitoring phase progress and knowing
    when to submit for review or advance to next phase.
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')

    # SQLite-backed phase progress (JSONL truth) to avoid registry drift/lock contention.
    workspace_base = get_workspace_base_from_task_workspace(workspace)
    try:
        state_db.reconcile_task_workspace(workspace)
    except Exception as e:
        logger.warning(f"State DB reconcile failed for {task_id}: {e}")

    snapshot = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id) or {}
    phases = snapshot.get("phases", []) or []
    current_idx = int(snapshot.get("current_phase_index") or 0)

    if not phases or current_idx >= len(phases):
        return json.dumps({"success": False, "error": "No current phase"})

    current_phase = phases[current_idx]
    phase_status = current_phase.get("status")

    phase_state = state_db.load_phase_snapshot(
        workspace_base=workspace_base, task_id=task_id, phase_index=current_idx
    )
    counts = phase_state.get("counts", {}) or {}

    all_done = bool(counts.get("all_done"))
    ready_for_review = all_done and phase_status == "ACTIVE"

    if phase_status == "APPROVED":
        if current_idx < len(phases) - 1:
            next_action = "Phase approved. Use advance_to_next_phase to proceed."
        else:
            next_action = "All phases complete. Task finished."
    elif phase_status == "UNDER_REVIEW":
        next_action = "Phase under review. Wait for reviewer verdicts."
    elif phase_status == "AWAITING_REVIEW":
        next_action = "Phase awaiting review. Use trigger_agentic_review to spawn reviewers."
    elif phase_status == "REVISING":
        if all_done:
            next_action = "Revisions complete. Use submit_phase_for_review to re-submit."
        else:
            next_action = f"Revisions in progress. {int(counts.get('pending', 0))} agents still working."
    elif ready_for_review:
        next_action = "All agents done. Use submit_phase_for_review to request review."
    elif int(counts.get("pending", 0)) > 0:
        next_action = f"Phase in progress. {int(counts.get('pending', 0))} agents still working."
    else:
        next_action = "No agents deployed yet. Use deploy_opus_agent to start."

    return json.dumps(
        {
            "success": True,
            "task_id": task_id,
            "phase": {
                "name": current_phase.get("name"),
                "status": phase_status,
                "index": current_idx,
                "total_phases": len(phases),
            },
            "agents": {
                "total": int(counts.get("total", 0)),
                "completed": int(counts.get("completed", 0)),
                "pending": int(counts.get("pending", 0)),
                "failed": int(counts.get("failed", 0)),
            },
            "pending_agents": [a for a in (phase_state.get("agents", []) or []) if a.get("status") not in state_db.AGENT_TERMINAL_STATUSES],
            "all_agents_done": all_done,
            "ready_for_review": ready_for_review,
            "next_action": next_action,
        },
        indent=2,
    )

    with LockedRegistryFile(registry_path) as (registry, f):
        phases = registry.get('phases', [])
        current_idx = registry.get('current_phase_index', 0)

        if not phases or current_idx >= len(phases):
            return json.dumps({"success": False, "error": "No current phase"})

        current_phase = phases[current_idx]
        phase_id = current_phase.get('id')
        phase_status = current_phase.get('status')

        # Get all agents bound to this phase by phase_index (NOT phase_id)
        # Agents are tagged with phase_index when deployed
        phase_agents = [
            a for a in registry.get('agents', [])
            if a.get('phase_index') == current_idx
        ]

        # Categorize by status
        completed_agents = []
        pending_agents = []
        failed_agents = []

        for agent in phase_agents:
            status = agent.get('status', '')
            agent_summary = {
                "id": agent.get('id'),
                "type": agent.get('type'),
                "status": status
            }
            if status in {'completed', 'phase_completed'}:
                completed_agents.append(agent_summary)
            elif status in {'failed', 'error', 'terminated'}:
                failed_agents.append(agent_summary)
            else:
                pending_agents.append(agent_summary)

        all_done = len(pending_agents) == 0 and len(phase_agents) > 0
        ready_for_review = all_done and phase_status == 'ACTIVE'

        # Determine recommended action
        if phase_status == 'APPROVED':
            if current_idx < len(phases) - 1:
                next_action = "Phase approved. Use advance_to_next_phase to proceed."
            else:
                next_action = "All phases complete. Task finished."
        elif phase_status == 'UNDER_REVIEW':
            next_action = "Phase under review. Wait for reviewer verdicts."
        elif phase_status == 'AWAITING_REVIEW':
            next_action = "Phase awaiting review. Use trigger_agentic_review to spawn reviewers."
        elif phase_status == 'REVISING':
            if all_done:
                next_action = "Revisions complete. Use submit_phase_for_review to re-submit."
            else:
                next_action = f"Revisions in progress. {len(pending_agents)} agents still working."
        elif ready_for_review:
            next_action = "All agents done. Use submit_phase_for_review to request review."
        elif len(pending_agents) > 0:
            next_action = f"Phase in progress. {len(pending_agents)} agents still working."
        else:
            next_action = "No agents deployed yet. Use deploy_opus_agent to start."

    return json.dumps({
        "success": True,
        "task_id": task_id,
        "phase": {
            "name": current_phase.get('name'),
            "status": phase_status,
            "index": current_idx,
            "total_phases": len(phases)
        },
        "agents": {
            "total": len(phase_agents),
            "completed": len(completed_agents),
            "pending": len(pending_agents),
            "failed": len(failed_agents)
        },
        "pending_agents": pending_agents,
        "all_agents_done": all_done,
        "ready_for_review": ready_for_review,
        "next_action": next_action
    }, indent=2)


@mcp.tool()
def advance_to_next_phase(
    task_id: str,
    handover_summary: Optional[str] = None,
    key_findings: Optional[List[str]] = None,
    blockers: Optional[List[str]] = None,
    recommendations: Optional[List[str]] = None
) -> str:
    """
    Advance task to the next phase with optional handover document.

    Creates a handover document capturing the current phase's work
    before transitioning to the next phase.

    Args:
        task_id: Task to advance
        handover_summary: Summary of work done in current phase
        key_findings: Key findings/discoveries
        blockers: Any blockers encountered
        recommendations: Recommendations for next phase
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')

    with LockedRegistryFile(registry_path) as (registry, f):
        phases = registry.get('phases', [])
        current_idx = registry.get('current_phase_index', 0)

        if not phases:
            return json.dumps({"success": False, "error": "No phases defined"})

        if current_idx >= len(phases) - 1:
            return json.dumps({"success": False, "error": "Already at final phase"})

        current_phase = phases[current_idx]
        next_phase = phases[current_idx + 1]

        # CRITICAL ENFORCEMENT: Phase must already be APPROVED before advancing
        # The orchestrator CANNOT self-approve by calling this function
        # This prevents bypassing the mandatory agentic review process
        current_status = current_phase.get('status', 'PENDING')
        if current_status != 'APPROVED':
            # Generate contextual guidance for the blocked state
            if current_status == 'ACTIVE':
                next_action = "Deploy agents and wait for completion, then auto-submit will trigger"
                available_actions = [
                    "deploy_opus_agent/deploy_sonnet_agent - Add agents if needed",
                    "check_phase_progress - Check if agents are done"
                ]
            elif current_status in ['AWAITING_REVIEW', 'UNDER_REVIEW']:
                next_action = "Wait for reviewers to submit verdicts"
                available_actions = [
                    "get_review_status - Check review progress",
                    "get_phase_status - View current state"
                ]
            elif current_status == 'REJECTED':
                next_action = "Deploy agents to fix issues identified in review"
                available_actions = [
                    "get_review_status - View rejection reasons",
                    "deploy_opus_agent/deploy_sonnet_agent - Deploy fix agents"
                ]
            elif current_status == 'ESCALATED':
                next_action = "Use force approval or retry review"
                available_actions = [
                    "approve_phase_review(force_escalated=True) - Force approve",
                    "trigger_agentic_review - Retry with new reviewers"
                ]
            else:
                next_action = "Check phase status for details"
                available_actions = ["get_phase_status - View current state"]

            return json.dumps({
                "success": False,
                "error": f"PHASE_NOT_APPROVED: Cannot advance phase '{current_phase.get('name')}' with status '{current_status}'",
                "hint": "Phase must be APPROVED by reviewers before advancement. "
                        "Flow: deploy agents → agents complete → auto-submit for review → reviewers approve → then advance.",
                "current_phase": current_phase.get('name'),
                "current_status": current_status,
                "required_status": "APPROVED",
                "valid_statuses_for_advance": ["APPROVED"],
                "guidance": {
                    "current_state": f"phase_{current_status.lower()}_blocked",
                    "next_action": next_action,
                    "available_actions": available_actions,
                    "warnings": None,
                    "blocked_reason": f"Phase status is '{current_status}', must be 'APPROVED' to advance"
                }
            }, indent=2)

        # Create handover document
        handover = HandoverDocument(
            phase_id=current_phase.get('id', f"phase-{current_idx}"),
            phase_name=current_phase.get('name', f"Phase {current_idx + 1}"),
            summary=handover_summary or f"Completed {current_phase.get('name', 'phase')}",
            key_findings=key_findings or [],
            blockers=blockers or [],
            recommendations=recommendations or []
        )

        # Save handover (save_handover takes task_workspace, handover)
        save_result = save_handover(workspace, handover)
        handover_path = save_result.get('path', 'unknown')

        # Phase is already APPROVED (verified above), mark as COMPLETED and advance
        current_phase['status'] = 'COMPLETED'  # Final state after advancement
        current_phase['completed_at'] = datetime.now().isoformat()
        next_phase['status'] = 'ACTIVE'
        next_phase['started_at'] = datetime.now().isoformat()

        # Advance index
        registry['current_phase_index'] = current_idx + 1

        # Write back
        f.seek(0)
        json.dump(registry, f, indent=2)
        f.truncate()

    next_phase_name = next_phase.get('name')
    return json.dumps({
        "success": True,
        "previous_phase": current_phase.get('name'),
        "current_phase": next_phase_name,
        "phase_index": current_idx + 1,
        "handover_saved": handover_path,
        "guidance": {
            "current_state": "phase_advanced",
            "next_action": f"Deploy agents for '{next_phase_name}' phase using deploy_opus_agent/deploy_sonnet_agent",
            "available_actions": [
                f"deploy_opus_agent/deploy_sonnet_agent - Deploy agents for '{next_phase_name}'",
                "get_phase_status - View new phase requirements",
                "get_phase_handover - Review previous phase handover"
            ],
            "warnings": None,
            "blocked_reason": None,
            "context": {
                "new_phase": next_phase_name,
                "phase_index": current_idx + 1
            }
        }
    }, indent=2)


@mcp.tool()
def submit_phase_for_review(task_id: str, phase_summary: Optional[str] = None) -> str:
    """
    Submit current phase for review.

    Transitions phase from ACTIVE to AWAITING_REVIEW.
    This signals that work is complete and ready for review.
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')

    with LockedRegistryFile(registry_path) as (registry, f):
        phases = registry.get('phases', [])
        current_idx = registry.get('current_phase_index', 0)

        if not phases or current_idx >= len(phases):
            return json.dumps({"success": False, "error": "No current phase"})

        current_phase = phases[current_idx]

        # Allow submit from ACTIVE (normal flow) or REVISING (after rejection)
        if current_phase.get('status') not in ['ACTIVE', 'REVISING']:
            return json.dumps({
                "success": False,
                "error": f"Phase must be ACTIVE or REVISING to submit for review. Current: {current_phase.get('status')}"
            })

        # Count phase agents for reviewer context
        phase_agents = [a for a in registry.get('agents', []) if a.get('phase_index') == current_idx]
        completed_agents = len([a for a in phase_agents if a.get('status') == 'completed'])
        failed_agents = len([a for a in phase_agents if a.get('status') in ['failed', 'error', 'terminated']])
        phase_name = current_phase.get('name', f'Phase {current_idx + 1}')

        # Transition to AWAITING_REVIEW
        current_phase['status'] = 'AWAITING_REVIEW'
        current_phase['submitted_for_review_at'] = datetime.now().isoformat()
        current_phase['manual_submit'] = True  # Mark as manual submission
        if phase_summary:
            current_phase['review_summary'] = phase_summary

        f.seek(0)
        json.dump(registry, f, indent=2)
        f.truncate()

    # MANDATORY: Auto-spawn reviewers to prevent manual approval bypass
    # This ensures the orchestrator CANNOT submit and then manually approve
    logger.info(f"PHASE ENFORCEMENT: Manual submit_phase_for_review - auto-spawning reviewers")
    try:
        auto_review_result = _auto_spawn_phase_reviewers(
            task_id=task_id,
            phase_index=current_idx,
            phase_name=phase_name,
            completed_agents=completed_agents,
            failed_agents=failed_agents,
            workspace=workspace
        )
        logger.info(f"PHASE ENFORCEMENT: Auto-review triggered: {auto_review_result}")
    except Exception as e:
        logger.error(f"PHASE ENFORCEMENT: Failed to auto-spawn reviewers: {e}")
        # Even if reviewer spawning fails, phase is in AWAITING_REVIEW with auto_review=False
        # This will be caught by approve_phase_review which requires review completion

    return json.dumps({
        "success": True,
        "phase": phase_name,
        "status": "UNDER_REVIEW",  # Will be UNDER_REVIEW after reviewers spawn
        "message": "Phase submitted for review - agentic reviewers auto-spawned",
        "enforcement": "Reviewers will independently verify phase work. Manual approval blocked."
    }, indent=2)


@mcp.tool()
def approve_phase_review(
    task_id: str,
    reviewer_notes: Optional[str] = None,
    auto_advance: bool = True,
    force_escalated: bool = False
) -> str:
    """
    Approve the current phase review and optionally advance to next phase.

    IMPORTANT: This is BLOCKED when an auto-review is in progress.
    The system enforces agentic review - manual approval is not allowed
    once reviewers have been spawned automatically.

    EXCEPTION: If force_escalated=True AND phase is ESCALATED (all reviewers crashed),
    manual approval is allowed as an escape hatch.

    Args:
        task_id: Task ID
        reviewer_notes: Optional notes from reviewer
        auto_advance: If True, automatically advance to next phase
        force_escalated: If True, allows approval of ESCALATED phases only
    """
    # ===== CHECK FOR ESCALATED PHASE OVERRIDE =====
    if force_escalated:
        workspace = find_task_workspace(task_id)
        if not workspace:
            return json.dumps({"success": False, "error": f"Task {task_id} not found"})

        registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')

        with LockedRegistryFile(registry_path) as (registry, f):
            phases = registry.get('phases', [])
            current_idx = registry.get('current_phase_index', 0)

            if not phases or current_idx >= len(phases):
                return json.dumps({"success": False, "error": "No current phase"})

            current_phase = phases[current_idx]

            # Only allow force approval for ESCALATED phases
            if current_phase.get('status') != 'ESCALATED':
                return json.dumps({
                    "success": False,
                    "error": f"force_escalated only works for ESCALATED phases. Current status: {current_phase.get('status')}",
                    "hint": "This escape hatch is only for phases where all reviewers crashed."
                })

            # Perform forced approval
            current_phase['status'] = 'APPROVED'
            current_phase['approved_at'] = datetime.now().isoformat()
            current_phase['forced_approval'] = True
            current_phase['force_reason'] = 'ESCALATED phase - all reviewers crashed'
            if reviewer_notes:
                current_phase['reviewer_notes'] = reviewer_notes

            logger.warning(f"FORCE APPROVAL: Phase {current_idx} approved via force_escalated (all reviewers crashed)")

            # Auto-advance if requested
            advanced = False
            if auto_advance and current_idx < len(phases) - 1:
                next_phase = phases[current_idx + 1]
                next_phase['status'] = 'ACTIVE'
                next_phase['started_at'] = datetime.now().isoformat()
                registry['current_phase_index'] = current_idx + 1
                advanced = True

            f.seek(0)
            f.write(json.dumps(registry, indent=2))
            f.truncate()

        return json.dumps({
            "success": True,
            "phase_index": current_idx,
            "phase_name": current_phase.get('name'),
            "status": "APPROVED",
            "forced": True,
            "advanced_to_next": advanced,
            "next_phase_index": current_idx + 1 if advanced else None
        })

    # ===== CRITICAL PHASE ENFORCEMENT: Manual approval ALWAYS blocked =====
    # Per CLAUDE.md: "The orchestrator CANNOT: Self-approve, Skip phases, Bypass review"
    # ALL approvals must go through submit_review_verdict from reviewer agents
    return json.dumps({
        "success": False,
        "error": "BLOCKED: Manual approval is not allowed. All approvals must come from reviewer agents.",
        "enforcement": "mandatory_agentic_review",
        "hint": "Phase approvals are handled automatically by the system. "
                "Flow: agents complete → auto-submit → auto-spawn reviewers → reviewers submit verdicts → auto-approve/reject. "
                "Use get_phase_status to check current state and guidance. "
                "EXCEPTION: If phase is ESCALATED (all reviewers crashed), use force_escalated=True.",
        "next_action": "Wait for reviewer agents to complete their review and submit verdicts via submit_review_verdict."
    })

    # NOTE: The code below is unreachable but kept for reference
    # If we ever need to allow manual approval in special cases, uncomment this
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')

    with LockedRegistryFile(registry_path) as (registry, f):
        phases = registry.get('phases', [])
        current_idx = registry.get('current_phase_index', 0)

        if not phases or current_idx >= len(phases):
            return json.dumps({"success": False, "error": "No current phase"})

        current_phase = phases[current_idx]

        # ===== PHASE ENFORCEMENT: Block manual approval when auto-review active =====
        if current_phase.get('auto_review'):
            return json.dumps({
                "success": False,
                "error": "BLOCKED: This phase has an auto-review in progress. "
                         "Manual approval is not allowed. Wait for reviewer agents to submit verdicts.",
                "enforcement": "automatic_phase_control",
                "active_review_id": current_phase.get('active_review_id'),
                "hint": "Reviewer agents will automatically approve/reject this phase. "
                        "Check get_review_status for progress."
            })

        if current_phase.get('status') not in ['AWAITING_REVIEW', 'UNDER_REVIEW']:
            return json.dumps({
                "success": False,
                "error": f"Phase must be awaiting/under review. Current: {current_phase.get('status')}"
            })

        # Approve (only if not auto-review)
        current_phase['status'] = 'APPROVED'
        current_phase['approved_at'] = datetime.now().isoformat()
        current_phase['manual_approval'] = True  # Mark as manual
        if reviewer_notes:
            current_phase['reviewer_notes'] = reviewer_notes

        # Auto-advance if requested and there's a next phase
        advanced = False
        if auto_advance and current_idx < len(phases) - 1:
            next_phase = phases[current_idx + 1]
            next_phase['status'] = 'ACTIVE'
            next_phase['started_at'] = datetime.now().isoformat()
            registry['current_phase_index'] = current_idx + 1
            advanced = True

        f.seek(0)
        json.dump(registry, f, indent=2)
        f.truncate()

    return json.dumps({
        "success": True,
        "phase": current_phase.get('name'),
        "status": "APPROVED",
        "advanced_to_next": advanced,
        "new_phase_index": registry.get('current_phase_index'),
        "note": "Manual approval - consider using agentic review for better quality control"
    }, indent=2)
    """


@mcp.tool()
def reject_phase_review(
    task_id: str,
    rejection_reason: str,
    required_changes: Optional[List[str]] = None
) -> str:
    """
    Reject the current phase review, requiring revisions.

    IMPORTANT: This is BLOCKED when an auto-review is in progress.
    The system enforces agentic review - manual rejection is not allowed
    once reviewers have been spawned automatically.

    Transitions phase to REVISING status.
    """
    # ===== CRITICAL PHASE ENFORCEMENT: Manual rejection ALWAYS blocked =====
    # Per CLAUDE.md: "The orchestrator CANNOT: Self-approve, Skip phases, Bypass review"
    # ALL rejections must go through submit_review_verdict from reviewer agents
    return json.dumps({
        "success": False,
        "error": "BLOCKED: Manual rejection is not allowed. All phase decisions must come from reviewer agents.",
        "enforcement": "mandatory_agentic_review",
        "hint": "Phase rejections are handled automatically by the system. "
                "Flow: agents complete → auto-submit → auto-spawn reviewers → reviewers submit verdicts → auto-approve/reject. "
                "Use get_phase_status to check current state and guidance.",
        "next_action": "Wait for reviewer agents to complete their review and submit verdicts via submit_review_verdict."
    })

    # NOTE: The code below is unreachable but kept for reference
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')

    with LockedRegistryFile(registry_path) as (registry, f):
        phases = registry.get('phases', [])
        current_idx = registry.get('current_phase_index', 0)

        if not phases or current_idx >= len(phases):
            return json.dumps({"success": False, "error": "No current phase"})

        current_phase = phases[current_idx]

        # ===== PHASE ENFORCEMENT: Block manual rejection when auto-review active =====
        if current_phase.get('auto_review'):
            return json.dumps({
                "success": False,
                "error": "BLOCKED: This phase has an auto-review in progress. "
                         "Manual rejection is not allowed. Wait for reviewer agents to submit verdicts.",
                "enforcement": "automatic_phase_control",
                "active_review_id": current_phase.get('active_review_id'),
                "hint": "Reviewer agents will automatically approve/reject this phase. "
                        "Check get_review_status for progress."
            })

        if current_phase.get('status') not in ['AWAITING_REVIEW', 'UNDER_REVIEW']:
            return json.dumps({
                "success": False,
                "error": f"Phase must be awaiting/under review. Current: {current_phase.get('status')}"
            })

        # Reject - move to REVISING (only if not auto-review)
        current_phase['status'] = 'REVISING'
        current_phase['rejected_at'] = datetime.now().isoformat()
        current_phase['rejection_reason'] = rejection_reason
        current_phase['required_changes'] = required_changes or []
        current_phase['revision_count'] = current_phase.get('revision_count', 0) + 1
        current_phase['manual_rejection'] = True  # Mark as manual

        f.seek(0)
        json.dump(registry, f, indent=2)
        f.truncate()

    return json.dumps({
        "success": True,
        "phase": current_phase.get('name'),
        "status": "REVISING",
        "rejection_reason": rejection_reason,
        "required_changes": required_changes or [],
        "revision_count": current_phase.get('revision_count'),
        "note": "Manual rejection - consider using agentic review for better quality control"
    }, indent=2)
    """


# ============================================================================
# AGENTIC REVIEW TOOLS - Automated multi-agent review system
# ============================================================================


def _auto_spawn_phase_reviewers(
    task_id: str,
    phase_index: int,
    phase_name: str,
    completed_agents: int,
    failed_agents: int,
    workspace: str,
    num_reviewers: int = 3
) -> Dict[str, Any]:
    """
    INTERNAL: Auto-spawn reviewer agents when a phase completes.

    This is called automatically by update_agent_progress when all phase agents finish.
    It creates a review record and spawns reviewer agents without orchestrator involvement.

    Args:
        task_id: Task ID
        phase_index: Index of the phase that just completed
        phase_name: Name of the phase
        completed_agents: Number of agents that completed successfully
        failed_agents: Number of agents that failed
        workspace: Task workspace path
        num_reviewers: Number of reviewer agents to spawn (default 3)

    Returns:
        Dict with review_id, spawned agents, and status
    """
    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')

    # Create review record
    review_id = f"auto-review-{uuid.uuid4().hex[:12]}"
    review_focus = ["completeness", "correctness", "quality"]

    with LockedRegistryFile(registry_path) as (registry, f):
        phases = registry.get('phases', [])
        if phase_index >= len(phases):
            return {"success": False, "error": "Invalid phase_index"}

        current_phase = phases[phase_index]

        # Only proceed if phase is in AWAITING_REVIEW (set by update_agent_progress)
        if current_phase.get('status') != 'AWAITING_REVIEW':
            return {"success": False, "error": f"Phase not awaiting review: {current_phase.get('status')}"}

        # Create review record
        review_record = {
            "review_id": review_id,
            "phase_id": current_phase.get('id', f"phase-{phase_index}"),
            "phase_name": phase_name,
            "status": "in_progress",
            "num_reviewers": num_reviewers,
            "reviewers": [],
            "verdicts": [],
            "created_at": datetime.now().isoformat(),
            "review_focus": review_focus,
            "auto_triggered": True,  # Mark as auto-triggered
            "trigger_reason": f"All {completed_agents + failed_agents} phase agents finished ({completed_agents} completed, {failed_agents} failed)"
        }

        if 'reviews' not in registry:
            registry['reviews'] = []
        registry['reviews'].append(review_record)

        # Transition phase to UNDER_REVIEW
        current_phase['status'] = 'UNDER_REVIEW'
        current_phase['review_started_at'] = datetime.now().isoformat()
        current_phase['active_review_id'] = review_id
        current_phase['auto_review'] = True

        # Extract phase-specific deliverables and success criteria for reviewer context
        phase_deliverables = current_phase.get('deliverables', [])
        phase_success_criteria = current_phase.get('success_criteria', [])
        phase_description = current_phase.get('description', '')

        # Build OUT OF SCOPE section from future phases
        future_phases = []
        for fp_idx, fp in enumerate(phases):
            if fp_idx > phase_index:
                fp_name = fp.get('name', f'Phase {fp_idx + 1}')
                fp_desc = fp.get('description', '')
                fp_deliverables = fp.get('deliverables', [])
                future_phases.append({
                    'name': fp_name,
                    'description': fp_desc,
                    'deliverables': fp_deliverables
                })

        f.seek(0)
        json.dump(registry, f, indent=2)
        f.truncate()

    # Build phase-specific sections for reviewer prompt
    deliverables_section = ""
    if phase_deliverables:
        deliverables_list = "\n".join([f"  - {d}" for d in phase_deliverables])
        deliverables_section = f"""
═══════════════════════════════════════════════════════════════════════════════
📋 THIS PHASE'S EXPECTED DELIVERABLES (what you MUST verify):
═══════════════════════════════════════════════════════════════════════════════
{deliverables_list}

IMPORTANT: Only evaluate against THESE deliverables, not future phase work.
"""
    else:
        deliverables_section = """
📋 THIS PHASE'S EXPECTED DELIVERABLES: Not explicitly defined.
   Use get_phase_handover to see what agents produced.
"""

    success_criteria_section = ""
    if phase_success_criteria:
        criteria_list = "\n".join([f"  - {c}" for c in phase_success_criteria])
        success_criteria_section = f"""
═══════════════════════════════════════════════════════════════════════════════
✅ THIS PHASE'S SUCCESS CRITERIA (checklist for approval):
═══════════════════════════════════════════════════════════════════════════════
{criteria_list}

IMPORTANT: Only evaluate against THESE criteria. Future phase criteria are NOT your concern.
"""

    out_of_scope_section = ""
    if future_phases:
        oos_items = []
        for fp in future_phases:
            fp_line = f"  - {fp['name']}"
            if fp['description']:
                fp_line += f": {fp['description']}"
            oos_items.append(fp_line)
            if fp['deliverables']:
                for d in fp['deliverables'][:3]:  # Show first 3 deliverables
                    oos_items.append(f"      → {d}")
        oos_list = "\n".join(oos_items)
        out_of_scope_section = f"""
═══════════════════════════════════════════════════════════════════════════════
⛔ OUT OF SCOPE - DO NOT REJECT FOR THESE (they belong to future phases):
═══════════════════════════════════════════════════════════════════════════════
{oos_list}

CRITICAL: If you find issues related to future phases, do NOT mark as blocker.
          Only evaluate this phase's deliverables and success criteria.
"""

    # Build review prompt for agents with phase-specific context
    review_prompt = f"""You are an INDEPENDENT REVIEWER AGENT for phase "{phase_name}" (Task: {task_id}).

THIS IS AN AUTOMATED REVIEW - The orchestrator CANNOT bypass this review. Your verdict is binding.

PHASE SUMMARY:
- Phase: {phase_name} (index {phase_index})
- Description: {phase_description if phase_description else 'Not provided'}
- Agents completed: {completed_agents}
- Agents failed: {failed_agents}
{deliverables_section}
{success_criteria_section}
{out_of_scope_section}
YOUR MISSION: Review ONLY this phase's deliverables against ONLY this phase's success criteria.

REVIEW FOCUS AREAS: {', '.join(review_focus)}

STEP 1 - GET AGENT FINDINGS (what agents discovered/created):
```
mcp__claude-orchestrator__get_phase_handover(task_id="{task_id}", phase_index={phase_index})
```
This shows: findings, key discoveries, deliverables from this phase.

STEP 2 - GET TASK CONTEXT (if needed for overall understanding):
```
mcp__claude-orchestrator__get_real_task_status(task_id="{task_id}")
```
This shows: task description, overall context, agent statuses.

STEP 3 - CHECK AGENT OUTPUTS (if needed):
```
mcp__claude-orchestrator__get_agent_output(task_id="{task_id}", agent_id="<agent_id>", response_format="recent")
```
Use this to see what specific agents did.

STEP 4 - VERIFY ACTUAL DELIVERABLES:
- If files were created, use Read tool to check them
- If code was written, verify it exists and looks correct
- If a server was implemented, test the endpoints
- Workspace location: {workspace}

CRITICAL EVALUATION RULES:
1. ONLY evaluate against THIS phase's deliverables and success criteria
2. Do NOT reject for work belonging to future phases (see OUT OF SCOPE above)
3. IGNORE registry progress percentages - they are unreliable
4. FOCUS ON: Do the phase deliverables exist and meet phase success criteria?

AFTER REVIEWING, SUBMIT YOUR VERDICT:
```
mcp__claude-orchestrator__submit_review_verdict(
    task_id="{task_id}",
    review_id="{review_id}",
    verdict="approved" | "rejected" | "needs_revision",
    findings=[{{"type": "issue|suggestion|blocker|praise", "severity": "critical|high|medium|low", "message": "..."}}],
    reviewer_notes="Summary of what you verified against THIS phase's criteria"
)
```

VERDICT GUIDE:
- "approved": This phase's deliverables exist and meet THIS phase's success criteria
- "needs_revision": Deliverables exist but have minor issues within THIS phase's scope
- "rejected": Critical deliverables for THIS phase are missing or broken

═══════════════════════════════════════════════════════════════════════════════
⚡ MANDATORY: YOU MUST SUBMIT YOUR VERDICT - REVIEW IS NOT COMPLETE WITHOUT IT ⚡
═══════════════════════════════════════════════════════════════════════════════

Your job is ONLY COMPLETE when you call submit_review_verdict.

IF YOU DO NOT SUBMIT YOUR VERDICT:
- The phase will be STUCK waiting for your review
- The orchestrator cannot proceed
- Your review is WASTED
- The system will eventually mark you as failed

REVIEW THIS PHASE'S DELIVERABLES AND SUBMIT YOUR VERDICT NOW!
═══════════════════════════════════════════════════════════════════════════════
"""

    # Spawn reviewer agents
    spawned_agents = []
    for i in range(num_reviewers):
        # CRITICAL FIX (v2): Agent types must be unique per-REVIEW, not just per-phase
        # The find_existing_agent check blocks spawning if same agent_type exists with status 'working'
        # When a phase needs re-review, old reviewers may still have status 'working' (before the status fix)
        # Include review_id prefix to guarantee uniqueness across multiple reviews of the same phase
        review_prefix = review_id.split('-')[-1][:8]  # e.g., "auto-review-abc123..." -> "abc123"
        agent_type = f"reviewer-{review_prefix}-{i+1}"
        try:
            # Use the internal deployment function with a special phase_index (-1 = reviewer)
            # Reviewers don't belong to any phase - they review phases
            result = deploy_claude_tmux_agent(
                task_id=task_id,
                agent_type=agent_type,
                prompt=review_prompt,
                parent="orchestrator",
                phase_index=-1  # -1 indicates reviewer agent (not part of any phase)
            )
            if result.get('success'):
                agent_id = result.get('agent_id')
                spawned_agents.append(agent_id)

                # Update review record with reviewer info
                with LockedRegistryFile(registry_path) as (reg, f2):
                    for rev in reg.get('reviews', []):
                        if rev.get('review_id') == review_id:
                            rev['reviewers'].append({
                                "agent_id": agent_id,
                                "agent_type": agent_type,
                                "spawned_at": datetime.now().isoformat(),
                                "status": "reviewing"
                            })
                            break
                    f2.seek(0)
                    json.dump(reg, f2, indent=2)
                    f2.truncate()

                logger.info(f"AUTO-PHASE-ENFORCEMENT: Spawned reviewer {agent_id}")
            else:
                # CRITICAL: Log when deployment fails (was silently ignored before, causing 0-reviewer mystery)
                logger.error(f"AUTO-PHASE-ENFORCEMENT: Failed to spawn reviewer {i+1}: {result.get('error', 'Unknown error')}")
        except Exception as e:
            logger.error(f"AUTO-PHASE-ENFORCEMENT: Failed to spawn reviewer {i+1}: {e}")

    return {
        "success": True,
        "review_id": review_id,
        "phase": phase_name,
        "phase_index": phase_index,
        "status": "UNDER_REVIEW",
        "num_reviewers": num_reviewers,
        "spawned_agents": spawned_agents,
        "auto_triggered": True,
        "message": f"Auto-spawned {len(spawned_agents)} reviewer agents"
    }


@mcp.tool()
def trigger_agentic_review(
    task_id: str,
    num_reviewers: int = 2,
    review_focus: Optional[List[str]] = None
) -> str:
    """
    Trigger automated agentic review by spawning reviewer agents.

    This deploys specialized reviewer agents that independently examine
    the phase work and submit verdicts. Use this instead of manual
    approve/reject for automated quality gates.

    Flow:
        1. Phase must be in AWAITING_REVIEW state
        2. Spawns num_reviewers agents with review prompts
        3. Each agent reviews and calls submit_review_verdict
        4. System aggregates verdicts and auto-transitions phase

    Args:
        task_id: Task ID containing the phase to review
        num_reviewers: Number of reviewer agents to spawn (1-5, default 2)
        review_focus: Optional focus areas like ["security", "performance", "code_quality"]

    Returns:
        Dict with review_id, spawned agent IDs, and phase status
    """
    from orchestrator.review import create_review_record, ReviewConfig

    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    # Clamp num_reviewers
    num_reviewers = max(1, min(5, num_reviewers))

    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')

    with LockedRegistryFile(registry_path) as (registry, f):
        phases = registry.get('phases', [])
        current_idx = registry.get('current_phase_index', 0)

        if not phases or current_idx >= len(phases):
            return json.dumps({"success": False, "error": "No current phase"})

        current_phase = phases[current_idx]
        phase_id = current_phase.get('id', f"phase-{current_idx}")
        phase_name = current_phase.get('name', 'Unknown')

        phase_status = current_phase.get('status')
        if phase_status not in ['AWAITING_REVIEW', 'ESCALATED']:
            return json.dumps({
                "success": False,
                "error": f"Phase must be AWAITING_REVIEW or ESCALATED to trigger review. Current: {phase_status}"
            })

        # If phase was ESCALATED, log the retry
        if phase_status == 'ESCALATED':
            logger.info(f"Retrying review for ESCALATED phase {current_idx} in task {task_id}")
            current_phase['escalation_retry_at'] = datetime.now().isoformat()
            current_phase['escalation_retry_reason'] = 'Manual retry via trigger_agentic_review'

        # Create review record
        review_id = f"review-{uuid.uuid4().hex[:12]}"
        review_record = {
            "review_id": review_id,
            "phase_id": phase_id,
            "phase_name": phase_name,
            "status": "in_progress",
            "num_reviewers": num_reviewers,
            "reviewers": [],
            "verdicts": [],
            "created_at": datetime.now().isoformat(),
            "review_focus": review_focus or ["completeness", "correctness", "quality"]
        }

        # Initialize reviews list if not exists
        if 'reviews' not in registry:
            registry['reviews'] = []
        registry['reviews'].append(review_record)

        # Transition phase to UNDER_REVIEW
        current_phase['status'] = 'UNDER_REVIEW'
        current_phase['review_started_at'] = datetime.now().isoformat()
        current_phase['active_review_id'] = review_id

        f.seek(0)
        json.dump(registry, f, indent=2)
        f.truncate()

    # Build review prompt for agents
    focus_areas = review_focus or ["completeness", "correctness", "quality"]
    current_phase_idx = registry.get('current_phase_index', 0)
    review_prompt = f"""You are a REVIEWER AGENT for phase "{phase_name}" (Task: {task_id}).

YOUR MISSION: Review the ACTUAL DELIVERABLES produced in this phase and submit a verdict.

REVIEW FOCUS AREAS: {', '.join(focus_areas)}

STEP 1 - GET TASK CONTEXT (use MCP tools):
```
mcp__claude-orchestrator__get_real_task_status(task_id="{task_id}")
```
This shows: task description, expected deliverables, success criteria, agent statuses.

STEP 2 - GET AGENT FINDINGS (what agents discovered/created):
```
mcp__claude-orchestrator__get_phase_handover(task_id="{task_id}", phase_index={current_phase_idx})
```
This shows: findings, key discoveries, deliverables from this phase.

STEP 3 - CHECK AGENT OUTPUTS (if needed):
```
mcp__claude-orchestrator__get_agent_output(task_id="{task_id}", agent_id="<agent_id>", response_format="recent")
```
Use this to see what specific agents did.

STEP 4 - VERIFY ACTUAL DELIVERABLES:
- If files were created, use Read tool to check them
- If code was written, verify it exists and looks correct
- If a server was implemented, test the endpoints with curl/fetch
- Workspace location: {workspace}

CRITICAL EVALUATION RULES:
1. IGNORE registry progress percentages - they are unreliable
2. FOCUS ON: Do the deliverables exist and work?
3. Check success_criteria from task status - are they met?

AFTER REVIEWING, SUBMIT YOUR VERDICT:
```
mcp__claude-orchestrator__submit_review_verdict(
    task_id="{task_id}",
    review_id="{review_id}",
    verdict="approved" | "rejected" | "needs_revision",
    findings=[{{"type": "issue|suggestion|blocker|praise", "severity": "critical|high|medium|low", "message": "..."}}],
    reviewer_notes="Summary of what you verified"
)
```

VERDICT GUIDE:
- "approved": Deliverables exist and meet success criteria
- "needs_revision": Deliverables exist but have minor issues
- "rejected": Critical deliverables missing or fundamentally broken

═══════════════════════════════════════════════════════════════════════════════
⚡ MANDATORY: YOU MUST SUBMIT YOUR VERDICT - REVIEW IS NOT COMPLETE WITHOUT IT ⚡
═══════════════════════════════════════════════════════════════════════════════

Your job is ONLY COMPLETE when you call submit_review_verdict.

IF YOU DO NOT SUBMIT YOUR VERDICT:
- The phase will be STUCK waiting for your review
- The orchestrator cannot proceed
- Your review is WASTED
- The system will eventually mark you as failed

REVIEW THE DELIVERABLES AND SUBMIT YOUR VERDICT NOW!
═══════════════════════════════════════════════════════════════════════════════
"""

    # Spawn reviewer agents
    spawned_agents = []
    for i in range(num_reviewers):
        # CRITICAL FIX (v2): Agent types must be unique per-REVIEW, not just per-phase
        # Include review_id prefix to guarantee uniqueness across multiple reviews
        review_prefix = review_id.split('-')[-1][:8]  # e.g., "review-abc123..." -> "abc123"
        agent_type = f"reviewer-{review_prefix}-{i+1}"
        try:
            # Use the internal deployment function (not MCP-decorated)
            result = deploy_claude_tmux_agent(
                task_id=task_id,
                agent_type=agent_type,
                prompt=review_prompt,
                parent="orchestrator"
            )
            if result.get('success'):
                agent_id = result.get('agent_id')
                spawned_agents.append(agent_id)

                # Update review record with reviewer info
                with LockedRegistryFile(registry_path) as (reg, f2):
                    for rev in reg.get('reviews', []):
                        if rev.get('review_id') == review_id:
                            rev['reviewers'].append({
                                "agent_id": agent_id,
                                "agent_type": agent_type,
                                "spawned_at": datetime.now().isoformat(),
                                "status": "reviewing"
                            })
                            break
                    f2.seek(0)
                    json.dump(reg, f2, indent=2)
                    f2.truncate()
            else:
                # Log when deployment fails (was silently ignored before)
                logger.error(f"Failed to spawn reviewer {i+1}: {result.get('error', 'Unknown error')}")
        except Exception as e:
            logger.error(f"Failed to spawn reviewer {i+1}: {e}")

    return json.dumps({
        "success": True,
        "review_id": review_id,
        "phase": phase_name,
        "status": "UNDER_REVIEW",
        "num_reviewers": num_reviewers,
        "spawned_agents": spawned_agents,
        "message": f"Spawned {len(spawned_agents)} reviewer agents"
    }, indent=2)


@mcp.tool()
def submit_review_verdict(
    task_id: str,
    review_id: str,
    verdict: str,
    findings: List[Dict[str, Any]],
    reviewer_notes: Optional[str] = None
) -> str:
    """
    Submit a review verdict (called by reviewer agents).

    After examining the phase work, reviewer agents call this to submit
    their verdict. When all reviewers have submitted, the system
    automatically aggregates and finalizes the review.

    Args:
        task_id: Task ID
        review_id: Review ID from trigger_agentic_review
        verdict: "approved", "rejected", or "needs_revision"
        findings: List of findings, each with:
            - type: "issue", "suggestion", "blocker", or "praise"
            - severity: "critical", "high", "medium", or "low"
            - message: Description of the finding
        reviewer_notes: Optional summary notes

    Returns:
        Dict with submission status and review progress
    """
    from orchestrator.review import REVIEW_VERDICTS, calculate_aggregate_verdict

    # Validate verdict
    if verdict not in REVIEW_VERDICTS:
        return json.dumps({
            "success": False,
            "error": f"Invalid verdict '{verdict}'. Must be: approved, rejected, needs_revision"
        })

    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')

    with LockedRegistryFile(registry_path) as (registry, f):
        # Find the review record
        reviews = registry.get('reviews', [])
        review_record = None
        for rev in reviews:
            if rev.get('review_id') == review_id:
                review_record = rev
                break

        if not review_record:
            return json.dumps({
                "success": False,
                "error": f"Review {review_id} not found"
            })

        # Record the verdict
        review_record['verdicts'].append({
            "verdict": verdict,
            "findings": findings,
            "reviewer_notes": reviewer_notes or "",
            "submitted_at": datetime.now().isoformat()
        })

        # CRITICAL FIX: Update reviewer agent status to "completed"
        # Without this, old reviewers stay "working" and block new reviewer spawns
        # due to find_existing_agent deduplication check
        for agent in registry.get('agents', []):
            # Find reviewer agents for this review (check if type starts with review prefix pattern)
            # Also match old-style phase-based reviewers
            if agent.get('status') in ['working', 'running']:
                agent_type = agent.get('type', '')
                # Match both old format (phase0-reviewer-1) and new format (review-xxx-reviewer-1)
                is_reviewer = 'reviewer' in agent_type.lower()
                if is_reviewer:
                    # Check if this agent is assigned to this review
                    for reviewer in review_record.get('reviewers', []):
                        if reviewer.get('agent_id') == agent.get('id'):
                            # CRITICAL FIX: Decrement active_count when marking reviewer as completed
                            # Agent is transitioning from active status (working/running) to terminal (completed)
                            registry['active_count'] = max(0, registry.get('active_count', 0) - 1)
                            registry['completed_count'] = registry.get('completed_count', 0) + 1

                            agent['status'] = 'completed'
                            agent['completed_at'] = datetime.now().isoformat()
                            agent['final_verdict'] = verdict
                            logger.info(f"REVIEWER STATUS UPDATE: {agent.get('id')} marked completed after verdict submission. Active count: {registry['active_count']}")
                            break

        # Check if all reviewers have submitted
        num_expected = review_record.get('num_reviewers', 1)
        num_submitted = len(review_record['verdicts'])
        all_submitted = num_submitted >= num_expected

        result_info = {
            "success": True,
            "review_id": review_id,
            "verdict_submitted": verdict,
            "findings_count": len(findings),
            "reviewers_submitted": num_submitted,
            "reviewers_expected": num_expected,
            "all_submitted": all_submitted
        }

        # Check for dead/failed reviewers - if some are dead, we can proceed with partial verdicts
        should_finalize = all_submitted
        dead_reviewers = []
        if not all_submitted and num_submitted > 0:
            # Check if remaining reviewers are dead
            reviewer_agent_ids = [r.get('agent_id') for r in review_record.get('reviewers', [])]
            submitted_reviewer_ids = [v.get('reviewer_agent_id') for v in review_record.get('verdicts', [])]

            for agent in registry.get('agents', []):
                agent_id = agent.get('id')
                if agent_id in reviewer_agent_ids and agent_id not in submitted_reviewer_ids:
                    # This reviewer hasn't submitted yet
                    if agent.get('status') in ['failed', 'error', 'terminated', 'killed']:
                        dead_reviewers.append(agent_id)

            # If all non-submitted reviewers are dead, proceed with partial verdicts
            remaining_alive = num_expected - num_submitted - len(dead_reviewers)
            if remaining_alive == 0 and num_submitted > 0:
                logger.warning(f"Proceeding with partial verdicts: {num_submitted}/{num_expected} submitted, {len(dead_reviewers)} reviewers dead")
                should_finalize = True
                result_info['partial_verdict'] = True
                result_info['dead_reviewers'] = dead_reviewers

        # If all reviewers submitted (or dead), aggregate and finalize
        if should_finalize:
            # Aggregate verdicts
            all_verdicts = [v['verdict'] for v in review_record['verdicts']]
            all_findings = []
            for v in review_record['verdicts']:
                all_findings.extend(v.get('findings', []))

            # Simple aggregation: any rejection = rejected, any needs_revision = needs_revision
            if 'rejected' in all_verdicts:
                final_verdict = 'rejected'
            elif 'needs_revision' in all_verdicts:
                final_verdict = 'needs_revision'
            else:
                final_verdict = 'approved'

            review_record['status'] = 'completed'
            review_record['final_verdict'] = final_verdict
            review_record['completed_at'] = datetime.now().isoformat()

            # Apply verdict to phase
            phases = registry.get('phases', [])
            current_idx = registry.get('current_phase_index', 0)
            if current_idx < len(phases):
                current_phase = phases[current_idx]

                if final_verdict == 'approved':
                    current_phase['status'] = 'APPROVED'
                    current_phase['approved_at'] = datetime.now().isoformat()

                    # Auto-advance to next phase if not final
                    if current_idx < len(phases) - 1:
                        next_phase = phases[current_idx + 1]
                        next_phase['status'] = 'ACTIVE'
                        next_phase['started_at'] = datetime.now().isoformat()
                        registry['current_phase_index'] = current_idx + 1
                        result_info['advanced_to_phase'] = next_phase.get('name')
                else:
                    current_phase['status'] = 'REVISING'
                    current_phase['revision_required_at'] = datetime.now().isoformat()
                    current_phase['revision_count'] = current_phase.get('revision_count', 0) + 1

            result_info['final_verdict'] = final_verdict
            result_info['review_completed'] = True
            result_info['phase_status'] = current_phase.get('status') if current_idx < len(phases) else None

        f.seek(0)
        json.dump(registry, f, indent=2)
        f.truncate()

    return json.dumps(result_info, indent=2)


@mcp.tool()
def get_review_status(task_id: str, review_id: Optional[str] = None) -> str:
    """
    Get status of agentic review(s) for a task.

    Args:
        task_id: Task ID
        review_id: Optional specific review ID. If None, returns all reviews.

    Returns:
        Dict with review status, verdicts submitted, and final outcome
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        registry = json.load(f)

    reviews = registry.get('reviews', [])

    if review_id:
        # Find specific review
        for rev in reviews:
            if rev.get('review_id') == review_id:
                return json.dumps({
                    "success": True,
                    "review": rev
                }, indent=2)
        return json.dumps({"success": False, "error": f"Review {review_id} not found"})

    # Return all reviews
    return json.dumps({
        "success": True,
        "total_reviews": len(reviews),
        "reviews": reviews
    }, indent=2)


@mcp.tool()
def abort_stalled_review(
    task_id: str,
    review_id: str,
    reason: str = "Reviewer(s) crashed or stalled"
) -> str:
    """
    Abort a stalled review when reviewer(s) crash or fail to submit verdicts.

    Use this when:
    - A reviewer agent crashes without submitting a verdict
    - Review is stuck in "in_progress" state for too long
    - Need to re-spawn reviewers or proceed differently

    This will:
    1. Mark the review as "aborted"
    2. Return the phase to ACTIVE or REVISING state (can re-submit for review)
    3. Kill any still-running reviewer agents

    Args:
        task_id: Task ID
        review_id: The review ID to abort
        reason: Reason for aborting the review

    Returns:
        Status of the abort operation
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')

    killed_agents = []

    with LockedRegistryFile(registry_path) as (registry, f):
        reviews = registry.get('reviews', [])

        # Find the review
        target_review = None
        for rev in reviews:
            if rev.get('review_id') == review_id:
                target_review = rev
                break

        if not target_review:
            return json.dumps({"success": False, "error": f"Review {review_id} not found"})

        if target_review.get('status') == 'completed':
            return json.dumps({
                "success": False,
                "error": "Cannot abort a completed review",
                "hint": "Use submit_phase_for_review to start a new review cycle"
            })

        # Mark review as aborted
        target_review['status'] = 'aborted'
        target_review['aborted_at'] = datetime.now().isoformat()
        target_review['abort_reason'] = reason
        target_review['verdicts_received'] = len(target_review.get('verdicts', []))

        # Find and return phase to appropriate state
        phases = registry.get('phases', [])
        current_idx = registry.get('current_phase_index', 0)

        if current_idx < len(phases):
            current_phase = phases[current_idx]
            if current_phase.get('active_review_id') == review_id or current_phase.get('status') == 'ESCALATED':
                # Determine target state based on current phase status
                current_status = current_phase.get('status')

                if current_status == 'ESCALATED':
                    # ESCALATED phases go to AWAITING_REVIEW so they can be retried
                    current_phase['status'] = 'AWAITING_REVIEW'
                    logger.info(f"Phase {current_idx} reset from ESCALATED to AWAITING_REVIEW")
                elif current_phase.get('revision_count', 0) > 0:
                    # Re-reviews go to REVISING
                    current_phase['status'] = 'REVISING'
                else:
                    # Normal abort goes to ACTIVE
                    current_phase['status'] = 'ACTIVE'

                current_phase['review_aborted_at'] = datetime.now().isoformat()
                current_phase['last_abort_reason'] = reason

        # Kill any running reviewer agents from this review
        reviewer_agent_ids = [r.get('agent_id') for r in target_review.get('reviewers', [])]
        for agent in registry.get('agents', []):
            if agent.get('id') in reviewer_agent_ids and agent.get('status') in ['running', 'working']:
                tmux_session = agent.get('tmux_session')
                if tmux_session:
                    try:
                        subprocess.run(
                            ['tmux', 'kill-session', '-t', tmux_session],
                            capture_output=True, timeout=5
                        )
                        killed_agents.append(agent.get('id'))
                        agent['status'] = 'terminated'
                        agent['terminated_reason'] = f"Review aborted: {reason}"
                        if registry.get('active_count', 0) > 0:
                            registry['active_count'] -= 1
                    except Exception as e:
                        logger.warning(f"Failed to kill reviewer {agent.get('id')}: {e}")

        f.seek(0)
        json.dump(registry, f, indent=2)
        f.truncate()

    return json.dumps({
        "success": True,
        "review_id": review_id,
        "status": "aborted",
        "reason": reason,
        "verdicts_received_before_abort": target_review.get('verdicts_received', 0),
        "killed_reviewers": killed_agents,
        "phase_returned_to": "REVISING" if phases[current_idx].get('revision_count', 0) > 0 else "ACTIVE",
        "next_action": "Use submit_phase_for_review to spawn new reviewers, or deploy fix agents first"
    }, indent=2)


@mcp.tool()
def get_phase_handover(task_id: str, phase_index: Optional[int] = None) -> str:
    """
    Get handover document for a phase.

    Args:
        task_id: Task ID
        phase_index: Phase index (defaults to previous phase)
    """
    from orchestrator.handover import get_handover_path

    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
    with open(registry_path, 'r') as f:
        registry = json.load(f)

    phases = registry.get('phases', [])
    current_idx = registry.get('current_phase_index', 0)
    target_idx = phase_index if phase_index is not None else current_idx - 1

    if target_idx < 0:
        return json.dumps({"success": False, "error": "No previous phase handover exists"})

    if target_idx >= len(phases):
        return json.dumps({"success": False, "error": f"Phase index {target_idx} out of range"})

    # Get phase_id from phases list
    phase_id = phases[target_idx].get('id', f"phase-{target_idx}")
    handover_path = get_handover_path(workspace, phase_id)

    if not os.path.exists(handover_path):
        return json.dumps({
            "success": False,
            "error": f"No handover found for phase {target_idx} ({phase_id})"
        })

    # load_handover takes (task_workspace, phase_id)
    handover = load_handover(workspace, phase_id)
    if not handover:
        return json.dumps({
            "success": False,
            "error": f"Failed to parse handover for phase {target_idx}"
        })
    markdown = format_handover_markdown(handover)

    return json.dumps({
        "success": True,
        "phase_index": target_idx,
        "handover": {
            "phase_id": handover.phase_id,
            "phase_name": handover.phase_name,
            "summary": handover.summary,
            "key_findings": handover.key_findings,
            "blockers": handover.blockers,
            "recommendations": handover.recommendations
        },
        "markdown": markdown
    }, indent=2)


@mcp.tool()
def get_health_status(task_id: Optional[str] = None) -> str:
    """
    Get health monitoring status for a task or all tasks.

    Args:
        task_id: Optional task ID. If None, returns overall daemon status.

    Returns:
        Health status information including daemon status and agent health.
    """
    workspace_base = resolve_workspace_variables(WORKSPACE_BASE)
    daemon = get_health_daemon(workspace_base)

    if task_id:
        # Get specific task health status
        workspace = find_task_workspace(task_id)
        if not workspace:
            return json.dumps({"success": False, "error": f"Task {task_id} not found"})

        registry_path = os.path.join(workspace, 'AGENT_REGISTRY.json')
        if not os.path.exists(registry_path):
            return json.dumps({"success": False, "error": f"Registry not found for task {task_id}"})

        try:
            with open(registry_path, 'r') as f:
                registry = json.load(f)

            agents = registry.get('agents', [])
            health_info = {
                "success": True,
                "task_id": task_id,
                "agents": [],
                "daemon_monitoring": task_id in daemon.monitored_tasks
            }

            for agent in agents:
                agent_health = {
                    "id": agent['id'],
                    "status": agent['status'],
                    "healthy": agent['status'] not in ['failed', 'error', 'terminated']
                }

                if 'health_check_failure' in agent:
                    agent_health['health_issue'] = agent['health_check_failure']

                if 'failed_at' in agent:
                    agent_health['failed_at'] = agent['failed_at']
                    agent_health['failure_reason'] = agent.get('failure_reason', 'Unknown')

                health_info['agents'].append(agent_health)

            # Add daemon stats
            health_info['daemon_status'] = daemon.get_status() if daemon else {"running": False}

            return json.dumps(health_info, indent=2)

        except Exception as e:
            return json.dumps({"success": False, "error": f"Failed to get health status: {str(e)}"})

    else:
        # Return overall daemon status
        daemon_status = daemon.get_status() if daemon else {"running": False}
        return json.dumps({
            "success": True,
            "daemon_status": daemon_status,
            "monitored_tasks": list(daemon.monitored_tasks) if daemon else []
        }, indent=2)


@mcp.tool()
def trigger_health_scan(task_id: Optional[str] = None) -> str:
    """
    Trigger an immediate health scan.

    Args:
        task_id: Optional task ID to scan. If None, scans all tasks.

    Returns:
        Status of the scan trigger request.
    """
    workspace_base = resolve_workspace_variables(WORKSPACE_BASE)
    daemon = get_health_daemon(workspace_base)

    if not daemon or not daemon.is_running:
        # Start daemon if not running
        if not daemon:
            daemon = get_health_daemon(workspace_base)
        if not daemon.is_running:
            daemon.start()

        return json.dumps({
            "success": True,
            "message": "Health daemon was not running, started it and triggered scan",
            "daemon_status": daemon.get_status()
        }, indent=2)

    # Trigger scan
    success = daemon.trigger_scan()

    return json.dumps({
        "success": success,
        "message": "Health scan triggered" if success else "Failed to trigger scan",
        "daemon_status": daemon.get_status()
    }, indent=2)


def cleanup_dead_agents_from_global_registry() -> Dict[str, Any]:
    """
    Scan the global registry and clean up agents with dead tmux sessions.

    This function:
    1. Reads all agents from the global registry
    2. Checks if their tmux sessions are still running
    3. Marks agents with dead tmux sessions as 'failed'
    4. Decrements active_agents counter for each dead agent found

    Returns:
        Dict with cleanup statistics
    """
    workspace_base = resolve_workspace_variables(WORKSPACE_BASE)
    global_reg_path = get_global_registry_path(workspace_base)

    if not os.path.exists(global_reg_path):
        return {"success": False, "error": "Global registry not found"}

    # Get list of running tmux sessions
    try:
        result = subprocess.run(
            ['tmux', 'list-sessions', '-F', '#{session_name}'],
            capture_output=True,
            text=True,
            timeout=5
        )
        running_sessions = set(result.stdout.strip().split('\n')) if result.returncode == 0 else set()
    except Exception as e:
        logger.warning(f"Failed to list tmux sessions: {e}")
        running_sessions = set()

    dead_agents = []
    cleaned_count = 0
    already_terminal_count = 0
    still_running_count = 0
    missing_tmux_field = 0

    active_statuses = {'running', 'working', 'blocked'}
    terminal_statuses = {'completed', 'failed', 'error', 'terminated', 'killed'}

    try:
        with LockedRegistryFile(global_reg_path) as (global_reg, f):
            agents = global_reg.get('agents', {})

            for agent_id, agent_data in agents.items():
                status = agent_data.get('status')
                tmux_session = agent_data.get('tmux_session')

                # Skip if already in terminal state
                if status in terminal_statuses:
                    already_terminal_count += 1
                    continue

                # No tmux session field - legacy agent without status tracking
                if not tmux_session:
                    # Mark as failed if it has no status or active status but no tmux session
                    if status is None or status in active_statuses:
                        agent_data['status'] = 'failed'
                        agent_data['failed_at'] = datetime.now().isoformat()
                        agent_data['failure_reason'] = 'Global registry cleanup: no tmux session tracked'
                        dead_agents.append(agent_id)
                        cleaned_count += 1
                    missing_tmux_field += 1
                    continue

                # Check if tmux session is running
                if tmux_session in running_sessions:
                    still_running_count += 1
                    continue

                # Tmux session is dead - mark agent as failed
                previous_status = agent_data.get('status')
                agent_data['status'] = 'failed'
                agent_data['failed_at'] = datetime.now().isoformat()
                agent_data['failure_reason'] = f'Global registry cleanup: tmux session dead ({tmux_session})'

                # Decrement active_agents if was in active status or had no status (was counted as active)
                if previous_status is None or previous_status in active_statuses:
                    global_reg['active_agents'] = max(0, global_reg.get('active_agents', 0) - 1)

                dead_agents.append(agent_id)
                cleaned_count += 1
                logger.info(f"Cleaned up dead agent: {agent_id} (tmux: {tmux_session}, prev_status: {previous_status})")

            # Recalculate active_agents to fix any counter drift
            actual_active = sum(1 for a in agents.values() if a.get('status') in active_statuses)
            counter_drift = global_reg.get('active_agents', 0) - actual_active
            if counter_drift != 0:
                logger.warning(f"Active agents counter drift detected: counter={global_reg.get('active_agents', 0)}, actual={actual_active}, drift={counter_drift}")
                global_reg['active_agents'] = actual_active

            # Write back if any changes
            if cleaned_count > 0 or counter_drift != 0:
                f.seek(0)
                f.write(json.dumps(global_reg, indent=2))
                f.truncate()
                logger.info(f"Global registry cleanup: {cleaned_count} dead agents marked as failed, active_agents corrected to: {global_reg.get('active_agents', 0)}")

        return {
            "success": True,
            "cleaned_count": cleaned_count,
            "counter_drift_fixed": counter_drift if counter_drift != 0 else None,
            "active_agents_after": actual_active,
            "still_running": still_running_count,
            "already_terminal": already_terminal_count,
            "missing_tmux_field": missing_tmux_field,
            "dead_agents": dead_agents[:20],  # Limit to first 20 for readability
            "running_sessions_detected": len(running_sessions),
            "message": f"Cleaned up {cleaned_count} dead agents from global registry" + (f", fixed counter drift of {counter_drift}" if counter_drift != 0 else "")
        }

    except Exception as e:
        logger.error(f"Global registry cleanup failed: {e}")
        return {"success": False, "error": str(e)}


def startup_global_registry_cleanup():
    """
    Run global registry cleanup on MCP server startup.
    This ensures stale agents from previous sessions are properly marked.
    """
    logger.info("Running startup global registry cleanup...")
    result = cleanup_dead_agents_from_global_registry()
    if result.get('success'):
        logger.info(f"Startup cleanup complete: {result.get('cleaned_count', 0)} dead agents cleaned up")
    else:
        logger.warning(f"Startup cleanup had issues: {result.get('error', 'unknown')}")
    return result


if __name__ == "__main__":
    # Run startup validation before serving
    startup_registry_validation()

    # Run global registry cleanup to mark dead agents from previous sessions
    startup_global_registry_cleanup()

    # Start health monitoring daemon
    try:
        workspace_base = resolve_workspace_variables(WORKSPACE_BASE)
        daemon = get_health_daemon(workspace_base)
        daemon.start()
        logger.info("Health monitoring daemon started during server initialization")
    except Exception as e:
        logger.error(f"Failed to start health daemon: {e}")
        # Non-fatal - server can still run without health monitoring

    try:
        mcp.run()
    finally:
        # Clean shutdown of health daemon
        try:
            stop_health_daemon()
            logger.info("Health monitoring daemon stopped cleanly")
        except Exception as e:
            logger.error(f"Error stopping health daemon: {e}")
