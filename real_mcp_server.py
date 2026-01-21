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
    format_previous_phase_handover,  # Legacy fallback
)

# Context accumulator (Jan 2026 - replaces filesystem-based handover)
from orchestrator.context_accumulator import (
    build_task_context_accumulator,
    format_accumulated_context,
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
# PEER CONTEXT HELPER (Auto-included in progress/finding responses)
# ============================================================================

def _get_peer_context(workspace: str, exclude_agent_id: str, max_progress: int = 3, max_findings: int = 3) -> Dict[str, Any]:
    """
    Fetch latest progress updates and findings from OTHER agents.

    This is automatically included in update_agent_progress and report_agent_finding
    responses so agents stay aware of peer activity without explicit get_task_findings calls.

    Args:
        workspace: Task workspace path
        exclude_agent_id: The calling agent's ID (to exclude from results)
        max_progress: Max number of peer progress updates to return
        max_findings: Max number of peer findings to return

    Returns:
        Dict with peer_progress and peer_findings lists
    """
    peer_progress = []
    peer_findings = []

    # Collect progress from other agents
    progress_dir = f"{workspace}/progress"
    if os.path.exists(progress_dir):
        all_progress = []
        for file in os.listdir(progress_dir):
            if not file.endswith('_progress.jsonl'):
                continue
            file_agent_id = file.replace('_progress.jsonl', '')
            if file_agent_id == exclude_agent_id:
                continue  # Skip calling agent's own progress
            try:
                with open(f"{progress_dir}/{file}", 'r') as f:
                    lines = f.readlines()
                    # Get last entry from this agent (most recent)
                    for line in reversed(lines):
                        line = line.strip()
                        if line:
                            try:
                                entry = json.loads(line)
                                all_progress.append(entry)
                                break  # Only take most recent per agent
                            except json.JSONDecodeError:
                                continue
            except Exception:
                continue

        # Sort by timestamp (newest first) and take top N
        all_progress.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        peer_progress = [
            {
                "agent": p.get("agent_id", "unknown"),
                "status": p.get("status", "unknown"),
                "message": p.get("message", "")[:100],  # Truncate long messages
                "progress": p.get("progress", 0),
                "time": p.get("timestamp", "")[-8:]  # Just time portion HH:MM:SS
            }
            for p in all_progress[:max_progress]
        ]

    # Collect findings from other agents
    findings_dir = f"{workspace}/findings"
    archive_dir = f"{workspace}/archive"

    findings_dirs = []
    if os.path.exists(findings_dir):
        findings_dirs.append(findings_dir)
    if os.path.exists(archive_dir):
        findings_dirs.append(archive_dir)

    all_findings = []
    for search_dir in findings_dirs:
        for file in os.listdir(search_dir):
            if not file.endswith('_findings.jsonl'):
                continue
            file_agent_id = file.replace('_findings.jsonl', '')
            if file_agent_id == exclude_agent_id:
                continue  # Skip calling agent's own findings
            try:
                with open(f"{search_dir}/{file}", 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                entry = json.loads(line)
                                all_findings.append(entry)
                            except json.JSONDecodeError:
                                continue
            except Exception:
                continue

    # Sort by timestamp (newest first) and take top N
    all_findings.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    peer_findings = [
        {
            "agent": f.get("agent_id", "unknown"),
            "type": f.get("finding_type", "unknown"),
            "severity": f.get("severity", "unknown"),
            "message": f.get("message", "")[:150],  # Truncate long messages
            "time": f.get("timestamp", "")[-8:]  # Just time portion HH:MM:SS
        }
        for f in all_findings[:max_findings]
    ]

    return {
        "peer_progress": peer_progress,
        "peer_findings": peer_findings,
        "note": "Latest updates from other agents. Use get_task_findings for full history."
    }


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
    conversation_history: Optional[List[Dict[str, str]]] = None,
    project_context: Optional[Dict[str, Any]] = None
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
                STRONGLY RECOMMENDED: Include 'deliverables' and 'success_criteria' per phase
                for accurate reviewer context.
        client_cwd: IMPORTANT - The client's working directory where agents should run.
                    Pass the current project path so agents operate in the correct location.
                    If not provided, agents may run in the wrong directory.
        background_context: Optional background information
        expected_deliverables: Optional list of expected deliverables
        success_criteria: Optional list of success criteria
        constraints: Optional list of constraints
        relevant_files: Optional list of relevant file paths
        conversation_history: Optional conversation context
        project_context: Optional dict with project-specific info for testers/reviewers:
                        - dev_server_port: Port where dev server runs (e.g., 3000, 5173)
                        - start_command: How to start the dev server (e.g., "npm run dev")
                        - test_url: Base URL for testing (e.g., "http://localhost:3000")
                        - framework: Framework used (e.g., "Next.js", "React", "Vue")
                        - test_credentials: Dict with test user credentials if needed

    Example phases (with deliverables - RECOMMENDED):
        [
            {
                "name": "Investigation",
                "description": "Research the codebase",
                "deliverables": ["Document auth flow", "List security gaps"],
                "success_criteria": ["Flow documented", "3+ gaps identified"]
            },
            {
                "name": "Implementation",
                "description": "Write the code",
                "deliverables": ["JWT auth endpoint", "Login page"],
                "success_criteria": ["Tokens expire correctly", "Login redirects to dashboard"]
            }
        ]

    Example project_context:
        {
            "dev_server_port": 3000,
            "start_command": "npm run dev",
            "test_url": "http://localhost:3000",
            "framework": "Next.js",
            "test_credentials": {"email": "test@example.com", "password": "test123"}
        }

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

        # CRITICAL: Warn about phases without deliverables (reviewers need these!)
        phases_without_deliverables = [p['name'] for p in enriched_phases if not p.get('deliverables')]
        phases_without_criteria = [p['name'] for p in enriched_phases if not p.get('success_criteria')]

        if phases_without_deliverables:
            warning = f"REVIEWER_CONTEXT_WARNING: Phases without deliverables (reviewers will see 'Not explicitly defined'): {phases_without_deliverables}"
            validation_warnings.append(warning)
            logger.warning(f"TASK-CREATION: {warning}")

        if phases_without_criteria:
            warning = f"REVIEWER_CONTEXT_WARNING: Phases without success_criteria (reviewers won't know approval criteria): {phases_without_criteria}"
            validation_warnings.append(warning)
            logger.warning(f"TASK-CREATION: {warning}")

        # AUTO-APPEND MANDATORY "Final Testing" PHASE (Jan 2026)
        # Testing is now a dedicated final phase instead of per-phase overhead.
        # Skip if the last phase already looks like a testing phase.
        last_phase_name = enriched_phases[-1]['name'].lower() if enriched_phases else ""
        is_testing_phase = any(keyword in last_phase_name for keyword in ['test', 'testing', 'verification', 'qa', 'quality'])

        if not is_testing_phase:
            # Collect deliverables from all prior phases to know what to test
            all_prior_deliverables = []
            for p in enriched_phases:
                all_prior_deliverables.extend(p.get('deliverables', []))

            testing_phase = {
                "id": f"phase-{uuid.uuid4().hex[:8]}",
                "order": len(enriched_phases) + 1,
                "name": "Final Testing",
                "description": "Comprehensive testing of all implemented features. This phase uses chrome-devtools MCP for browser testing, curl for API tests, and runs any existing test suites.",
                "deliverables": [
                    "All UI features tested via browser automation",
                    "All API endpoints tested via curl/integration tests",
                    "Existing test suites pass (if applicable)",
                    "No critical bugs or regressions found"
                ],
                "success_criteria": [
                    "Core user flows work end-to-end",
                    "No console errors during testing",
                    "API responses are correct and performant",
                    "Visual appearance matches expectations"
                ],
                "status": "PENDING",
                "created_at": datetime.now().isoformat(),
                "started_at": None,
                "auto_appended": True,  # Mark this was system-generated
                "tests_deliverables_from": [p['name'] for p in enriched_phases]  # What phases we're testing
            }
            enriched_phases.append(testing_phase)
            logger.info(f"TASK-CREATION: Auto-appended 'Final Testing' phase (order={len(enriched_phases)})")
            validation_warnings.append(f"AUTO_TESTING_PHASE: Added mandatory 'Final Testing' phase as phase {len(enriched_phases)}")

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

    # Add project_context to registry (for testers/reviewers to know port, framework, etc.)
    if project_context and isinstance(project_context, dict):
        registry['project_context'] = project_context
        logger.info(f"TASK-CREATION: project_context stored: {list(project_context.keys())}")

    # SQLITE MIGRATION: Create task directly in SQLite (source of truth)
    # This replaces the JSON-first-then-sync approach
    try:
        sqlite_result = state_db.create_task_with_phases(
            workspace_base=workspace_base,
            task_id=task_id,
            workspace=workspace,
            description=description,
            priority=priority,
            client_cwd=client_cwd,
            phases=enriched_phases,
            project_context=project_context,
            max_agents=DEFAULT_MAX_AGENTS,
            max_concurrent=DEFAULT_MAX_CONCURRENT,
            max_depth=DEFAULT_MAX_DEPTH,
            constraints=task_context.get('constraints') if has_enhanced_context else None,
            relevant_files=task_context.get('relevant_files') if has_enhanced_context else None,
            conversation_history=task_context.get('conversation_history') if has_enhanced_context else None,
            background_context=background_context,
            expected_deliverables=task_context.get('expected_deliverables') if has_enhanced_context else None
        )
        if sqlite_result.get('success'):
            logger.info(f"Task {task_id} created directly in SQLite (source of truth)")
        else:
            logger.error(f"Failed to create task in SQLite: {sqlite_result.get('error')}")
            return {"success": False, "error": f"SQLite creation failed: {sqlite_result.get('error')}"}
    except Exception as e:
        logger.error(f"Exception creating task in SQLite: {e}")
        return {"success": False, "error": f"SQLite creation exception: {e}"}

    # BACKWARD COMPAT: Keep JSON file for components still reading from it
    # TODO: Remove this once all AGENT_REGISTRY.json reads are migrated to SQLite
    with open(f"{workspace}/AGENT_REGISTRY.json", 'w') as f:
        json.dump(registry, f, indent=2)

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
    model: str = "claude-opus-4-5",
    agent_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Deploy a headless Claude agent using tmux for background execution.

    MIGRATED TO SQLITE (Jan 2026): No more nested LockedRegistryFile locks.
    Uses state_db for atomic operations, eliminating lock contention that
    caused reviewer spawn failures.

    Args:
        task_id: Task ID to deploy agent for
        agent_type: Type of agent (investigator, fixer, etc.)
        prompt: Instructions for the agent
        parent: Parent agent ID
        phase_index: Phase index this agent belongs to (auto-set from SQLite if None)
        model: Claude model to use - "claude-opus-4-5" (default) or "claude-sonnet-4-5" (faster, cheaper)
        agent_id: Optional pre-generated agent ID. If None, one will be generated.

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

    workspace_base = get_workspace_base_from_task_workspace(workspace)

    # =========================================================================
    # SQLITE MIGRATION: Replace nested LockedRegistryFile with SQLite checks
    # This eliminates lock contention that caused reviewer spawn failures
    # =========================================================================

    # Get task config from SQLite (or defaults)
    task_config = state_db.get_task_config(workspace_base=workspace_base, task_id=task_id)
    max_concurrent = task_config.get('max_concurrent', 20)
    max_agents = task_config.get('max_agents', 50)
    max_depth = task_config.get('max_depth', 5)

    # Check if we can spawn (atomic SQLite check - no file locks!)
    can_spawn, error_msg, existing = state_db.check_can_spawn_agent(
        workspace_base=workspace_base,
        task_id=task_id,
        agent_type=agent_type,
        max_concurrent=max_concurrent,
        max_agents=max_agents
    )

    if not can_spawn:
        if existing:
            return {
                "success": False,
                "error": error_msg,
                "existing_agent_id": existing.get('agent_id'),
                "existing_agent_status": existing.get('status'),
                "note": "Use the existing agent or wait for it to complete before spawning a new one"
            }
        return {
            "success": False,
            "error": error_msg
        }

    # Generate unique agent ID using UUID (no global registry lock needed!)
    # Use pre-generated agent_id if provided, otherwise generate one
    if not agent_id:
        timestamp = datetime.now().strftime('%H%M%S')
        unique_suffix = uuid.uuid4().hex[:6]
        # Truncate agent_type to avoid excessively long IDs
        type_prefix = agent_type[:20] if len(agent_type) > 20 else agent_type
        agent_id = f"{type_prefix}-{timestamp}-{unique_suffix}"

    session_name = f"agent_{agent_id}"

    # Calculate agent depth based on parent
    depth = 1 if parent == "orchestrator" else 2
    if parent != "orchestrator":
        # Check parent depth in SQLite
        parent_agent = state_db.get_agent_by_id(
            workspace_base=workspace_base,
            task_id=task_id,
            agent_id=parent
        )
        if parent_agent:
            depth = (parent_agent.get('depth') or 1) + 1

    # Get task description from SQLite task snapshot
    task_snapshot = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id)
    task_description = task_snapshot.get('description', '') if task_snapshot else ''

    # AUTO-SET phase_index if not provided - get from SQLite
    if phase_index is None:
        if task_snapshot:
            phase_index = task_snapshot.get('current_phase_index', 0)
        else:
            phase_index = 0
        logger.info(f"Auto-assigning agent {agent_id} to phase {phase_index}")

    # Build task_registry dict for prompt formatting (backward compat with format_task_enrichment_prompt)
    task_registry = {
        'task_description': task_description,
        'task_context': task_config,
        'max_depth': max_depth,
        'current_phase_index': phase_index,
        'phases': task_snapshot.get('phases', []) if task_snapshot else [],
        'agents': task_snapshot.get('agents', []) if task_snapshot else [],
    }

    # Legacy registry path (still needed for some file operations)
    registry_path = f"{workspace}/AGENT_REGISTRY.json"

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

    # Build accumulated context from SQLite (replaces filesystem-based handover)
    # This is CRITICAL for phase continuity - ensures agents have full task context
    try:
        accumulated_ctx = build_task_context_accumulator(
            workspace_base=workspace_base,
            task_id=task_id,
            current_phase_index=phase_index,
            max_tokens=2500
        )
        handover_context = format_accumulated_context(accumulated_ctx)
        logger.info(f"CONTEXT-ACCUMULATOR: Built context for {agent_id}, "
                    f"phase={phase_index}, tokens~{accumulated_ctx.estimated_tokens}, "
                    f"was_rejected={accumulated_ctx.was_rejected}")
    except Exception as e:
        # Fallback to legacy filesystem-based handover if accumulator fails
        logger.warning(f"CONTEXT-ACCUMULATOR: Failed for {agent_id}, using legacy handover: {e}")
        handover_context = format_previous_phase_handover(workspace, phase_index)

    # Create comprehensive agent prompt with MCP self-reporting capabilities
    agent_prompt = f"""You are a headless Claude agent in an orchestrator system.

🤖 AGENT IDENTITY:
- Agent ID: {agent_id}
- Agent Type: {agent_type}
- Task ID: {task_id}
- Parent Agent: {parent}
- Depth Level: {depth}
- Workspace: {workspace}
- Current Phase: {phase_index}

📝 YOUR MISSION:
{prompt}
{enrichment_prompt}
{context_prompt}
{handover_context}

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
        #
        # IMPORTANT: pass the prompt via stdin to avoid OS/shell argument-length limits.
        # Review prompts can be very large; passing them as a single CLI argument can cause the
        # tmux session to terminate immediately (agent never gets recorded/spawned).
        base_flags = '--print --output-format stream-json --input-format text --verbose --dangerously-skip-permissions'
        claude_flags = f'{base_flags} --model {model}'
        logger.info(f"Deploying agent {agent_id} with model: {model}")

        # JSONL log file path - unique per agent_id
        log_file = f"{logs_dir}/{agent_id}_stream.jsonl"

        # Completion notifier script - called immediately when Claude exits
        # This ensures registry is updated the moment the agent finishes
        notifier_script = os.path.join(os.path.dirname(__file__), 'orchestrator', 'completion_notifier.py')

        # Build command chain: Claude runs, then notifier triggers on exit
        # The notifier reads the stream log and updates registry immediately
        claude_command = (
            f"cd '{calling_project_dir}' && "
            f"cat '{prompt_file}' | {claude_executable} {claude_flags} | tee '{log_file}'; "
            f"python3 '{notifier_script}' '{task_id}' '{agent_id}' '{workspace}' '{log_file}'"
        )
        
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

        # =========================================================================
        # SQLITE MIGRATION: Replace LockedRegistryFile writes with SQLite
        # Single atomic transaction - no file locks, no race conditions
        # =========================================================================

        # Deploy agent to SQLite atomically
        deploy_result = state_db.deploy_agent_atomic(
            workspace_base=workspace_base,
            task_id=task_id,
            agent_id=agent_id,
            agent_type=agent_type,
            model=model,
            parent=parent,
            depth=depth,
            phase_index=phase_index,
            tmux_session=session_name,
            prompt_preview=prompt[:200] if prompt else ""
        )

        if not deploy_result.get('success'):
            # Clean up tmux session since SQLite insert failed
            if tmux_session_created:
                try:
                    subprocess.run(['tmux', 'kill-session', '-t', session_name],
                                 capture_output=True, timeout=5)
                    logger.info(f"Killed orphaned tmux session after SQLite insert failed: {session_name}")
                except Exception:
                    pass
            return {
                "success": False,
                "error": f"SQLite insert failed: {deploy_result.get('error', 'Unknown error')}"
            }

        # LIFECYCLE: Transition task to ACTIVE on first agent deployment
        active_count = state_db.get_active_agent_count(workspace_base=workspace_base, task_id=task_id)
        if active_count == 1:  # This is the first active agent
            try:
                if state_db.transition_task_to_active(workspace_base=workspace_base, task_id=task_id):
                    logger.info(f"[LIFECYCLE] Task {task_id} transitioned to ACTIVE on first agent deployment")
            except Exception as e:
                logger.warning(f"[LIFECYCLE] Failed to transition task to ACTIVE: {e}")

        # Log successful deployment
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": "agent_deployed",
            "agent_id": agent_id,
            "model": model,
            "tmux_session": session_name,
            "command": claude_command[:100] + "...",
            "success": True,
            "session_creation": session_result,
            "storage": "sqlite"  # Mark as SQLite-backed deployment
        }

        with open(f"{workspace}/logs/deploy_{agent_id}.json", 'w') as f:
            json.dump(log_entry, f, indent=2)

        logger.info(f"Agent {agent_id} deployed to SQLite successfully")

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

    SQLITE MIGRATION: Now reads agents from SQLite (source of truth) and updates
    agent statuses via SQLite. No more LockedRegistryFile - SQLite handles concurrency.

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

    # Get workspace_base for SQLite operations
    workspace_base = get_workspace_base_from_task_workspace(workspace)

    # Load agents from SQLite (source of truth)
    task_snapshot = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id)
    if not task_snapshot:
        # Fall back to reading basic task info from JSON if SQLite empty
        registry_path = f"{workspace}/AGENT_REGISTRY.json"
        try:
            with open(registry_path, 'r') as f:
                registry = json.load(f)
        except FileNotFoundError:
            return {"success": False, "error": f"Task {task_id} not found"}
        except json.JSONDecodeError:
            return {"success": False, "error": f"Corrupted registry for task {task_id}"}
    else:
        # Use SQLite data - transform to registry format
        registry = {
            'task_id': task_id,
            'task_description': task_snapshot.get('description', ''),
            'status': task_snapshot.get('status', 'INITIALIZED'),
            'phases': task_snapshot.get('phases', []),
            'current_phase_index': task_snapshot.get('current_phase_index', 0),
            'agents': task_snapshot.get('agents', []),
            'total_spawned': task_snapshot.get('counts', {}).get('total', 0),
            'active_count': task_snapshot.get('counts', {}).get('active', 0),
            'completed_count': task_snapshot.get('counts', {}).get('completed', 0),
            'agent_hierarchy': {'orchestrator': []},  # Will be populated from agent_hierarchy table if needed
            'max_agents': 45,
            'max_concurrent': 20,
            'max_depth': 5,
            'spiral_checks': {'enabled': True, 'last_check': datetime.now().isoformat(), 'violations': 0},
        }

    # SQLITE MIGRATION: Check agent completion via stream logs and tmux sessions
    # Update SQLite directly (no JSON writes)
    agents_completed = []
    active_statuses_to_check = {'running', 'working', 'blocked'}

    for agent in registry.get('agents', []):
        agent_status = agent.get('status', '')
        agent_id = agent.get('agent_id') or agent.get('id', '')

        # Skip if already in terminal state
        if agent_status not in active_statuses_to_check:
            continue

        # FIRST: Check stream log for completion marker (most reliable)
        stream_log = f"{workspace}/logs/{agent_id}_stream.jsonl"
        stream_completed = False
        new_status = None
        completion_reason = None

        if os.path.exists(stream_log):
            try:
                with open(stream_log, 'rb') as sf:
                    sf.seek(0, 2)  # End of file
                    file_size = sf.tell()
                    if file_size > 0:
                        read_size = min(4096, file_size)
                        sf.seek(-read_size, 2)
                        last_chunk = sf.read().decode('utf-8', errors='ignore')
                        lines = [l.strip() for l in last_chunk.split('\n') if l.strip()]
                        if lines:
                            try:
                                last_entry = json.loads(lines[-1])
                                if last_entry.get('type') == 'result':
                                    is_error = last_entry.get('is_error', False)
                                    new_status = 'failed' if is_error else 'completed'
                                    completion_reason = 'stream_log_result_marker'
                                    stream_completed = True
                            except json.JSONDecodeError:
                                pass
            except Exception as e:
                logger.debug(f"Error reading stream log for {agent_id}: {e}")

        # SECOND: Check tmux session (fallback)
        tmux_session = agent.get('tmux_session', '')
        if not stream_completed and tmux_session:
            if not check_tmux_session_exists(tmux_session):
                new_status = 'completed'
                completion_reason = 'tmux_session_terminated'

        # Update SQLite if status changed
        if new_status:
            try:
                state_db.update_agent_status(
                    workspace_base=workspace_base,
                    task_id=task_id,
                    agent_id=agent_id,
                    new_status=new_status
                )
                agents_completed.append(agent_id)
                logger.info(f"Detected agent {agent_id} {new_status} via {completion_reason} (was {agent_status})")
                # Update local registry copy for response
                agent['status'] = new_status
            except Exception as e:
                logger.error(f"Failed to update agent {agent_id} status in SQLite: {e}")
    
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
        # SQLITE MIGRATION: Filter by phase_index (SQLite) OR phase_id (legacy JSON)
        phase_agents = [
            a for a in registry.get('agents', [])
            if a.get('phase_index') == current_phase_index or a.get('phase_id') == current_phase.get('id')
        ]
        completed_agents = [a for a in phase_agents if a.get('status') in AGENT_TERMINAL_STATUSES]
        pending_agents = [
            a.get('agent_id') or a.get('id')
            for a in phase_agents
            if a.get('status') not in AGENT_TERMINAL_STATUSES
        ]

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

    # SQLITE MIGRATION: Get agent from SQLite instead of JSON registry
    workspace_base = get_workspace_base_from_task_workspace(workspace)
    agent = state_db.get_agent_by_id(
        workspace_base=workspace_base,
        task_id=task_id,
        agent_id=agent_id
    )

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

    # SQLITE MIGRATION: Get agent from SQLite instead of JSON registry
    workspace_base = get_workspace_base_from_task_workspace(workspace)
    agent = state_db.get_agent_by_id(
        workspace_base=workspace_base,
        task_id=task_id,
        agent_id=agent_id
    )

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
        
        # SQLITE MIGRATION: Mark agent as terminal in SQLite (source of truth)
        # Active count is computed from SQLite, no need to track separately
        try:
            state_db.mark_agent_terminal(
                workspace_base=workspace_base,
                agent_id=agent_id,
                status='terminated',
                reason=reason,
                auto_rollup=True  # Check if task should transition
            )
            logger.info(f"Agent {agent_id} marked as terminated in state_db")
        except Exception as e:
            logger.error(f"Failed to mark agent terminal in state_db: {e}")

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

    SQLITE MIGRATION: Now reads agents from SQLite instead of JSON.

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

    workspace_base = get_workspace_base_from_task_workspace(workspace)

    # SQLITE MIGRATION: Read agents from SQLite instead of JSON
    try:
        task_snapshot = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id)
        if not task_snapshot:
            return {"success": False, "error": f"Task {task_id} not found in SQLite"}

        # 1. Get all agents with current status from SQLite
        agents_status = []
        for agent in task_snapshot.get('agents', []):
            agents_status.append({
                "id": agent.get("agent_id"),
                "type": agent.get("type"),
                "status": agent.get("status"),
                "progress": agent.get("progress", 0),
                "last_update": agent.get("last_update"),
                "parent": agent.get("parent", "orchestrator")
            })
    except Exception as e:
        return {"success": False, "error": f"Failed to read from SQLite: {e}"}

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
        Includes peer_context with:
        - peer_progress: Latest 3 progress updates from OTHER agents
        - peer_findings: Latest 3 findings from OTHER agents
        This keeps you aware of what peers are doing without needing to call get_task_findings.
    """
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }

    workspace_base = get_workspace_base_from_task_workspace(workspace)

    # Log progress update to JSONL (append-only log)
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

    # SQLITE MIGRATION: SQLite is now the source of truth
    # No more LockedRegistryFile - SQLite handles concurrency natively

    # Define status categories
    active_statuses = ['running', 'working', 'blocked']
    terminal_statuses = ['completed', 'terminated', 'error', 'failed']

    # 1. Get agent's current status from SQLite (to track transitions)
    previous_status = None
    agent_phase_index = None
    try:
        agent_data = state_db.get_agent(
            workspace_base=workspace_base,
            task_id=task_id,
            agent_id=agent_id
        )
        if agent_data:
            previous_status = agent_data.get('status')
            agent_phase_index = agent_data.get('phase_index')
    except Exception as e:
        logger.warning(f"Failed to get agent state from SQLite: {e}")

    # 2. Record progress update in SQLite
    try:
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

    # 3. Update agent status in SQLite (handles count updates atomically)
    cleanup_needed = False
    if previous_status != status:
        state_db.update_agent_status(
            workspace_base=workspace_base,
            task_id=task_id,
            agent_id=agent_id,
            new_status=status
        )

        # Check if transitioning to terminal state
        if previous_status in active_statuses and status in terminal_statuses:
            cleanup_needed = True
            logger.info(
                f"Agent {agent_id} transitioned from {previous_status} to {status}."
            )

            # LIFECYCLE: Check if all agents are terminal and transition task to COMPLETED
            try:
                task_data = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id)
                if task_data:
                    agents = task_data.get('agents', [])
                    all_terminal = all(a.get('status') in terminal_statuses for a in agents) if agents else False

                    if all_terminal and len(agents) > 0:
                        if state_db.transition_task_to_completed(workspace_base=workspace_base, task_id=task_id):
                            logger.info(f"[LIFECYCLE] Task {task_id} transitioned to COMPLETED - all agents terminal")
            except Exception as e:
                logger.warning(f"[LIFECYCLE] Failed to check task completion: {e}")

    # 4. VALIDATION: When agent claims completion, validate the claim
    if status == 'completed':
        try:
            # Get agent type for validation
            agent_type = 'unknown'
            if agent_data:
                agent_type = agent_data.get('type', 'unknown')

            # Run 4-layer validation (uses JSONL files, not registry)
            validation = validate_agent_completion(workspace, agent_id, agent_type, message, None)

            # In WARNING mode: log but don't block completion
            if not validation['valid'] or validation['warnings']:
                logger.warning(f"Completion validation for {agent_id}: confidence={validation['confidence']:.2f}, "
                             f"warnings={len(validation['warnings'])}, blocking_issues={len(validation['blocking_issues'])}")

            logger.info(f"Agent {agent_id} completion validated: confidence={validation['confidence']:.2f}")
        except Exception as e:
            logger.warning(f"Completion validation failed for {agent_id}: {e}")

    # 5. AUTOMATIC PHASE ENFORCEMENT (SQLite only)
    pending_review = None

    def _maybe_auto_submit_phase_for_review_sqlite() -> Optional[Dict[str, Any]]:
        """Check if phase is complete and submit for review using SQLite only."""
        try:
            if status not in terminal_statuses:
                return None
            if agent_phase_index is None:
                return None

            # Check phase completion from SQLite
            phase_state = state_db.load_phase_snapshot(
                workspace_base=workspace_base,
                task_id=task_id,
                phase_index=int(agent_phase_index),
            )

            if not phase_state.get("counts", {}).get("all_done"):
                return None

            # Get current phase status from SQLite
            phase_data = state_db.get_phase(
                workspace_base=workspace_base,
                task_id=task_id,
                phase_index=int(agent_phase_index)
            )

            if not phase_data or phase_data.get('status') != 'ACTIVE':
                return None

            # Transition phase to AWAITING_REVIEW in SQLite
            state_db.update_phase_status(
                workspace_base=workspace_base,
                task_id=task_id,
                phase_index=int(agent_phase_index),
                new_status="AWAITING_REVIEW"
            )

            logger.info(f"AUTO-PHASE-ENFORCEMENT: Phase {agent_phase_index} submitted for review (SQLite)")

            return {
                "phase_index": int(agent_phase_index),
                "phase_name": phase_data.get("name", f"Phase {int(agent_phase_index) + 1}"),
                "task_id": task_id,
                "completed_agents": int(phase_state["counts"]["completed"]),
                "failed_agents": int(phase_state["counts"]["failed"]),
            }
        except Exception as e:
            logger.error(f"AUTO-PHASE-ENFORCEMENT: Failed to evaluate/transition phase: {e}")
            return None

    # Check if phase should be submitted for review
    if agent_phase_index is None:
        # Try to get phase_index from SQLite if not already known
        try:
            agent_data = state_db.get_agent(
                workspace_base=workspace_base,
                task_id=task_id,
                agent_id=agent_id
            )
            if agent_data:
                agent_phase_index = agent_data.get('phase_index')
        except Exception:
            pass

    pending_review = _maybe_auto_submit_phase_for_review_sqlite()

    # Retry in background if phase should complete but didn't
    if not pending_review and status in terminal_statuses and agent_phase_index is not None:
        def _review_retry_worker() -> None:
            try:
                import time
                for _ in range(10):  # ~30s total
                    pr = _maybe_auto_submit_phase_for_review_sqlite()
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

    # 6. ASYNC NON-DESTRUCTIVE CLEANUP (no file lock needed)
    if cleanup_needed:
        def _cleanup_worker():
            try:
                time.sleep(2)

                # Get agent data from SQLite instead of JSON
                agent_data_for_cleanup = state_db.get_agent(
                    workspace_base=workspace_base,
                    task_id=task_id,
                    agent_id=agent_id
                )

                if not agent_data_for_cleanup:
                    return

                cleanup_result = cleanup_agent_resources(
                    workspace=workspace,
                    agent_id=agent_id,
                    agent_data=agent_data_for_cleanup,
                    keep_logs=True,
                    kill_tmux=False,
                )

                logger.info(f"Async cleanup completed for {agent_id}: {cleanup_result}")
            except Exception as e:
                logger.error(f"Async cleanup failed for {agent_id}: {e}")

        threading.Thread(target=_cleanup_worker, daemon=True).start()

    # 7. AUTO-SPAWN REVIEWERS FOR PHASE ENFORCEMENT
    logger.info(f"[UPDATE-PROGRESS] pending_review={pending_review}")
    # DEBUG: Write to file for tracing
    import sys
    print(f"[DEBUG-TRACE] pending_review={pending_review}", file=sys.stderr)
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

    # Include peer context so agents stay aware without explicit get_task_findings calls
    # Returns latest 3 progress updates + 3 findings from OTHER agents (not O(n²) bloat)
    try:
        peer_context = _get_peer_context(workspace, exclude_agent_id=agent_id)
    except Exception as e:
        logger.warning(f"Failed to get peer context: {e}")
        peer_context = {"peer_progress": [], "peer_findings": [], "note": "Error fetching peer context"}

    response = {
        "success": True,
        "own_update": {
            "agent_id": agent_id,
            "status": status,
            "progress": progress,
            "message": message,
            "timestamp": progress_entry["timestamp"]
        },
        "peer_context": peer_context,
        "coordination_tip": "Peer context shows latest 3 updates from other agents. Use get_task_findings for full history."
    }

    # Add completion reminder if not yet completed
    if status != "completed":
        response["important_reminder"] = (
            "CRITICAL: You MUST call update_agent_progress with status='completed' when you finish your work. "
            "If you don't, the phase cannot advance and other agents will be blocked waiting for you. "
            "Your work is not counted until you report completion."
        )

    # registry_lock_failed removed - SQLite handles concurrency natively, no file locking needed

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
        Includes peer_context with:
        - peer_progress: Latest 3 progress updates from OTHER agents
        - peer_findings: Latest 3 findings from OTHER agents
        This keeps you aware of what peers are doing without needing to call get_task_findings.
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

    # Include peer context so agents stay aware without explicit get_task_findings calls
    # Returns latest 3 progress updates + 3 findings from OTHER agents
    try:
        peer_context = _get_peer_context(workspace, exclude_agent_id=agent_id)
    except Exception as e:
        logger.warning(f"Failed to get peer context: {e}")
        peer_context = {"peer_progress": [], "peer_findings": [], "note": "Error fetching peer context"}

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
        "peer_context": peer_context,
        "coordination_tip": "Peer context shows latest 3 updates from other agents. Use get_task_findings for full history.",
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


