"""
Context Accumulator for Claude Orchestrator MCP.

This module builds comprehensive context from SQLite for agent prompt injection,
solving the context drift problem where later phases lose track of original
task requirements and earlier phase decisions.

Design principles:
1. Query SQLite directly (no filesystem reads)
2. Token budget management with priority-based truncation
3. Structured data preservation (not lossy markdown conversion)
4. Explicit rejection context for fix agents
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import state_db

logger = logging.getLogger(__name__)

# Token budget constants
DEFAULT_MAX_TOKENS = 2500
SECTION_BUDGETS = {
    "task_description": 300,
    "phase_deliverables": 200,
    "rejection_findings": 400,
    "critical_findings": 500,
    "key_decisions": 300,
    "phase_summaries": 400,
    "project_context": 200,
    "blockers": 200,
}

# Severity priority for sorting findings
SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def _estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 chars per token for English."""
    if not text:
        return 0
    return len(text) // 4


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to approximately max_tokens."""
    if not text:
        return ""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 3] + "..."


@dataclass
class TaskContextAccumulator:
    """
    Accumulated context for an agent, built from SQLite queries.

    This is dynamically constructed - not stored as a blob.
    """
    # === IMMUTABLE CORE ===
    task_id: str
    original_description: str
    constraints: List[str] = field(default_factory=list)
    expected_deliverables: List[str] = field(default_factory=list)
    success_criteria: List[str] = field(default_factory=list)
    project_context: Dict[str, Any] = field(default_factory=dict)
    background_context: str = ""
    relevant_files: List[str] = field(default_factory=list)

    # === CURRENT PHASE CONTEXT ===
    current_phase_index: int = 0
    current_phase_name: str = ""
    current_phase_description: str = ""
    current_phase_deliverables: List[str] = field(default_factory=list)
    current_phase_success_criteria: List[str] = field(default_factory=list)

    # === MUTABLE STATE FROM PREVIOUS PHASES ===
    phase_summaries: List[Dict[str, Any]] = field(default_factory=list)
    critical_findings: List[Dict[str, Any]] = field(default_factory=list)
    blockers_resolved: List[str] = field(default_factory=list)
    active_blockers: List[str] = field(default_factory=list)

    # === REJECTION CONTEXT ===
    was_rejected: bool = False
    rejection_findings: List[Dict[str, Any]] = field(default_factory=list)
    rejection_notes: str = ""

    # === TOKEN TRACKING ===
    estimated_tokens: int = 0


def build_task_context_accumulator(
    *,
    workspace_base: str,
    task_id: str,
    current_phase_index: int,
    max_tokens: int = DEFAULT_MAX_TOKENS
) -> TaskContextAccumulator:
    """
    Build accumulated context by querying SQLite.

    This replaces the filesystem-based format_previous_phase_handover()
    with pure SQLite queries for reliable, structured context.

    Args:
        workspace_base: Base directory for task workspace
        task_id: Task identifier
        current_phase_index: The phase this agent is being deployed to
        max_tokens: Maximum token budget for context section

    Returns:
        TaskContextAccumulator with all relevant context
    """
    ctx = TaskContextAccumulator(
        task_id=task_id,
        original_description="",
        current_phase_index=current_phase_index
    )

    try:
        # 1. Get task and task_config (immutable core)
        _load_task_core(workspace_base, task_id, ctx)

        # 2. Get current phase info
        _load_current_phase(workspace_base, task_id, current_phase_index, ctx)

        # 3. Get phase outcomes from previous phases
        _load_phase_outcomes(workspace_base, task_id, current_phase_index, ctx)

        # 4. Get critical/high findings from all previous phases
        _load_critical_findings(workspace_base, task_id, current_phase_index, ctx)

        # 5. Check for rejection context (if current phase was previously rejected)
        _load_rejection_context(workspace_base, task_id, current_phase_index, ctx)

        # 6. Calculate estimated tokens
        ctx.estimated_tokens = _estimate_context_tokens(ctx)

    except Exception as e:
        logger.error(f"Error building context accumulator for {task_id}: {e}")
        # Return partial context rather than failing completely
        ctx.original_description = f"[Error loading context: {e}]"

    return ctx


def _load_task_core(workspace_base: str, task_id: str, ctx: TaskContextAccumulator) -> None:
    """Load immutable task core from tasks and task_config tables."""
    db_path = state_db.get_state_db_path(workspace_base)
    conn = state_db._connect(db_path)
    try:
        # Get task description
        task_row = conn.execute(
            "SELECT description FROM tasks WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        if task_row:
            ctx.original_description = task_row["description"] or ""

        # Get task_config
        config_row = conn.execute(
            """SELECT project_context, constraints, relevant_files,
                      background_context, expected_deliverables, success_criteria
               FROM task_config WHERE task_id = ?""",
            (task_id,)
        ).fetchone()

        if config_row:
            # Parse JSON fields
            if config_row["project_context"]:
                try:
                    ctx.project_context = json.loads(config_row["project_context"])
                except Exception:
                    ctx.project_context = {}

            if config_row["constraints"]:
                try:
                    ctx.constraints = json.loads(config_row["constraints"])
                except Exception:
                    ctx.constraints = []

            if config_row["relevant_files"]:
                try:
                    ctx.relevant_files = json.loads(config_row["relevant_files"])[:10]  # Limit
                except Exception:
                    ctx.relevant_files = []

            ctx.background_context = config_row["background_context"] or ""

            if config_row["expected_deliverables"]:
                try:
                    ctx.expected_deliverables = json.loads(config_row["expected_deliverables"])
                except Exception:
                    ctx.expected_deliverables = []

            if config_row["success_criteria"]:
                try:
                    ctx.success_criteria = json.loads(config_row["success_criteria"])
                except Exception:
                    ctx.success_criteria = []

    finally:
        conn.close()


def _load_current_phase(
    workspace_base: str,
    task_id: str,
    phase_index: int,
    ctx: TaskContextAccumulator
) -> None:
    """Load current phase info from phases table."""
    db_path = state_db.get_state_db_path(workspace_base)
    conn = state_db._connect(db_path)
    try:
        phase_row = conn.execute(
            """SELECT name, description, deliverables, success_criteria, status
               FROM phases WHERE task_id = ? AND phase_index = ?""",
            (task_id, phase_index)
        ).fetchone()

        if phase_row:
            ctx.current_phase_name = phase_row["name"] or f"Phase {phase_index}"
            ctx.current_phase_description = phase_row["description"] or ""

            if phase_row["deliverables"]:
                try:
                    ctx.current_phase_deliverables = json.loads(phase_row["deliverables"])
                except Exception:
                    ctx.current_phase_deliverables = []

            if phase_row["success_criteria"]:
                try:
                    ctx.current_phase_success_criteria = json.loads(phase_row["success_criteria"])
                except Exception:
                    ctx.current_phase_success_criteria = []

    finally:
        conn.close()


def _load_phase_outcomes(
    workspace_base: str,
    task_id: str,
    current_phase_index: int,
    ctx: TaskContextAccumulator
) -> None:
    """Load phase outcomes from all previous phases."""
    # Get all outcomes up to (but not including) current phase
    outcomes = state_db.get_phase_outcomes(
        workspace_base=workspace_base,
        task_id=task_id
    )

    for outcome in outcomes:
        if outcome.get("phase_index", 0) >= current_phase_index:
            continue  # Skip current and future phases

        # Get phase name for summary
        db_path = state_db.get_state_db_path(workspace_base)
        conn = state_db._connect(db_path)
        try:
            phase_row = conn.execute(
                "SELECT name FROM phases WHERE task_id = ? AND phase_index = ?",
                (task_id, outcome["phase_index"])
            ).fetchone()
            phase_name = phase_row["name"] if phase_row else f"Phase {outcome['phase_index']}"
        finally:
            conn.close()

        summary = {
            "phase_index": outcome["phase_index"],
            "phase_name": phase_name,
            "verdict": outcome.get("review_verdict", "unknown"),
            "key_decisions": outcome.get("key_decisions", [])[:5],  # Limit
            "review_summary": _truncate_to_tokens(outcome.get("review_summary", ""), 50),
        }
        ctx.phase_summaries.append(summary)

        # Accumulate resolved blockers
        if outcome.get("blockers_resolved"):
            ctx.blockers_resolved.extend(outcome["blockers_resolved"])


def _load_critical_findings(
    workspace_base: str,
    task_id: str,
    current_phase_index: int,
    ctx: TaskContextAccumulator
) -> None:
    """Load critical/high severity findings from previous phases."""
    # Get all findings for this task
    all_findings = state_db.get_agent_findings(
        workspace_base=workspace_base,
        task_id=task_id,
        limit=200  # Get more, then filter
    )

    # Filter to previous phases and high/critical severity
    critical_findings = []
    for finding in all_findings:
        phase_idx = finding.get("phase_index", 0)
        severity = finding.get("severity", "low")

        if phase_idx >= current_phase_index:
            continue  # Skip current and future phases

        if severity not in ("critical", "high"):
            continue

        # Also track active blockers
        if finding.get("finding_type") == "blocker":
            blocker_msg = finding.get("message", "")[:100]
            if blocker_msg not in ctx.blockers_resolved:
                ctx.active_blockers.append(blocker_msg)

        critical_findings.append({
            "phase_index": phase_idx,
            "finding_type": finding.get("finding_type", "unknown"),
            "severity": severity,
            "message": _truncate_to_tokens(finding.get("message", ""), 50),
        })

    # Sort by severity (critical first) and recency
    critical_findings.sort(
        key=lambda f: (SEVERITY_ORDER.get(f["severity"], 99), -f.get("phase_index", 0))
    )

    # Limit to top findings
    ctx.critical_findings = critical_findings[:15]


def _load_rejection_context(
    workspace_base: str,
    task_id: str,
    current_phase_index: int,
    ctx: TaskContextAccumulator
) -> None:
    """Check if current phase was rejected and load rejection details."""
    db_path = state_db.get_state_db_path(workspace_base)
    conn = state_db._connect(db_path)
    try:
        # Check phase status
        phase_row = conn.execute(
            "SELECT status FROM phases WHERE task_id = ? AND phase_index = ?",
            (task_id, current_phase_index)
        ).fetchone()

        if not phase_row:
            return

        # If phase is REVISING or was REJECTED, load rejection details
        if phase_row["status"] in ("REVISING", "REJECTED"):
            ctx.was_rejected = True

            # Get the most recent review for this phase
            review_row = conn.execute(
                """SELECT review_id, verdict, reviewer_notes
                   FROM reviews
                   WHERE task_id = ? AND phase_index = ?
                   ORDER BY created_at DESC LIMIT 1""",
                (task_id, current_phase_index)
            ).fetchone()

            if review_row and review_row["verdict"] in ("rejected", "needs_revision"):
                ctx.rejection_notes = review_row["reviewer_notes"] or ""

                # Get reviewer findings
                verdict_rows = conn.execute(
                    """SELECT findings FROM review_verdicts
                       WHERE review_id = ? AND verdict IN ('rejected', 'needs_revision')""",
                    (review_row["review_id"],)
                ).fetchall()

                for verdict_row in verdict_rows:
                    if verdict_row["findings"]:
                        try:
                            findings = json.loads(verdict_row["findings"])
                            for finding in findings:
                                if finding.get("type") in ("issue", "blocker"):
                                    ctx.rejection_findings.append({
                                        "type": finding.get("type"),
                                        "severity": finding.get("severity", "medium"),
                                        "message": _truncate_to_tokens(
                                            finding.get("message", ""), 75
                                        ),
                                    })
                        except Exception:
                            pass

    finally:
        conn.close()


def _estimate_context_tokens(ctx: TaskContextAccumulator) -> int:
    """Estimate total tokens for the accumulated context."""
    total = 0

    total += _estimate_tokens(ctx.original_description)
    total += _estimate_tokens(ctx.background_context)
    total += _estimate_tokens(ctx.current_phase_description)

    for d in ctx.current_phase_deliverables:
        total += _estimate_tokens(d)

    for s in ctx.phase_summaries:
        total += _estimate_tokens(str(s))

    for f in ctx.critical_findings:
        total += _estimate_tokens(str(f))

    for f in ctx.rejection_findings:
        total += _estimate_tokens(str(f))

    return total


def format_accumulated_context(
    ctx: TaskContextAccumulator,
    max_tokens: int = DEFAULT_MAX_TOKENS
) -> str:
    """
    Format accumulated context for prompt injection.

    This replaces the old format_previous_phase_handover() function
    with SQLite-based context that preserves structured data.

    Args:
        ctx: TaskContextAccumulator to format
        max_tokens: Maximum token budget

    Returns:
        Formatted markdown string for prompt injection
    """
    sections = []

    # Header
    sections.append("""
