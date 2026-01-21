"""
Claude Orchestrator Module

A modular orchestration system for managing Claude Code agents across phases.

Modules:
- registry: Atomic registry operations with file locking
- workspace: Workspace directory management
- deployment: Agent deployment (tmux)
- tasks: Task validation and creation
- status: Status retrieval and JSONL parsing
- lifecycle: Agent lifecycle management
- handover: Phase handover documents for context preservation
"""

from .registry import (
    # Version Locking
    StaleVersionError,
    atomic_check_version,
    version_guarded_update,
    # Phase Schema
    PhaseStatus,
    VALID_PHASE_TRANSITIONS,
    create_phase,
    get_phase_by_id,
    get_current_phase,
    get_next_phase,
    is_valid_phase_transition,
    # Phase Transition Functions (MIT-002)
    AGENT_TERMINAL_STATUSES,
    AGENT_ACTIVE_STATUSES,
    check_phase_completion,
    atomic_check_and_transition_phase,
    try_advance_to_review,
    advance_phase,
    get_previous_phase_handover,
    # Phase-Agent Binding (MIT-003)
    validate_agent_phase,
    get_phase_agents,
    mark_phase_agents_completed,
    # Registry Operations
    LockedRegistryFile,
    atomic_add_agent,
    atomic_update_agent_status,
    atomic_increment_counts,
    atomic_decrement_active_count,
    atomic_mark_agents_completed,
    get_global_registry_path,
    read_registry_with_lock,
    write_registry_with_lock,
    ensure_global_registry,
    configure_registry,
    # Registry Health
    registry_health_check,
    generate_health_recommendations,
    validate_and_repair_registry,
)

from .workspace import (
    WORKSPACE_BASE,
    DEFAULT_MAX_CONCURRENT,
    find_task_workspace,
    get_workspace_base_from_task_workspace,
    ensure_workspace,
    check_disk_space,
    test_write_access,
    resolve_workspace_variables,
)

from .context import (
    parse_markdown_context,
    detect_project_context,
    format_project_context_prompt,
    clear_context_cache,
)

from .prompts import (
    generate_specialization_recommendations,
    format_task_enrichment_prompt,
    create_orchestration_guidance_prompt,
    get_investigator_requirements,
    get_builder_requirements,
    get_fixer_requirements,
    get_universal_protocol,
    get_type_specific_requirements,
    format_previous_phase_handover,
)

from .context_accumulator import (
    TaskContextAccumulator,
    build_task_context_accumulator,
    format_accumulated_context,
)