# NOTE: advance_to_next_phase was REMOVED (Jan 2026)
# Phase advancement now happens automatically in submit_review_verdict when reviewers approve.
# The function was redundant - by the time phase is APPROVED, auto-advance already happened.
# Removing it eliminates confusion and prevents orchestrator from thinking manual advance is needed.


@mcp.tool()
def submit_phase_for_review(task_id: str, phase_summary: Optional[str] = None) -> str:
    """
    Submit current phase for review.

    SQLITE MIGRATION: Now reads phase/agent data from SQLite (source of truth).
    Transitions phase from ACTIVE to AWAITING_REVIEW.
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    workspace_base = get_workspace_base_from_task_workspace(workspace)

    # SQLITE MIGRATION: Read from SQLite instead of JSON
    task_snapshot = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id)
    if not task_snapshot:
        return json.dumps({"success": False, "error": f"Task {task_id} not found in SQLite"})

    phases = task_snapshot.get('phases', [])
    current_idx = task_snapshot.get('current_phase_index', 0)

    if not phases or current_idx >= len(phases):
        return json.dumps({"success": False, "error": "No current phase"})

    current_phase = phases[current_idx]
    phase_status = current_phase.get('status', '')

    # Allow submit from ACTIVE (normal flow) or REVISING (after rejection)
    if phase_status not in ['ACTIVE', 'REVISING']:
        return json.dumps({
            "success": False,
            "error": f"Phase must be ACTIVE or REVISING to submit for review. Current: {phase_status}"
        })

    # Count phase agents from SQLite (source of truth)
    agents = task_snapshot.get('agents', [])
    phase_agents = [a for a in agents if a.get('phase_index') == current_idx]
    completed_agents = len([a for a in phase_agents if a.get('status') == 'completed'])
    failed_agents = len([a for a in phase_agents if a.get('status') in ['failed', 'error', 'terminated']])
    phase_name = current_phase.get('name', f'Phase {current_idx + 1}')

    # Transition to AWAITING_REVIEW in SQLite
    state_db.update_phase_status(
        workspace_base=workspace_base,
        task_id=task_id,
        phase_index=current_idx,
        new_status="AWAITING_REVIEW"
    )

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
    # SQLITE MIGRATION: Read from SQLite instead of JSON
    if force_escalated:
        workspace = find_task_workspace(task_id)
        if not workspace:
            return json.dumps({"success": False, "error": f"Task {task_id} not found"})

        workspace_base = get_workspace_base_from_task_workspace(workspace)

        # Read from SQLite
        task_snapshot = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id)
        if not task_snapshot:
            return json.dumps({"success": False, "error": f"Task {task_id} not found in SQLite"})

        phases = task_snapshot.get('phases', [])
        current_idx = task_snapshot.get('current_phase_index', 0)

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

        # Perform forced approval via SQLite
        state_db.update_phase_status(
            workspace_base=workspace_base,
            task_id=task_id,
            phase_index=current_idx,
            new_status='APPROVED'
        )

        logger.warning(f"FORCE APPROVAL: Phase {current_idx} approved via force_escalated (all reviewers crashed)")

        # Auto-advance if requested
        advanced = False
        if auto_advance and current_idx < len(phases) - 1:
            # Activate next phase
            state_db.update_phase_status(
                workspace_base=workspace_base,
                task_id=task_id,
                phase_index=current_idx + 1,
                new_status='ACTIVE'
            )
            # Update current phase index
            state_db.update_task_phase_index(
                workspace_base=workspace_base,
                task_id=task_id,
                new_phase_index=current_idx + 1
            )
            advanced = True

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


# NOTE: reject_phase_review was REMOVED (Jan 2026)
# Manual rejection is not allowed - all rejections go through submit_review_verdict from reviewer agents.
# The function was always blocked anyway, so removing it eliminates confusion.


# ============================================================================
# PHASE OUTCOME POPULATION - Context Accumulator Support (Jan 2026)
# ============================================================================


def _populate_phase_outcome(
    workspace_base: str,
    task_id: str,
    phase_index: int,
    review_id: str,
    final_verdict: str
) -> bool:
    """
    Populate phase_outcomes table after a review is finalized.

    This stores structured phase results for the context accumulator,
    enabling later phases to access comprehensive prior phase context.

    Called automatically when submit_review_verdict() finalizes a review.

    Args:
        workspace_base: Base directory for task workspace
        task_id: Task identifier
        phase_index: Index of the phase that was reviewed
        review_id: ID of the completed review
        final_verdict: Final verdict (approved, rejected, needs_revision)

    Returns:
        True if outcome was populated successfully
    """
    try:
        # 1. Get aggregated reviewer notes
        review_data = state_db.get_review(workspace_base=workspace_base, review_id=review_id)
        review_summary = (review_data.get('reviewer_notes') or '') if review_data else ''

        # 2. Get all verdicts to aggregate findings
        verdicts = state_db.get_review_verdicts(workspace_base=workspace_base, review_id=review_id)
        all_review_findings = []
        for verdict in verdicts:
            findings_json = verdict.get('findings')
            if findings_json:
                try:
                    findings = json.loads(findings_json) if isinstance(findings_json, str) else findings_json
                    all_review_findings.extend(findings)
                except Exception:
                    pass

            # Also include reviewer notes in summary
            notes = verdict.get('reviewer_notes') or ''
            if notes and notes not in review_summary:
                review_summary += f"\n{notes}"

        # 3. Get critical/high severity findings from this phase's agents
        agent_findings = state_db.get_agent_findings(
            workspace_base=workspace_base,
            task_id=task_id,
            limit=100
        )
        critical_findings = []
        for finding in agent_findings:
            if finding.get('phase_index') != phase_index:
                continue
            if finding.get('severity') in ('critical', 'high'):
                critical_findings.append({
                    'finding_type': finding.get('finding_type'),
                    'severity': finding.get('severity'),
                    'message': finding.get('message', '')[:200],
                    'agent_id': finding.get('agent_id'),
                })

        # 4. Extract key decisions from findings (type='solution' or 'recommendation')
        key_decisions = []
        for finding in agent_findings:
            if finding.get('phase_index') != phase_index:
                continue
            if finding.get('finding_type') in ('solution', 'recommendation', 'insight'):
                key_decisions.append(finding.get('message', '')[:150])

        # Limit to top 10 decisions
        key_decisions = key_decisions[:10]

        # 5. Extract blockers (only if resolved - i.e., phase was approved)
        blockers_resolved = []
        if final_verdict == 'approved':
            for finding in agent_findings:
                if finding.get('phase_index') != phase_index:
                    continue
                if finding.get('finding_type') == 'blocker':
                    blockers_resolved.append(finding.get('message', '')[:100])

        # 6. Extract artifacts from finding data
        artifacts_created = []
        for finding in agent_findings:
            if finding.get('phase_index') != phase_index:
                continue
            data = finding.get('data', {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    data = {}
            if isinstance(data, dict):
                # Look for file paths in data
                for key in ('file', 'files', 'path', 'paths', 'created_files', 'modified_files'):
                    val = data.get(key)
                    if isinstance(val, str):
                        artifacts_created.append(val)
                    elif isinstance(val, list):
                        artifacts_created.extend([v for v in val if isinstance(v, str)])

        # Remove duplicates and limit
        artifacts_created = list(set(artifacts_created))[:20]

        # 7. Upsert phase outcome
        state_db.upsert_phase_outcome(
            workspace_base=workspace_base,
            task_id=task_id,
            phase_index=phase_index,
            review_verdict=final_verdict,
            review_summary=review_summary.strip()[:500],  # Limit summary length
            key_decisions=key_decisions,
            blockers_resolved=blockers_resolved,
            critical_findings=critical_findings[:15],  # Limit findings
            artifacts_created=artifacts_created
        )

        logger.info(f"PHASE-OUTCOME: Populated outcome for task {task_id} phase {phase_index}: "
                    f"verdict={final_verdict}, decisions={len(key_decisions)}, "
                    f"critical_findings={len(critical_findings)}")
        return True

    except Exception as e:
        logger.error(f"PHASE-OUTCOME: Failed to populate for {task_id} phase {phase_index}: {e}",
                     exc_info=True)
        return False


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
    num_reviewers: int = 2
) -> Dict[str, Any]:
    """
    INTERNAL: Auto-spawn reviewer agents + 1 critique agent when a phase completes.

    This is called automatically by update_agent_progress when all phase agents finish.
    It creates a review record and spawns:
    - 2 Sonnet REVIEWER agents (submit verdicts - approve/reject/needs_revision)
    - 1 Sonnet CRITIQUE agent (senior dev perspective, no verdict, just observations)

    The critique agent provides birds-eye view feedback but doesn't affect phase approval.
    Only reviewer verdicts count for pass/fail decisions.

    Args:
        task_id: Task ID
        phase_index: Index of the phase that just completed
        phase_name: Name of the phase
        completed_agents: Number of agents that completed successfully
        failed_agents: Number of agents that failed
        workspace: Task workspace path
        num_reviewers: Number of reviewer agents to spawn (default 2, plus 1 critique)

    Returns:
        Dict with review_id, spawned agents, critique agent, and status
    """
    workspace_base = get_workspace_base_from_task_workspace(workspace)
    logger.info(f"[REVIEWER-SPAWN] Starting _auto_spawn_phase_reviewers for task={task_id}, phase={phase_index}")

    # SQLITE MIGRATION: Use SQLite for all review record management
    # No more LockedRegistryFile - SQLite handles concurrency natively

    # Create review record
    review_id = f"auto-review-{uuid.uuid4().hex[:12]}"
    review_focus = ["completeness", "correctness", "quality"]

    # 1. Get phase data from SQLite
    phase_data = state_db.get_phase(
        workspace_base=workspace_base,
        task_id=task_id,
        phase_index=phase_index
    )
    logger.info(f"[REVIEWER-SPAWN] Phase data from SQLite: {phase_data}")

    if not phase_data:
        logger.error(f"[REVIEWER-SPAWN] Phase not found in SQLite for task={task_id}, phase_index={phase_index}")
        return {"success": False, "error": "Invalid phase_index - phase not found in SQLite"}

    # 2. ATOMIC CLAIM: Transition AWAITING_REVIEW -> UNDER_REVIEW
    # This prevents race conditions where multiple threads try to spawn reviewers
    claimed = state_db.claim_phase_for_review(
        workspace_base=workspace_base,
        task_id=task_id,
        phase_index=phase_index
    )

    if not claimed:
        # Another thread already claimed this phase - don't spawn duplicates
        logger.info(f"[REVIEWER-SPAWN] Phase {phase_index} already claimed by another thread - skipping duplicate spawn")
        return {"success": False, "error": "Phase already claimed for review by another process", "duplicate_prevented": True}

    # 3. Create review record in SQLite (only after successful claim)
    create_result = state_db.create_review_record(
        workspace_base=workspace_base,
        task_id=task_id,
        review_id=review_id,
        phase_index=phase_index,
        num_reviewers=num_reviewers
    )

    if not create_result.get('success'):
        return {"success": False, "error": f"Failed to create review record: {create_result.get('error')}"}

    # Extract phase-specific deliverables and success criteria for reviewer context
    phase_deliverables = phase_data.get('deliverables', [])
    phase_success_criteria = phase_data.get('success_criteria', [])
    phase_description = phase_data.get('description', '')

    # Get project_context from task config in SQLite
    task_config = state_db.get_task_config(workspace_base=workspace_base, task_id=task_id)
    project_context = {}
    if task_config and task_config.get('project_context'):
        try:
            project_context = json.loads(task_config['project_context']) if isinstance(task_config['project_context'], str) else task_config['project_context']
        except:
            project_context = {}

    # Get all phases from SQLite for OUT OF SCOPE section
    task_snapshot = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id)
    phases = task_snapshot.get('phases', []) if task_snapshot else []

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

    # Build project context section (port, framework, test URLs for testers/reviewers)
    project_context_section = ""
    if project_context:
        ctx_items = []
        if project_context.get('dev_server_port'):
            ctx_items.append(f"  - Dev Server Port: {project_context['dev_server_port']}")
        if project_context.get('test_url'):
            ctx_items.append(f"  - Test URL: {project_context['test_url']}")
        if project_context.get('start_command'):
            ctx_items.append(f"  - Start Command: {project_context['start_command']}")
        if project_context.get('framework'):
            ctx_items.append(f"  - Framework: {project_context['framework']}")
        if project_context.get('test_credentials'):
            creds = project_context['test_credentials']
            # Show credentials exist but mask password for security in logs
            cred_info = f"Email: {creds.get('email', 'N/A')}, Password: [provided]"
            ctx_items.append(f"  - Test Credentials: {cred_info}")

        if ctx_items:
            ctx_list = "\n".join(ctx_items)
            project_context_section = f"""