===============================================================================
TASK CONTEXT ACCUMULATOR - READ CAREFULLY BEFORE STARTING
===============================================================================
""")

    # 1. Original Task (Priority 1 - never truncate)
    sections.append(f"""## Original Task
{_truncate_to_tokens(ctx.original_description, SECTION_BUDGETS["task_description"])}
""")

    # 2. Current Phase Deliverables (Priority 2 - never truncate)
    if ctx.current_phase_deliverables or ctx.current_phase_success_criteria:
        deliverables_text = ""
        if ctx.current_phase_deliverables:
            deliverables_text += "**Deliverables:**\n"
            for d in ctx.current_phase_deliverables[:10]:
                deliverables_text += f"- {d}\n"

        if ctx.current_phase_success_criteria:
            deliverables_text += "\n**Success Criteria:**\n"
            for s in ctx.current_phase_success_criteria[:10]:
                deliverables_text += f"- {s}\n"

        sections.append(f"""## Current Phase: {ctx.current_phase_name}
{ctx.current_phase_description[:200] if ctx.current_phase_description else ""}

{deliverables_text}
""")

    # 3. Rejection Issues (Priority 3 - critical for fix agents)
    if ctx.was_rejected and ctx.rejection_findings:
        rejection_text = "**YOU MUST FIX THESE ISSUES:**\n"
        for finding in ctx.rejection_findings[:10]:
            severity = finding.get("severity", "medium").upper()
            msg = finding.get("message", "")
            rejection_text += f"- [{severity}] {msg}\n"

        if ctx.rejection_notes:
            rejection_text += f"\n**Reviewer Notes:** {_truncate_to_tokens(ctx.rejection_notes, 100)}\n"

        sections.append(f"""## PHASE WAS REJECTED - FIX REQUIRED
{rejection_text}
""")

    # 4. Critical Findings from Previous Phases (Priority 4)
    if ctx.critical_findings:
        findings_text = ""
        for finding in ctx.critical_findings[:10]:
            severity = finding.get("severity", "unknown").upper()
            ftype = finding.get("finding_type", "info")
            msg = finding.get("message", "")
            phase_idx = finding.get("phase_index", 0)
            findings_text += f"- [P{phase_idx + 1}][{severity}] {ftype}: {msg}\n"

        sections.append(f"""## Critical Findings from Previous Phases
{findings_text}
""")

    # 5. Phase Summaries (Priority 6)
    if ctx.phase_summaries:
        summary_text = ""
        verdict_emoji = {
            "approved": "APPROVED",
            "rejected": "REJECTED",
            "needs_revision": "REVISION",
            "unknown": "?"
        }
        for summary in ctx.phase_summaries:
            v = summary.get("verdict", "unknown")
            name = summary.get("phase_name", f"Phase {summary.get('phase_index', 0)}")
            decisions_count = len(summary.get("key_decisions", []))
            emoji = verdict_emoji.get(v, "?")
            summary_text += f"- [{emoji}] {name}: {decisions_count} key decisions\n"

        sections.append(f"""## Previous Phase Outcomes
{summary_text}
""")

    # 6. Project Context (Priority 7)
    if ctx.project_context:
        context_items = []
        if ctx.project_context.get("dev_server_port"):
            context_items.append(f"- Dev server port: {ctx.project_context['dev_server_port']}")
        if ctx.project_context.get("test_url"):
            context_items.append(f"- Test URL: {ctx.project_context['test_url']}")
        if ctx.project_context.get("framework"):
            context_items.append(f"- Framework: {ctx.project_context['framework']}")

        if context_items:
            sections.append(f"""## Project Context
{chr(10).join(context_items)}
""")

    # 7. Active Blockers (Priority 8)
    if ctx.active_blockers:
        blockers_text = "\n".join(f"- {b}" for b in ctx.active_blockers[:5])
        sections.append(f"""## Active Blockers (Unresolved)
{blockers_text}
""")

    # Footer
    sections.append("""
===============================================================================
BUILD ON THIS CONTEXT - DO NOT DUPLICATE OR IGNORE PREVIOUS WORK
===============================================================================
""")

    full_text = "\n".join(sections)

    # Final token check - if over budget, truncate findings sections
    if _estimate_tokens(full_text) > max_tokens:
        # Remove lower priority sections until under budget
        # This is a simple approach - could be more sophisticated
        if ctx.active_blockers:
            sections = [s for s in sections if "Active Blockers" not in s]
        if ctx.project_context:
            sections = [s for s in sections if "Project Context" not in s]

        full_text = "\n".join(sections)

    return full_text


__all__ = [
    "TaskContextAccumulator",
    "build_task_context_accumulator",
    "format_accumulated_context",
]