from .deployment import (
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

from .tasks import (
    TaskValidationError,
    TaskValidationWarning,
    validate_task_parameters,
    calculate_task_complexity,
    extract_text_from_message_content,
    truncate_conversation_history,
    # Phase validation
    PHASE_STATUSES,
    PhaseValidationError,
    create_default_phase,
    validate_phases,
    ensure_task_has_phases,
)

from .status import (
    MAX_LINE_LENGTH,
    MAX_TOOL_RESULT_CONTENT,
    MAX_ASSISTANT_TEXT,
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
)

from .lifecycle import (
    kill_real_agent,
    cleanup_agent_resources,
    update_agent_progress,
    report_agent_finding,
    spawn_child_agent,
    get_minimal_coordination_info,
    validate_agent_completion,
)

from .handover import (
    # Constants
    HANDOVER_MAX_TOKENS,
    HANDOVER_MAX_CHARS,
    CHARS_PER_TOKEN,
    # Schema
    HandoverDocument,
    FindingDict,
    ArtifactDict,
    MetricsDict,
    # Token utilities
    count_tokens,
    truncate_to_tokens,
    truncate_list_to_tokens,
    # Path utilities
    get_handover_path,
    ensure_handovers_dir,
    # Markdown formatting
    format_handover_markdown,
    parse_handover_markdown,
    # File operations
    save_handover,
    load_handover,
    list_handovers,
    get_previous_handover,
    # Auto-generation
    auto_generate_handover,
    collect_phase_findings,
    # MCP tool wrappers
    submit_phase_handover,
    get_phase_handover,
    get_handover_context,
)

from .review import (
    # Enums
    ReviewStatus,
    ReviewVerdict,
    # Constants
    REVIEW_VERDICTS,
    REVIEW_FINDING_TYPES,
    REVIEW_FINDING_SEVERITIES,
    DEFAULT_MIN_REVIEWERS,
    DEFAULT_REQUIRE_UNANIMOUS,
    DEFAULT_AUTO_APPROVE_THRESHOLD,
    DEFAULT_TIMEOUT_SECONDS,
    # Dataclasses
    ReviewFinding,
    ReviewAgent,
    ReviewConfig,
    # TypedDicts
    ReviewFindingDict,
    ReviewAgentDict,
    ReviewConfigDict,
    # Helper functions
    create_review_agent,
    validate_verdict,
    validate_finding_type,
    determine_verdict_from_findings,
    # Verdict submission and phase transition functions
    submit_review_verdict,
    calculate_aggregate_verdict,
    finalize_phase_review,
    format_review_for_handover,
    # Review triggering and record creation functions
    create_review_record,
    trigger_phase_review,
    get_phase_reviews,
    # MCP tool wrapper functions
    request_phase_review,
    submit_review,
    get_review_status,
    get_review_context,
)

__all__ = [
    # Version Locking
    'StaleVersionError',
    'atomic_check_version',
    'version_guarded_update',
    # Phase Schema
    'PhaseStatus',
    'VALID_PHASE_TRANSITIONS',
    'create_phase',
    'get_phase_by_id',
    'get_current_phase',
    'get_next_phase',
    'is_valid_phase_transition',
    # Phase Transition Functions (MIT-002)
    'AGENT_TERMINAL_STATUSES',
    'AGENT_ACTIVE_STATUSES',
    'check_phase_completion',
    'atomic_check_and_transition_phase',
    'try_advance_to_review',
    'advance_phase',
    'get_previous_phase_handover',
    # Phase-Agent Binding (MIT-003)
    'validate_agent_phase',
    'get_phase_agents',
    'mark_phase_agents_completed',
    # Registry
    'LockedRegistryFile',
    'atomic_add_agent',
    'atomic_update_agent_status',
    'atomic_increment_counts',
    'atomic_decrement_active_count',
    'atomic_mark_agents_completed',
    'get_global_registry_path',
    'read_registry_with_lock',
    'write_registry_with_lock',
    'ensure_global_registry',
    'configure_registry',
    # Registry Health
    'registry_health_check',
    'generate_health_recommendations',
    'validate_and_repair_registry',
    # Workspace
    'WORKSPACE_BASE',
    'DEFAULT_MAX_CONCURRENT',
    'find_task_workspace',
    'get_workspace_base_from_task_workspace',
    'ensure_workspace',
    'check_disk_space',
    'test_write_access',
    'resolve_workspace_variables',
    # Context Detection
    'parse_markdown_context',
    'detect_project_context',
    'format_project_context_prompt',
    'clear_context_cache',
    # Prompt Generation
    'generate_specialization_recommendations',
    'format_task_enrichment_prompt',
    'create_orchestration_guidance_prompt',
    'get_investigator_requirements',
    'get_builder_requirements',
    'get_fixer_requirements',
    'get_universal_protocol',
    'get_type_specific_requirements',
    'format_previous_phase_handover',
    # Context Accumulator (Jan 2026)
    'TaskContextAccumulator',
    'build_task_context_accumulator',
    'format_accumulated_context',
    # Deployment
    'check_tmux_available',
    'create_tmux_session',
    'get_tmux_session_output',
    'check_tmux_session_exists',
    'kill_tmux_session',
    'list_all_tmux_sessions',
    'find_existing_agent',
    'verify_agent_id_unique',
    'generate_unique_agent_id',
    # Tasks
    'TaskValidationError',
    'TaskValidationWarning',
    'validate_task_parameters',
    'calculate_task_complexity',
    'extract_text_from_message_content',
    'truncate_conversation_history',
    # Phase validation
    'PHASE_STATUSES',
    'PhaseValidationError',
    'create_default_phase',
    'validate_phases',
    'ensure_task_has_phases',
    # Status
    'MAX_LINE_LENGTH',
    'MAX_TOOL_RESULT_CONTENT',
    'MAX_ASSISTANT_TEXT',
    'read_jsonl_lines',
    'tail_jsonl_efficient',
    'filter_lines_regex',
    'parse_jsonl_lines',
    'format_output_by_type',
    'collect_log_metadata',
    'detect_repetitive_content',
    'extract_critical_lines',
    'intelligent_sample_lines',
    'summarize_output',
    'smart_preview_truncate',
    'line_based_truncate',
    'simple_truncate',
    'truncate_coordination_info',
    'detect_and_truncate_binary',
    'is_already_truncated',
    'truncate_json_structure',
    'safe_json_truncate',
    # Lifecycle
    'kill_real_agent',
    'cleanup_agent_resources',
    'update_agent_progress',
    'report_agent_finding',
    'spawn_child_agent',
    'get_minimal_coordination_info',
    'validate_agent_completion',
    # Handover - Constants
    'HANDOVER_MAX_TOKENS',
    'HANDOVER_MAX_CHARS',
    'CHARS_PER_TOKEN',
    # Handover - Schema
    'HandoverDocument',
    'FindingDict',
    'ArtifactDict',
    'MetricsDict',
    # Handover - Token utilities
    'count_tokens',
    'truncate_to_tokens',
    'truncate_list_to_tokens',
    # Handover - Path utilities
    'get_handover_path',
    'ensure_handovers_dir',
    # Handover - Markdown formatting
    'format_handover_markdown',
    'parse_handover_markdown',
    # Handover - File operations
    'save_handover',
    'load_handover',
    'list_handovers',
    'get_previous_handover',
    # Handover - Auto-generation
    'auto_generate_handover',
    'collect_phase_findings',
    # Handover - MCP tool wrappers
    'submit_phase_handover',
    'get_phase_handover',
    'get_handover_context',
    # Review - Enums
    'ReviewStatus',
    'ReviewVerdict',
    # Review - Constants
    'REVIEW_VERDICTS',
    'REVIEW_FINDING_TYPES',
    'REVIEW_FINDING_SEVERITIES',
    'DEFAULT_MIN_REVIEWERS',
    'DEFAULT_REQUIRE_UNANIMOUS',
    'DEFAULT_AUTO_APPROVE_THRESHOLD',
    'DEFAULT_TIMEOUT_SECONDS',
    # Review - Dataclasses
    'ReviewFinding',
    'ReviewAgent',
    'ReviewConfig',
    # Review - TypedDicts
    'ReviewFindingDict',
    'ReviewAgentDict',
    'ReviewConfigDict',
    # Review - Helper functions
    'create_review_agent',
    'validate_verdict',
    'validate_finding_type',
    'determine_verdict_from_findings',
    # Review - Verdict submission and phase transition
    'submit_review_verdict',
    'calculate_aggregate_verdict',
    'finalize_phase_review',
    'format_review_for_handover',
    # Review - Triggering and record creation
    'create_review_record',
    'trigger_phase_review',
    'get_phase_reviews',
    # Review - MCP tool wrapper functions
    'request_phase_review',
    'submit_review',
    'get_review_status',
    'get_review_context',
]