═══════════════════════════════════════════════════════════════════════════════
🔧 PROJECT CONTEXT (for testing/verification):
═══════════════════════════════════════════════════════════════════════════════
{ctx_list}

USE THIS INFO: When verifying deliverables, use these settings instead of defaults.
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
{project_context_section}
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
    reviewer_agent_id="{{REVIEWER_AGENT_ID}}",
    verdict="approved" | "rejected" | "needs_revision",
    findings=[{{"type": "issue|suggestion|blocker|praise", "severity": "critical|high|medium|low", "message": "..."}}],
    reviewer_notes="Summary of what you verified against THIS phase's criteria"
)
```
NOTE: Replace {{REVIEWER_AGENT_ID}} with your actual agent ID (provided below).

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

    # Spawn reviewer agents (Sonnet for speed/cost - reviews are formulaic)
    spawned_agents = []
    review_prefix = review_id.split('-')[-1][:8]  # e.g., "auto-review-abc123..." -> "abc123"

    # DEBUG: Log key variables before reviewer spawn loop
    logger.info(f"AUTO-PHASE-ENFORCEMENT: === REVIEWER SPAWN DEBUG ===")
    logger.info(f"AUTO-PHASE-ENFORCEMENT: task_id={task_id}")
    logger.info(f"AUTO-PHASE-ENFORCEMENT: review_id={review_id}")
    logger.info(f"AUTO-PHASE-ENFORCEMENT: review_prefix={review_prefix}")
    logger.info(f"AUTO-PHASE-ENFORCEMENT: num_reviewers={num_reviewers}")
    logger.info(f"AUTO-PHASE-ENFORCEMENT: workspace={workspace}")
    logger.info(f"AUTO-PHASE-ENFORCEMENT: review_prompt length={len(review_prompt)}")

    for i in range(num_reviewers):
        # CRITICAL FIX (v2): Agent types must be unique per-REVIEW, not just per-phase
        # Include review_id prefix to guarantee uniqueness across multiple reviews of the same phase
        agent_type = f"reviewer-{review_prefix}-{i+1}"
        logger.info(f"AUTO-PHASE-ENFORCEMENT: Attempting to spawn reviewer {i+1}/{num_reviewers}: agent_type={agent_type}")
        try:
            # Pre-generate agent_id so we can inject it into the prompt
            timestamp = datetime.now().strftime('%H%M%S')
            unique_suffix = uuid.uuid4().hex[:6]
            type_prefix = agent_type[:20] if len(agent_type) > 20 else agent_type
            pre_generated_agent_id = f"{type_prefix}-{timestamp}-{unique_suffix}"

            # Inject the agent_id into the prompt
            reviewer_prompt_with_id = review_prompt.replace(
                "{REVIEWER_AGENT_ID}",
                pre_generated_agent_id
            )

            # Use Sonnet for reviewers (faster, cheaper, sufficient for structured review tasks)
            logger.info(f"AUTO-PHASE-ENFORCEMENT: Calling deploy_claude_tmux_agent for {agent_type} with pre-generated id {pre_generated_agent_id}...")
            result = deploy_claude_tmux_agent(
                task_id=task_id,
                agent_type=agent_type,
                prompt=reviewer_prompt_with_id,
                parent="orchestrator",
                phase_index=-1,  # -1 indicates reviewer agent (not part of any phase)
                model="claude-sonnet-4-5",  # Sonnet for reviewers
                agent_id=pre_generated_agent_id
            )
            logger.info(f"AUTO-PHASE-ENFORCEMENT: deploy_claude_tmux_agent returned: success={result.get('success')}, error={result.get('error', 'N/A')}")
            if result.get('success'):
                agent_id = result.get('agent_id')
                spawned_agents.append(agent_id)

                # SQLITE MIGRATION: Update review record with reviewer info in SQLite
                state_db.add_reviewer_to_review(
                    workspace_base=workspace_base,
                    review_id=review_id,
                    agent_id=agent_id
                )

                logger.info(f"AUTO-PHASE-ENFORCEMENT: Successfully spawned Sonnet reviewer {agent_id}")
            else:
                logger.error(f"AUTO-PHASE-ENFORCEMENT: Failed to spawn reviewer {i+1}: {result.get('error', 'Unknown error')}")
                logger.error(f"AUTO-PHASE-ENFORCEMENT: Full result: {result}")
        except Exception as e:
            logger.error(f"AUTO-PHASE-ENFORCEMENT: Exception spawning reviewer {i+1}: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"AUTO-PHASE-ENFORCEMENT: Traceback: {traceback.format_exc()}")

    logger.info(f"AUTO-PHASE-ENFORCEMENT: Reviewer spawn loop complete. Spawned: {len(spawned_agents)} agents")

    # Build critique prompt (different from reviewer - senior dev birds-eye view)
    critique_prompt = f"""You are a SENIOR DEVELOPER CRITIQUE AGENT for phase "{phase_name}" (Task: {task_id}).

YOUR ROLE IS DIFFERENT FROM REVIEWERS:
- You do NOT submit a verdict (approve/reject)
- You provide senior developer perspective and observations
- Your feedback informs the orchestrator but doesn't block progress
- Think like a tech lead doing a high-level code review

PHASE SUMMARY:
- Phase: {phase_name} (index {phase_index})
- Description: {phase_description if phase_description else 'Not provided'}
- Agents completed: {completed_agents}
- Agents failed: {failed_agents}
{deliverables_section}
{out_of_scope_section}
YOUR MISSION: Provide birds-eye view observations, not pass/fail judgment.

STEP 1 - GET AGENT FINDINGS:
```
mcp__claude-orchestrator__get_phase_handover(task_id="{task_id}", phase_index={phase_index})
```

STEP 2 - GET TASK CONTEXT (if needed):
```
mcp__claude-orchestrator__get_real_task_status(task_id="{task_id}")
```

STEP 3 - EXAMINE CODE/DELIVERABLES:
- Use Read tool to check actual files
- Look for architectural patterns
- Check for technical debt
- Workspace: {workspace}

WHAT TO LOOK FOR (senior dev perspective):
1. ARCHITECTURAL: Is the approach sound? Any red flags?
2. TECHNICAL DEBT: Are there shortcuts that will cause problems later?
3. MAINTAINABILITY: Will this be easy to maintain/extend?
4. BEST PRACTICES: Are coding standards followed?
5. SUGGESTIONS: What could be improved (even if not blocking)?

SUBMIT YOUR CRITIQUE (NOT a verdict):
```
mcp__claude-orchestrator__submit_critique(
    task_id="{task_id}",
    review_id="{review_id}",
    critique_agent_id="{{CRITIQUE_AGENT_ID}}",
    observations=[
        {{"type": "architectural|technical_debt|suggestion|concern|praise", "priority": "high|medium|low", "message": "...", "scope": "current_phase|future_phases|overall"}}
    ],
    summary="High-level assessment from senior dev perspective",
    recommendations=["Optional list of recommendations for orchestrator"]
)
```
NOTE: Replace {{CRITIQUE_AGENT_ID}} with your actual agent ID (provided below).

═══════════════════════════════════════════════════════════════════════════════
⚡ MANDATORY: YOU MUST SUBMIT YOUR CRITIQUE - YOUR JOB IS NOT COMPLETE WITHOUT IT ⚡
═══════════════════════════════════════════════════════════════════════════════

REMEMBER: You are providing observations and advice, NOT a pass/fail verdict.
The 2 reviewer agents handle the verdict. Your role is senior dev perspective.
"""

    # Spawn critique agent (Sonnet)
    critique_agent_id = None
    try:
        critique_agent_type = f"critique-{review_prefix}"

        # Pre-generate agent_id so we can inject it into the prompt
        timestamp = datetime.now().strftime('%H%M%S')
        unique_suffix = uuid.uuid4().hex[:6]
        pre_generated_critique_id = f"{critique_agent_type[:20]}-{timestamp}-{unique_suffix}"

        # Inject the agent_id into the prompt
        critique_prompt_with_id = critique_prompt.replace(
            "{CRITIQUE_AGENT_ID}",
            pre_generated_critique_id
        )

        result = deploy_claude_tmux_agent(
            task_id=task_id,
            agent_type=critique_agent_type,
            prompt=critique_prompt_with_id,
            parent="orchestrator",
            phase_index=-1,  # -1 indicates review-related agent
            model="claude-sonnet-4-5",  # Sonnet for critique
            agent_id=pre_generated_critique_id
        )
        if result.get('success'):
            critique_agent_id = result.get('agent_id')

            # SQLITE MIGRATION: Update review record with critique agent in SQLite
            state_db.set_critique_agent_for_review(
                workspace_base=workspace_base,
                review_id=review_id,
                critique_agent_id=critique_agent_id
            )

            logger.info(f"AUTO-PHASE-ENFORCEMENT: Spawned Sonnet critique agent {critique_agent_id}")
        else:
            logger.error(f"AUTO-PHASE-ENFORCEMENT: Failed to spawn critique: {result.get('error', 'Unknown error')}")
    except Exception as e:
        logger.error(f"AUTO-PHASE-ENFORCEMENT: Failed to spawn critique: {e}")

    # NOTE: Per-phase tester removed (Jan 2026)
    # Testing is now a mandatory final phase instead of per-phase overhead.
    # This reduces review complexity and focuses testing where it matters.

    # Build message based on what was spawned
    message_parts = [f"{len(spawned_agents)} Sonnet reviewers", "1 Sonnet critique agent"]

    return {
        "success": True,
        "review_id": review_id,
        "phase": phase_name,
        "phase_index": phase_index,
        "status": "UNDER_REVIEW",
        "num_reviewers": num_reviewers,
        "spawned_reviewer_agents": spawned_agents,
        "critique_agent_id": critique_agent_id,
        "auto_triggered": True,
        "message": f"Auto-spawned {' + '.join(message_parts)}"
    }


# NOTE: _should_spawn_tester() and _spawn_tester_agent() were REMOVED (Jan 2026)
# Per-phase testing was removed in favor of a mandatory "Final Testing" phase.
# This reduces review overhead (no tester for Investigation/Design phases) and
# focuses testing effort where it matters most - after all implementation is complete.
# The Final Testing phase is auto-appended to task phases in create_real_task().

# NOTE: trigger_agentic_review() was REMOVED (Jan 2026)
# This was duplicate code of _auto_spawn_phase_reviewers() with bugs:
# - Used wrong phase_index (current_phase_idx from registry instead of actual phase)
# - Caused reviewers to evaluate against wrong phase context
# All review triggering now goes through _auto_spawn_phase_reviewers() which is
# called automatically by update_agent_progress when all phase agents complete.


@mcp.tool()
def submit_review_verdict(
    task_id: str,
    review_id: str,
    reviewer_agent_id: str,
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
        reviewer_agent_id: The agent ID of the reviewer submitting this verdict
        verdict: "approved", "rejected", or "needs_revision"
        findings: List of findings, each with:
            - type: "issue", "suggestion", "blocker", or "praise"
            - severity: "critical", "high", "medium", or "low"
            - message: Description of the finding
        reviewer_notes: Optional summary notes

    Returns:
        Dict with submission status and review progress
    """
    from orchestrator.review import REVIEW_VERDICTS

    # Validate verdict
    if verdict not in REVIEW_VERDICTS:
        return json.dumps({
            "success": False,
            "error": f"Invalid verdict '{verdict}'. Must be: approved, rejected, needs_revision"
        })

    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    workspace_base = get_workspace_base_from_task_workspace(workspace)

    # SQLITE MIGRATION: Use SQLite for all verdict recording and aggregation
    # No more LockedRegistryFile - SQLite handles concurrency natively

    # 1. Record the verdict in SQLite
    record_result = state_db.record_review_verdict(
        workspace_base=workspace_base,
        review_id=review_id,
        task_id=task_id,
        reviewer_agent_id=reviewer_agent_id,
        verdict=verdict,
        findings=findings,
        reviewer_notes=reviewer_notes
    )

    if not record_result.get('success'):
        return json.dumps({
            "success": False,
            "error": record_result.get('error', 'Failed to record verdict')
        })

    # 2. Check if all reviewers have submitted
    is_complete, final_verdict, all_verdicts = state_db.check_review_complete(
        workspace_base=workspace_base,
        review_id=review_id
    )

    result_info = {
        "success": True,
        "review_id": review_id,
        "verdict_submitted": verdict,
        "findings_count": len(findings),
        "reviewers_submitted": record_result.get('submitted_count', 1),
        "reviewers_expected": record_result.get('expected_count', 2),
        "all_submitted": is_complete
    }

    # 3. If all reviewers submitted, aggregate and finalize
    if is_complete:
        # Get critique info if available
        critique_data = state_db.get_critique(workspace_base=workspace_base, review_id=review_id)
        if critique_data:
            result_info['critique_summary'] = critique_data.get('summary', '')
            result_info['critique_recommendations'] = critique_data.get('recommendations', [])

        # Get review record to find phase_index
        review_data = state_db.get_review(workspace_base=workspace_base, review_id=review_id)
        phase_index = review_data.get('phase_index', 0) if review_data else 0

        # 4. Finalize the review - updates phase status atomically
        finalize_success = state_db.finalize_review(
            workspace_base=workspace_base,
            task_id=task_id,
            review_id=review_id,
            phase_index=phase_index,
            final_verdict=final_verdict
        )

        if finalize_success:
            result_info['final_verdict'] = final_verdict
            result_info['review_completed'] = True
            result_info['phase_index'] = phase_index

            # Get updated phase status
            phase_data = state_db.get_phase(workspace_base=workspace_base, task_id=task_id, phase_index=phase_index)
            if phase_data:
                result_info['phase_status'] = phase_data.get('status')
                result_info['phase_name'] = phase_data.get('name')

            # Check if next phase was activated
            next_phase = state_db.get_phase(workspace_base=workspace_base, task_id=task_id, phase_index=phase_index + 1)
            if next_phase and next_phase.get('status') == 'ACTIVE':
                result_info['advanced_to_phase'] = next_phase.get('name')

            # Populate phase_outcomes table for context accumulator
            _populate_phase_outcome(
                workspace_base=workspace_base,
                task_id=task_id,
                phase_index=phase_index,
                review_id=review_id,
                final_verdict=final_verdict
            )

            # Auto-generate handover for approved phases
            if final_verdict == 'approved':
                try:
                    phase_name_for_handover = result_info.get('phase_name', f"Phase {phase_index + 1}")
                    phase_id = f"phase-{phase_index}"

                    # Load registry for handover generation
                    registry_path = os.path.join(workspace, "registry.json")
                    registry = {}
                    if os.path.exists(registry_path):
                        try:
                            with open(registry_path, 'r') as f:
                                registry = json.load(f)
                        except Exception as reg_err:
                            logger.warning(f"Could not load registry for handover: {reg_err}")

                    # Use auto_generate_handover which properly collects from findings/ AND archive/
                    from orchestrator.handover import auto_generate_handover, save_handover as save_handover_doc
                    handover_doc = auto_generate_handover(
                        task_workspace=workspace,
                        phase_id=phase_id,
                        phase_name=phase_name_for_handover,
                        registry=registry
                    )

                    # Enhance handover with review verdict data
                    review_data = state_db.get_review(workspace_base=workspace_base, review_id=review_id)
                    if review_data:
                        # Add reviewer feedback to handover recommendations
                        reviewer_notes = review_data.get('reviewer_notes', '')
                        if reviewer_notes:
                            handover_doc.recommendations.insert(0, f"Reviewer notes: {reviewer_notes}")

                    save_result = save_handover_doc(workspace, handover_doc)
                    logger.info(f"PHASE-APPROVAL: Auto-generated handover for phase {phase_id}: {save_result.get('path', 'unknown')}")
                    result_info['handover_generated'] = True
                    result_info['handover_path'] = save_result.get('path')
                    result_info['handover_findings_count'] = len(handover_doc.key_findings)
                except Exception as e:
                    logger.error(f"PHASE-APPROVAL: Failed to auto-generate handover: {e}", exc_info=True)
                    result_info['handover_generated'] = False
                    result_info['handover_error'] = str(e)
        else:
            result_info['finalize_error'] = "Failed to finalize review"

    # 5. Update reviewer agent status to completed in SQLite
    # Find which agent submitted this verdict and mark them done
    try:
        # Get review record to find reviewer agents
        review_data = state_db.get_review(workspace_base=workspace_base, review_id=review_id)
        if review_data:
            reviewer_agents = review_data.get('reviewer_agent_ids', [])
            # Mark all reviewer agents for this review as completed if they're still active
            for agent_id in reviewer_agents:
                state_db.update_agent_status(
                    workspace_base=workspace_base,
                    task_id=task_id,
                    agent_id=agent_id,
                    new_status='completed'
                )
    except Exception as e:
        logger.warning(f"VERDICT: Failed to update reviewer agent status: {e}")

    return json.dumps(result_info, indent=2)


@mcp.tool()
def submit_critique(
    task_id: str,
    review_id: str,
    critique_agent_id: str,
    observations: List[Dict[str, Any]],
    summary: str,
    recommendations: Optional[List[str]] = None
) -> str:
    """
    Submit a critique (called by the critique agent - NOT a reviewer).

    The critique agent provides senior developer perspective without a verdict.
    Their observations inform the orchestrator but don't affect phase approval.

    Args:
        task_id: Task ID
        review_id: Review ID from the review process
        critique_agent_id: The agent ID of the critique agent submitting this
        observations: List of observations, each with:
            - type: "architectural", "technical_debt", "suggestion", "concern", "praise"
            - priority: "high", "medium", "low" (how important to address)
            - message: Description of the observation
            - scope: "current_phase" | "future_phases" | "overall"
        summary: High-level summary from senior dev perspective
        recommendations: Optional list of recommendations for orchestrator

    Returns:
        Dict with submission status
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    workspace_base = get_workspace_base_from_task_workspace(workspace)

    # SQLITE MIGRATION: Use SQLite for critique recording
    # No more LockedRegistryFile - SQLite handles concurrency natively

    # 1. Record the critique in SQLite
    record_result = state_db.record_critique(
        workspace_base=workspace_base,
        review_id=review_id,
        task_id=task_id,
        critique_agent_id=critique_agent_id,
        observations=observations,
        summary=summary,
        recommendations=recommendations
    )

    if not record_result.get('success'):
        return json.dumps({
            "success": False,
            "error": record_result.get('error', 'Failed to record critique')
        })

    # 2. Get review status to check if ready to finalize
    review_data = state_db.get_review(workspace_base=workspace_base, review_id=review_id)

    num_expected_reviewers = 2
    num_verdicts = 0

    if review_data:
        num_expected_reviewers = review_data.get('num_reviewers', 2)
        # Count verdicts from SQLite
        verdicts = state_db.get_review_verdicts(workspace_base=workspace_base, review_id=review_id)
        num_verdicts = len(verdicts) if verdicts else 0

    result_info = {
        "success": True,
        "review_id": review_id,
        "critique_submitted": True,
        "observations_count": len(observations),
        "verdicts_submitted": num_verdicts,
        "verdicts_expected": num_expected_reviewers,
        "ready_to_finalize": num_verdicts >= num_expected_reviewers
    }

    # 3. Update critique agent status to completed
    if review_data and review_data.get('critique_agent_id'):
        critique_agent_id = review_data['critique_agent_id']
        state_db.update_agent_status(
            workspace_base=workspace_base,
            task_id=task_id,
            agent_id=critique_agent_id,
            new_status='completed'
        )
        logger.info(f"CRITIQUE STATUS UPDATE: {critique_agent_id} marked completed")

    if num_verdicts >= num_expected_reviewers:
        result_info['message'] = "Critique received. Review is ready for verdict aggregation."
    else:
        result_info['message'] = f"Critique received. Waiting for {num_expected_reviewers - num_verdicts} more verdict(s)."

    return json.dumps(result_info, indent=2)


@mcp.tool()
def get_review_status(task_id: str, review_id: Optional[str] = None) -> str:
    """
    Get status of agentic review(s) for a task.

    SQLITE MIGRATION: Now reads reviews from SQLite instead of JSON.

    Args:
        task_id: Task ID
        review_id: Optional specific review ID. If None, returns all reviews.

    Returns:
        Dict with review status, verdicts submitted, and final outcome
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    workspace_base = get_workspace_base_from_task_workspace(workspace)

    # SQLITE MIGRATION: Read reviews from SQLite
    reviews = state_db.get_reviews_for_task(workspace_base=workspace_base, task_id=task_id)

    if review_id:
        # Find specific review
        for rev in reviews:
            if rev.get('review_id') == review_id:
                # Get verdicts for this review
                verdicts = state_db.get_review_verdicts(workspace_base=workspace_base, review_id=review_id)
                rev['verdicts'] = verdicts
                return json.dumps({
                    "success": True,
                    "review": rev
                }, indent=2)
        return json.dumps({"success": False, "error": f"Review {review_id} not found"})

    # Return all reviews with verdict counts
    for rev in reviews:
        verdicts = state_db.get_review_verdicts(workspace_base=workspace_base, review_id=rev.get('review_id', ''))
        rev['verdicts_submitted'] = len(verdicts)
        rev['verdicts'] = verdicts

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

    SQLITE MIGRATION: Now reads/writes reviews and agents via SQLite.

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

    workspace_base = get_workspace_base_from_task_workspace(workspace)

    # SQLITE MIGRATION: Read review from SQLite
    target_review = state_db.get_review(workspace_base=workspace_base, review_id=review_id)
    if not target_review:
        return json.dumps({"success": False, "error": f"Review {review_id} not found"})

    if target_review.get('status') == 'completed':
        return json.dumps({
            "success": False,
            "error": "Cannot abort a completed review",
            "hint": "Use submit_phase_for_review to start a new review cycle"
        })

    # Get verdicts count before abort
    verdicts = state_db.get_review_verdicts(workspace_base=workspace_base, review_id=review_id)
    verdicts_received = len(verdicts)

    # Abort the review in SQLite
    state_db.abort_review(
        workspace_base=workspace_base,
        review_id=review_id,
        reason=reason
    )

    # Get task snapshot for phase info
    task_snapshot = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id)
    phases = task_snapshot.get('phases', []) if task_snapshot else []
    current_idx = task_snapshot.get('current_phase_index', 0) if task_snapshot else 0

    # Determine new phase status
    new_phase_status = 'ACTIVE'
    if current_idx < len(phases):
        current_phase = phases[current_idx]
        current_status = current_phase.get('status')

        if current_status == 'ESCALATED':
            new_phase_status = 'AWAITING_REVIEW'
            logger.info(f"Phase {current_idx} reset from ESCALATED to AWAITING_REVIEW")
        elif current_phase.get('revision_count', 0) > 0:
            new_phase_status = 'REVISING'

        # Update phase status in SQLite
        state_db.update_phase_status(
            workspace_base=workspace_base,
            task_id=task_id,
            phase_index=current_idx,
            new_status=new_phase_status
        )

    # Kill any running reviewer agents from this review
    killed_agents = []
    reviewer_agent_ids = target_review.get('reviewer_agent_ids', [])
    if isinstance(reviewer_agent_ids, str):
        try:
            reviewer_agent_ids = json.loads(reviewer_agent_ids)
        except:
            reviewer_agent_ids = []

    agents = task_snapshot.get('agents', []) if task_snapshot else []
    for agent in agents:
        agent_id = agent.get('agent_id')
        if agent_id in reviewer_agent_ids and agent.get('status') in ['running', 'working']:
            tmux_session = agent.get('tmux_session')
            if tmux_session:
                try:
                    subprocess.run(
                        ['tmux', 'kill-session', '-t', tmux_session],
                        capture_output=True, timeout=5
                    )
                    killed_agents.append(agent_id)
                    # Update agent status in SQLite
                    state_db.update_agent_status(
                        workspace_base=workspace_base,
                        task_id=task_id,
                        agent_id=agent_id,
                        new_status='terminated'
                    )
                except Exception as e:
                    logger.warning(f"Failed to kill reviewer {agent_id}: {e}")

    return json.dumps({
        "success": True,
        "review_id": review_id,
        "status": "aborted",
        "reason": reason,
        "verdicts_received_before_abort": verdicts_received,
        "killed_reviewers": killed_agents,
        "phase_returned_to": new_phase_status,
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


# ============================================================================
# CONTEXT ACCUMULATOR MCP TOOL (Jan 2026)
# ============================================================================


@mcp.tool()
def get_accumulated_task_context(
    task_id: str,
    phase_index: Optional[int] = None,
    include_all_findings: bool = False,
    max_tokens: int = 2000
) -> str:
    """
    Get accumulated context for a task.

    Use this to refresh context mid-execution or get more detail
    than what was injected at deployment time.

    This is useful for:
    - Long-running agents that need updated findings from peers
    - Fix agents that want full rejection context
    - Agents that need to understand decisions from earlier phases

    Args:
        task_id: Task ID to get context for
        phase_index: Optional - defaults to current phase
        include_all_findings: If True, include all findings (not just critical/high)
        max_tokens: Maximum token budget for response

    Returns:
        JSON with accumulated context including:
        - original_task: Original task description
        - current_phase: Current phase info with deliverables
        - phase_summaries: Summary of previous phases
        - critical_findings: High/critical severity findings
        - rejection_context: If phase was rejected, what to fix
    """
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"success": False, "error": f"Task {task_id} not found"})

    workspace_base = get_workspace_base_from_task_workspace(workspace)

    # Get current phase index if not specified
    if phase_index is None:
        task_snapshot = state_db.load_task_snapshot(workspace_base=workspace_base, task_id=task_id)
        if task_snapshot:
            phase_index = task_snapshot.get('current_phase_index', 0)
        else:
            phase_index = 0

    try:
        # Build accumulated context
        ctx = build_task_context_accumulator(
            workspace_base=workspace_base,
            task_id=task_id,
            current_phase_index=phase_index,
            max_tokens=max_tokens
        )

        # Build response
        result = {
            "success": True,
            "task_id": task_id,
            "phase_index": phase_index,

            # Immutable core
            "original_task": ctx.original_description[:500] if ctx.original_description else "",
            "constraints": ctx.constraints[:5],
            "expected_deliverables": ctx.expected_deliverables[:10],
            "project_context": ctx.project_context,

            # Current phase
            "current_phase": {
                "name": ctx.current_phase_name,
                "description": ctx.current_phase_description[:200] if ctx.current_phase_description else "",
                "deliverables": ctx.current_phase_deliverables[:10],
                "success_criteria": ctx.current_phase_success_criteria[:10],
            },

            # Previous phases
            "phase_summaries": ctx.phase_summaries,

            # Findings
            "critical_findings": ctx.critical_findings[:20] if include_all_findings else ctx.critical_findings[:10],
            "active_blockers": ctx.active_blockers[:5],

            # Rejection context
            "was_rejected": ctx.was_rejected,
            "rejection_findings": ctx.rejection_findings[:10] if ctx.was_rejected else [],
            "rejection_notes": ctx.rejection_notes[:300] if ctx.was_rejected else "",

            # Token info
            "estimated_tokens": ctx.estimated_tokens,
        }

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"get_accumulated_task_context failed for {task_id}: {e}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": str(e),
            "task_id": task_id
        })


def cleanup_dead_agents_from_global_registry() -> Dict[str, Any]:
    """
    SQLITE MIGRATION: Now scans SQLite for active agents with dead tmux sessions.

    This function:
    1. Reads all active agents from SQLite (across all tasks)
    2. Checks if their tmux sessions are still running
    3. Marks agents with dead tmux sessions as 'failed' via SQLite

    Note: SQLite doesn't use a counter - active count is derived from agent statuses.

    Returns:
        Dict with cleanup statistics
    """
    workspace_base = resolve_workspace_variables(WORKSPACE_BASE)

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
    still_running_count = 0
    missing_tmux_field = 0

    try:
        # Get all active agents from SQLite
        active_agents = state_db.get_all_active_agents(workspace_base=workspace_base)

        for agent in active_agents:
            agent_id = agent.get('agent_id')
            tmux_session = agent.get('tmux_session')
            task_id = agent.get('task_id')

            # No tmux session field
            if not tmux_session:
                missing_tmux_field += 1
                dead_agents.append(agent_id)
                continue

            # Check if tmux session is running
            if tmux_session in running_sessions:
                still_running_count += 1
                continue

            # Tmux session is dead - mark agent as failed
            dead_agents.append(agent_id)
            logger.info(f"Found dead agent: {agent_id} (task: {task_id}, tmux: {tmux_session})")

        # Batch update dead agents
        cleaned_count = 0
        if dead_agents:
            cleaned_count = state_db.mark_agents_as_failed_batch(
                workspace_base=workspace_base,
                agent_ids=dead_agents,
                reason='Global cleanup: tmux session dead'
            )
            logger.info(f"Global registry cleanup: {cleaned_count} dead agents marked as failed via SQLite")

        # Get final active count from SQLite
        # Note: This is an estimate - we don't have a global count, just per-task
        # For now we just report successful cleanup
        return {
            "success": True,
            "cleaned_count": cleaned_count,
            "still_running": still_running_count,
            "missing_tmux_field": missing_tmux_field,
            "dead_agents": dead_agents[:20],  # Limit to first 20 for readability
            "running_sessions_detected": len(running_sessions),
            "total_active_checked": len(active_agents),
            "storage": "sqlite",
            "message": f"Cleaned up {cleaned_count} dead agents via SQLite"
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
