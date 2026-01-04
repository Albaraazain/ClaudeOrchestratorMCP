"""
Handover Document Module for Claude Orchestrator.

This module handles phase handover documents - structured markdown documents
that capture the state, findings, and recommendations from one phase to pass
to the next phase. Handovers prevent context loss between phases.

Key components:
- HandoverDocument: Dataclass defining the handover schema
- Token utilities: Count and truncate text to fit token limits
- File operations: Save/load handovers as markdown files
- Markdown formatting: Human-readable format with structured parsing

Author: Claude Code Orchestrator Project
License: MIT
"""

import os
import re
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Any, Optional, TypedDict

logger = logging.getLogger(__name__)

# ============================================================================
# CONSTANTS
# ============================================================================

# Maximum tokens for handover document content
# User specified 5000 tokens (larger than default 2000)
HANDOVER_MAX_TOKENS = 5000

# Approximate chars per token (conservative estimate)
# GPT/Claude tokenizers average ~4 chars per token, we use 3 for safety margin
CHARS_PER_TOKEN = 3

# Maximum character limits derived from token limit
HANDOVER_MAX_CHARS = HANDOVER_MAX_TOKENS * CHARS_PER_TOKEN  # ~15000 chars

# Section limits (proportion of total)
SUMMARY_MAX_TOKENS = 1000  # ~20% for summary
FINDINGS_MAX_TOKENS = 2000  # ~40% for key findings
BLOCKERS_MAX_TOKENS = 500  # ~10% for blockers
RECOMMENDATIONS_MAX_TOKENS = 1000  # ~20% for recommendations
ARTIFACTS_MAX_TOKENS = 300  # ~6% for artifacts list
METRICS_MAX_TOKENS = 200  # ~4% for metrics


# ============================================================================
# HANDOVER DOCUMENT SCHEMA
# ============================================================================

@dataclass
class HandoverDocument:
    """
    Handover document capturing phase completion state for next phase.

    This dataclass defines the structured schema for handover documents.
    Handovers are stored as markdown files but can be parsed back to this structure.

    Attributes:
        phase_id: Unique identifier of the completed phase (e.g., 'phase-abc123')
        phase_name: Human-readable phase name (e.g., 'Investigation', 'Implementation')
        created_at: ISO timestamp when handover was created
        summary: What was accomplished in this phase (max ~1000 tokens)
        key_findings: List of findings [{type, severity, message, data}]
        blockers: Issues that blocked or slowed progress
        recommendations: Suggestions for the next phase
        artifacts: Files/resources created [{path, description}]
        metrics: Phase metrics {agents_deployed, completed, failed, duration_seconds}

    Example:
        >>> handover = HandoverDocument(
        ...     phase_id="phase-abc123",
        ...     phase_name="Investigation",
        ...     summary="Analyzed codebase structure and identified 3 key issues...",
        ...     key_findings=[
        ...         {"type": "issue", "severity": "high", "message": "Race condition in registry"}
        ...     ],
        ...     blockers=["Could not access production logs"],
        ...     recommendations=["Fix race condition before adding features"],
        ...     artifacts=[{"path": "analysis.md", "description": "Full analysis report"}],
        ...     metrics={"agents_deployed": 5, "completed": 5, "failed": 0, "duration_seconds": 3600}
        ... )
    """
    phase_id: str
    phase_name: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    summary: str = ""
    key_findings: List[Dict[str, Any]] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    artifacts: List[Dict[str, str]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HandoverDocument':
        """Create HandoverDocument from dictionary."""
        return cls(
            phase_id=data.get('phase_id', ''),
            phase_name=data.get('phase_name', ''),
            created_at=data.get('created_at', datetime.now().isoformat()),
            summary=data.get('summary', ''),
            key_findings=data.get('key_findings', []),
            blockers=data.get('blockers', []),
            recommendations=data.get('recommendations', []),
            artifacts=data.get('artifacts', []),
            metrics=data.get('metrics', {})
        )


# TypedDict alternatives for type hints in function signatures
class FindingDict(TypedDict, total=False):
    """Type definition for finding entries."""
    type: str  # 'issue', 'solution', 'insight', 'recommendation'
    severity: str  # 'low', 'medium', 'high', 'critical'
    message: str
    data: Dict[str, Any]


class ArtifactDict(TypedDict):
    """Type definition for artifact entries."""
    path: str
    description: str


class MetricsDict(TypedDict, total=False):
    """Type definition for phase metrics."""
    agents_deployed: int
    completed: int
    failed: int
    duration_seconds: int


# ============================================================================
# TOKEN COUNTING UTILITIES
# ============================================================================

def count_tokens(text: str) -> int:
    """
    Approximate token count for text.

    Uses a simple heuristic: words * 1.3 (accounts for subword tokenization).
    This is an approximation - actual tokenizers like tiktoken would be more accurate
    but we avoid the dependency for simplicity.

    Args:
        text: Text to count tokens for

    Returns:
        Approximate token count

    Example:
        >>> count_tokens("Hello world, this is a test.")
        8  # 6 words * 1.3 ≈ 8
    """
    if not text:
        return 0

    # Split on whitespace and punctuation for word count
    words = re.findall(r'\b\w+\b', text)
    word_count = len(words)

    # Multiply by 1.3 to account for subword tokenization
    # (punctuation, common word splits, etc.)
    token_estimate = int(word_count * 1.3)

    return max(1, token_estimate) if text.strip() else 0


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """
    Truncate text to fit within token limit.

    Uses iterative word removal to get close to the target token count.
    Adds ellipsis to indicate truncation.

    Args:
        text: Text to truncate
        max_tokens: Maximum tokens allowed

    Returns:
        Truncated text with ellipsis if truncated

    Example:
        >>> long_text = "This is a very long text that needs truncation..."
        >>> truncate_to_tokens(long_text, 5)
        'This is a very...'
    """
    if not text:
        return ""

    current_tokens = count_tokens(text)

    if current_tokens <= max_tokens:
        return text

    # Estimate characters per token and truncate
    # Use conservative 3 chars/token for safety
    target_chars = max_tokens * CHARS_PER_TOKEN

    if len(text) <= target_chars:
        return text

    # Truncate at word boundary
    truncated = text[:target_chars]

    # Find last space to avoid cutting mid-word
    last_space = truncated.rfind(' ')
    if last_space > target_chars * 0.5:  # Only use if we don't lose too much
        truncated = truncated[:last_space]

    # Add ellipsis
    truncated = truncated.rstrip('.,;:!? ') + '...'

    logger.debug(f"Truncated text from {current_tokens} to ~{count_tokens(truncated)} tokens")

    return truncated


def truncate_list_to_tokens(items: List[str], max_tokens: int) -> List[str]:
    """
    Truncate a list of strings to fit within token limit.

    Keeps as many complete items as possible, then truncates.

    Args:
        items: List of strings to truncate
        max_tokens: Maximum total tokens for the list

    Returns:
        Truncated list of strings
    """
    if not items:
        return []

    result = []
    tokens_used = 0

    for item in items:
        item_tokens = count_tokens(item)

        if tokens_used + item_tokens <= max_tokens:
            result.append(item)
            tokens_used += item_tokens
        else:
            # Try to fit a truncated version of this item
            remaining_tokens = max_tokens - tokens_used
            if remaining_tokens > 10:  # Only if meaningful space left
                truncated_item = truncate_to_tokens(item, remaining_tokens)
                if truncated_item:
                    result.append(truncated_item)
            break

    return result


# ============================================================================
# FILE PATH UTILITIES
# ============================================================================

def get_handover_path(task_workspace: str, phase_id: str) -> str:
    """
    Get the file path for a handover document.

    Handovers are stored in {task_workspace}/handovers/phase-{id}-handover.md

    Args:
        task_workspace: Path to task workspace directory
        phase_id: Phase ID (e.g., 'phase-abc123')

    Returns:
        Full path to handover markdown file

    Example:
        >>> get_handover_path('/workspace/TASK-123', 'phase-abc123')
        '/workspace/TASK-123/handovers/phase-abc123-handover.md'
    """
    # Ensure handovers directory exists
    handovers_dir = os.path.join(task_workspace, 'handovers')

    # Build filename - use phase_id directly as it already has 'phase-' prefix
    filename = f"{phase_id}-handover.md"

    return os.path.join(handovers_dir, filename)


def ensure_handovers_dir(task_workspace: str) -> str:
    """
    Ensure the handovers directory exists within task workspace.

    Args:
        task_workspace: Path to task workspace

    Returns:
        Path to handovers directory
    """
    handovers_dir = os.path.join(task_workspace, 'handovers')
    os.makedirs(handovers_dir, exist_ok=True)
    return handovers_dir


# ============================================================================
# MARKDOWN FORMATTING
# ============================================================================

def format_handover_markdown(handover: HandoverDocument) -> str:
    """
    Format a HandoverDocument as readable markdown.

    Creates a structured markdown document with clear sections.
    Enforces token limits on each section to stay within HANDOVER_MAX_TOKENS.

    Args:
        handover: HandoverDocument to format

    Returns:
        Formatted markdown string

    Example output:
        # Phase Handover: Investigation

        **Phase ID:** phase-abc123
        **Created:** 2024-01-15T10:30:00

        ## Summary
        Analyzed the codebase and identified key issues...

        ## Key Findings
        - **[HIGH] issue:** Race condition in registry operations
        ...
    """
    lines = []

    # Header
    lines.append(f"# Phase Handover: {handover.phase_name}")
    lines.append("")
    lines.append(f"**Phase ID:** {handover.phase_id}")
    lines.append(f"**Created:** {handover.created_at}")
    lines.append("")

    # Summary section (truncate if needed)
    lines.append("## Summary")
    lines.append("")
    summary = truncate_to_tokens(handover.summary, SUMMARY_MAX_TOKENS)
    lines.append(summary if summary else "_No summary provided._")
    lines.append("")

    # Key Findings section
    lines.append("## Key Findings")
    lines.append("")
    if handover.key_findings:
        findings_tokens = 0
        for finding in handover.key_findings:
            if findings_tokens >= FINDINGS_MAX_TOKENS:
                lines.append("- _Additional findings truncated..._")
                break

            # Handle both string and dict findings
            if isinstance(finding, str):
                finding_type = 'info'
                severity = 'MEDIUM'
                message = finding
            else:
                finding_type = finding.get('type', 'info')
                severity = finding.get('severity', 'medium').upper()
                message = finding.get('message', '')

            # Format: - **[SEVERITY] type:** message
            finding_line = f"- **[{severity}] {finding_type}:** {message}"
            finding_tokens = count_tokens(finding_line)

            if findings_tokens + finding_tokens <= FINDINGS_MAX_TOKENS:
                lines.append(finding_line)
                findings_tokens += finding_tokens

                # Include data if present and space permits (only for dict findings)
                data = finding.get('data', {}) if isinstance(finding, dict) else {}
                if data and findings_tokens < FINDINGS_MAX_TOKENS - 50:
                    data_str = json.dumps(data, indent=2)
                    if count_tokens(data_str) < 100:  # Only include small data
                        lines.append(f"  ```json")
                        lines.append(f"  {data_str}")
                        lines.append(f"  ```")
                        findings_tokens += count_tokens(data_str)
            else:
                # Truncate this finding
                truncated_msg = truncate_to_tokens(message, FINDINGS_MAX_TOKENS - findings_tokens - 20)
                lines.append(f"- **[{severity}] {finding_type}:** {truncated_msg}")
                break
    else:
        lines.append("_No findings reported._")
    lines.append("")

    # Blockers section
    lines.append("## Blockers")
    lines.append("")
    if handover.blockers:
        blockers = truncate_list_to_tokens(handover.blockers, BLOCKERS_MAX_TOKENS)
        for blocker in blockers:
            lines.append(f"- {blocker}")
    else:
        lines.append("_No blockers encountered._")
    lines.append("")

    # Recommendations section
    lines.append("## Recommendations for Next Phase")
    lines.append("")
    if handover.recommendations:
        recommendations = truncate_list_to_tokens(handover.recommendations, RECOMMENDATIONS_MAX_TOKENS)
        for i, rec in enumerate(recommendations, 1):
            lines.append(f"{i}. {rec}")
    else:
        lines.append("_No specific recommendations._")
    lines.append("")

    # Artifacts section
    lines.append("## Artifacts Created")
    lines.append("")
    if handover.artifacts:
        for artifact in handover.artifacts[:10]:  # Limit to 10 artifacts
            path = artifact.get('path', 'unknown')
            desc = artifact.get('description', '')
            lines.append(f"- `{path}`: {desc}")
    else:
        lines.append("_No artifacts created._")
    lines.append("")

    # Metrics section
    lines.append("## Phase Metrics")
    lines.append("")
    if handover.metrics:
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        for key, value in handover.metrics.items():
            # Format key nicely (e.g., agents_deployed -> Agents Deployed)
            formatted_key = key.replace('_', ' ').title()
            lines.append(f"| {formatted_key} | {value} |")
    else:
        lines.append("_No metrics recorded._")
    lines.append("")

    # Footer with JSON for parsing
    lines.append("---")
    lines.append("")
    lines.append("<!-- HANDOVER_JSON_START")
    lines.append(json.dumps(handover.to_dict(), indent=2))
    lines.append("HANDOVER_JSON_END -->")

    markdown = "\n".join(lines)

    # Final token check
    total_tokens = count_tokens(markdown)
    if total_tokens > HANDOVER_MAX_TOKENS:
        logger.warning(
            f"Handover markdown exceeds token limit: {total_tokens} > {HANDOVER_MAX_TOKENS}. "
            f"Consider reducing content."
        )

    return markdown


def parse_handover_markdown(content: str) -> Optional[HandoverDocument]:
    """
    Parse a handover markdown file back to HandoverDocument.

    Extracts the embedded JSON from the markdown footer for accurate parsing.
    Falls back to regex parsing if JSON is not found.

    Args:
        content: Markdown file content

    Returns:
        HandoverDocument if parsing succeeds, None if parsing fails

    Example:
        >>> content = open('handover.md').read()
        >>> handover = parse_handover_markdown(content)
        >>> print(handover.phase_name)
        'Investigation'
    """
    if not content:
        logger.warning("Empty content provided for parsing")
        return None

    # Try to extract embedded JSON first (most reliable)
    json_match = re.search(
        r'<!-- HANDOVER_JSON_START\s*\n(.+?)\nHANDOVER_JSON_END -->',
        content,
        re.DOTALL
    )

    if json_match:
        try:
            json_str = json_match.group(1).strip()
            data = json.loads(json_str)
            logger.debug(f"Parsed handover from embedded JSON: phase_id={data.get('phase_id')}")
            return HandoverDocument.from_dict(data)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse embedded JSON: {e}")

    # Fallback: Parse from markdown structure
    logger.debug("Falling back to markdown structure parsing")

    try:
        handover_data = {}

        # Extract phase name from title
        title_match = re.search(r'# Phase Handover: (.+)', content)
        if title_match:
            handover_data['phase_name'] = title_match.group(1).strip()

        # Extract phase ID
        phase_id_match = re.search(r'\*\*Phase ID:\*\* (.+)', content)
        if phase_id_match:
            handover_data['phase_id'] = phase_id_match.group(1).strip()

        # Extract created timestamp
        created_match = re.search(r'\*\*Created:\*\* (.+)', content)
        if created_match:
            handover_data['created_at'] = created_match.group(1).strip()

        # Extract summary (text between ## Summary and next ##)
        summary_match = re.search(
            r'## Summary\s*\n\n(.+?)(?=\n## |\n---|\Z)',
            content,
            re.DOTALL
        )
        if summary_match:
            summary = summary_match.group(1).strip()
            if summary != "_No summary provided._":
                handover_data['summary'] = summary

        # Extract blockers (list items under ## Blockers)
        blockers_match = re.search(
            r'## Blockers\s*\n\n(.+?)(?=\n## |\n---|\Z)',
            content,
            re.DOTALL
        )
        if blockers_match:
            blockers_text = blockers_match.group(1).strip()
            if blockers_text != "_No blockers encountered._":
                blockers = re.findall(r'^- (.+)$', blockers_text, re.MULTILINE)
                handover_data['blockers'] = blockers

        # Extract recommendations (numbered list)
        rec_match = re.search(
            r'## Recommendations for Next Phase\s*\n\n(.+?)(?=\n## |\n---|\Z)',
            content,
            re.DOTALL
        )
        if rec_match:
            rec_text = rec_match.group(1).strip()
            if rec_text != "_No specific recommendations._":
                recommendations = re.findall(r'^\d+\. (.+)$', rec_text, re.MULTILINE)
                handover_data['recommendations'] = recommendations

        # Extract key findings (simplified - just messages)
        findings_match = re.search(
            r'## Key Findings\s*\n\n(.+?)(?=\n## |\n---|\Z)',
            content,
            re.DOTALL
        )
        if findings_match:
            findings_text = findings_match.group(1).strip()
            if findings_text != "_No findings reported._":
                # Parse: - **[SEVERITY] type:** message
                finding_pattern = r'- \*\*\[(\w+)\] (\w+):\*\* (.+?)(?=\n- |\n\n|\Z)'
                findings = []
                for match in re.finditer(finding_pattern, findings_text, re.DOTALL):
                    findings.append({
                        'severity': match.group(1).lower(),
                        'type': match.group(2),
                        'message': match.group(3).strip()
                    })
                handover_data['key_findings'] = findings

        # Validate we have required fields
        if not handover_data.get('phase_id'):
            logger.warning("Could not extract phase_id from markdown")
            return None

        return HandoverDocument.from_dict(handover_data)

    except Exception as e:
        logger.error(f"Failed to parse handover markdown: {e}")
        return None


# ============================================================================
# FILE OPERATIONS
# ============================================================================

def save_handover(task_workspace: str, handover: HandoverDocument) -> Dict[str, Any]:
    """
    Save a handover document as a markdown file.

    Creates the handovers directory if it doesn't exist.
    Formats the document as markdown and writes to disk.

    Args:
        task_workspace: Path to task workspace directory
        handover: HandoverDocument to save

    Returns:
        Dict with:
        - success: bool - True if save succeeded
        - path: str - Path where file was saved
        - token_count: int - Approximate token count of saved content
        - error: str - Error message if save failed (only if success=False)

    Example:
        >>> result = save_handover('/workspace/TASK-123', handover)
        >>> print(result)
        {'success': True, 'path': '/workspace/TASK-123/handovers/phase-abc123-handover.md', 'token_count': 450}
    """
    try:
        # Ensure handovers directory exists
        ensure_handovers_dir(task_workspace)

        # Get file path
        file_path = get_handover_path(task_workspace, handover.phase_id)

        # Format as markdown
        markdown_content = format_handover_markdown(handover)
        token_count = count_tokens(markdown_content)

        # Write to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(markdown_content)

        logger.info(
            f"Saved handover for phase {handover.phase_id} to {file_path} "
            f"({token_count} tokens)"
        )

        return {
            'success': True,
            'path': file_path,
            'token_count': token_count,
            'phase_id': handover.phase_id,
            'phase_name': handover.phase_name
        }

    except PermissionError as e:
        error_msg = f"Permission denied writing handover: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}

    except OSError as e:
        error_msg = f"OS error saving handover: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}

    except Exception as e:
        error_msg = f"Unexpected error saving handover: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}


def load_handover(task_workspace: str, phase_id: str) -> Optional[HandoverDocument]:
    """
    Load a handover document from file.

    Args:
        task_workspace: Path to task workspace directory
        phase_id: Phase ID to load handover for

    Returns:
        HandoverDocument if file exists and parses successfully, None otherwise

    Example:
        >>> handover = load_handover('/workspace/TASK-123', 'phase-abc123')
        >>> if handover:
        ...     print(handover.summary)
    """
    file_path = get_handover_path(task_workspace, phase_id)

    if not os.path.exists(file_path):
        logger.debug(f"Handover file not found: {file_path}")
        return None

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        handover = parse_handover_markdown(content)

        if handover:
            logger.debug(f"Loaded handover for phase {phase_id} from {file_path}")
        else:
            logger.warning(f"Failed to parse handover from {file_path}")

        return handover

    except PermissionError as e:
        logger.error(f"Permission denied reading handover {file_path}: {e}")
        return None

    except OSError as e:
        logger.error(f"OS error loading handover {file_path}: {e}")
        return None

    except Exception as e:
        logger.error(f"Unexpected error loading handover {file_path}: {e}")
        return None


def list_handovers(task_workspace: str) -> List[Dict[str, Any]]:
    """
    List all handover documents in a task workspace.

    Args:
        task_workspace: Path to task workspace directory

    Returns:
        List of dicts with handover metadata:
        [{phase_id, phase_name, created_at, path, token_count}, ...]
    """
    handovers_dir = os.path.join(task_workspace, 'handovers')

    if not os.path.exists(handovers_dir):
        return []

    handovers = []

    for filename in os.listdir(handovers_dir):
        if filename.endswith('-handover.md'):
            file_path = os.path.join(handovers_dir, filename)

            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                handover = parse_handover_markdown(content)

                if handover:
                    handovers.append({
                        'phase_id': handover.phase_id,
                        'phase_name': handover.phase_name,
                        'created_at': handover.created_at,
                        'path': file_path,
                        'token_count': count_tokens(content)
                    })
            except Exception as e:
                logger.warning(f"Failed to read handover {file_path}: {e}")

    # Sort by created_at
    handovers.sort(key=lambda h: h.get('created_at', ''))

    return handovers


def get_previous_handover(task_workspace: str, current_phase_id: str) -> Optional[HandoverDocument]:
    """
    Get the handover from the phase immediately before the current phase.

    This is used when starting a new phase to provide context from the previous phase.

    Args:
        task_workspace: Path to task workspace directory
        current_phase_id: ID of the current phase (to find the one before it)

    Returns:
        HandoverDocument from previous phase, or None if not found
    """
    handovers = list_handovers(task_workspace)

    if not handovers:
        return None

    # Find current phase in list and return the one before
    for i, h in enumerate(handovers):
        if h['phase_id'] == current_phase_id:
            if i > 0:
                prev_phase_id = handovers[i - 1]['phase_id']
                return load_handover(task_workspace, prev_phase_id)
            return None

    # If current phase not found, return the most recent handover
    if handovers:
        return load_handover(task_workspace, handovers[-1]['phase_id'])

    return None


# ============================================================================
# AUTOMATIC HANDOVER GENERATION FROM PHASE DATA
# ============================================================================

def collect_phase_findings(
    task_workspace: str,
    phase_id: str,
    registry: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Collect all findings from agents in a specific phase.

    Reads findings from {task_workspace}/findings/{agent_id}_findings.jsonl
    for all agents bound to the specified phase.

    Args:
        task_workspace: Path to task workspace directory
        phase_id: Phase ID to collect findings for
        registry: Registry dictionary containing agent data

    Returns:
        List of finding dictionaries sorted by timestamp (newest first)
    """
    findings = []
    findings_dir = os.path.join(task_workspace, "findings")

    if not os.path.exists(findings_dir):
        logger.debug(f"Findings directory does not exist: {findings_dir}")
        return findings

    # Get all agents bound to this phase
    phase_agents = [
        agent for agent in registry.get('agents', [])
        if agent.get('phase_id') == phase_id
    ]

    agent_ids = {agent.get('id') for agent in phase_agents}
    logger.debug(f"Collecting findings for {len(agent_ids)} agents in phase {phase_id}")

    # Read findings from each agent's findings file
    for filename in os.listdir(findings_dir):
        if not filename.endswith('_findings.jsonl'):
            continue

        # Extract agent_id from filename
        agent_id = filename.replace('_findings.jsonl', '')

        # Only include findings from agents in this phase
        if agent_id not in agent_ids:
            continue

        findings_file = os.path.join(findings_dir, filename)
        try:
            with open(findings_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        finding = json.loads(line)
                        # Ensure phase_id is tagged
                        finding['phase_id'] = phase_id
                        findings.append(finding)
                    except json.JSONDecodeError as e:
                        logger.warning(f"Invalid JSON in findings file {filename}: {e}")
                        continue
        except Exception as e:
            logger.warning(f"Error reading findings file {filename}: {e}")
            continue

    # Sort by timestamp (newest first)
    findings.sort(key=lambda x: x.get('timestamp', ''), reverse=True)

    logger.info(f"Collected {len(findings)} findings for phase {phase_id}")
    return findings


def calculate_phase_metrics(
    registry: Dict[str, Any],
    phase_id: str
) -> Dict[str, Any]:
    """
    Calculate metrics for a phase from registry data.

    Calculates:
    - agents_deployed: Number of agents spawned for this phase
    - completed: Number of agents that completed successfully
    - failed: Number of agents that failed/errored
    - duration_seconds: Time from phase start to now

    Args:
        registry: Registry dictionary containing phase and agent data
        phase_id: Phase ID to calculate metrics for

    Returns:
        Dictionary with phase metrics
    """
    metrics = {
        'agents_deployed': 0,
        'completed': 0,
        'failed': 0,
        'blocked': 0,
        'duration_seconds': 0,
        'findings_count': 0
    }

    # Find phase
    phase = None
    for p in registry.get('phases', []):
        if p.get('id') == phase_id:
            phase = p
            break

    if not phase:
        logger.warning(f"Phase {phase_id} not found in registry")
        return metrics

    # Calculate duration
    started_at = phase.get('started_at')
    if started_at:
        try:
            start_dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
            end_dt = datetime.now(start_dt.tzinfo) if start_dt.tzinfo else datetime.now()
            metrics['duration_seconds'] = int((end_dt - start_dt).total_seconds())
        except Exception as e:
            logger.warning(f"Error calculating duration: {e}")

    # Get agents for this phase
    terminal_statuses = {'completed', 'phase_completed'}
    failed_statuses = {'failed', 'error', 'terminated'}
    blocked_statuses = {'blocked'}

    for agent in registry.get('agents', []):
        if agent.get('phase_id') != phase_id:
            continue

        metrics['agents_deployed'] += 1
        status = agent.get('status', '')

        if status in terminal_statuses:
            metrics['completed'] += 1
        elif status in failed_statuses:
            metrics['failed'] += 1
        elif status in blocked_statuses:
            metrics['blocked'] += 1

    logger.debug(f"Phase {phase_id} metrics: {metrics}")
    return metrics


def summarize_findings(
    findings: List[Dict[str, Any]],
    max_chars: int = 1000
) -> str:
    """
    Create a concise summary from a list of findings.

    Prioritizes high/critical severity findings.
    Truncates to max_chars if needed.

    Args:
        findings: List of finding dictionaries
        max_chars: Maximum characters for summary

    Returns:
        Concise summary string
    """
    if not findings:
        return "No findings were reported during this phase."

    # Sort by severity (critical > high > medium > low)
    severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
    sorted_findings = sorted(
        findings,
        key=lambda f: (severity_order.get(f.get('severity', 'low'), 4), f.get('timestamp', ''))
    )

    # Group by finding type
    findings_by_type = {}
    for finding in sorted_findings:
        finding_type = finding.get('finding_type', 'other')
        if finding_type not in findings_by_type:
            findings_by_type[finding_type] = []
        findings_by_type[finding_type].append(finding)

    # Build summary
    summary_parts = []

    # Count by type
    type_counts = {ftype: len(flist) for ftype, flist in findings_by_type.items()}
    summary_parts.append(f"Total findings: {len(findings)}")
    summary_parts.append(f"By type: {', '.join(f'{k}={v}' for k, v in type_counts.items())}")

    # Include critical/high severity messages
    critical_high = [
        f for f in findings
        if f.get('severity') in ('critical', 'high')
    ]

    if critical_high:
        summary_parts.append("\nCritical/High priority items:")
        for finding in critical_high[:5]:  # Limit to top 5
            msg = finding.get('message', '')[:200]  # Truncate individual messages
            severity = finding.get('severity', 'unknown')
            summary_parts.append(f"  [{severity.upper()}] {msg}")

    # Include key solutions if any
    solutions = [f for f in findings if f.get('finding_type') == 'solution']
    if solutions:
        summary_parts.append("\nSolutions implemented:")
        for sol in solutions[:3]:  # Limit to top 3
            msg = sol.get('message', '')[:150]
            summary_parts.append(f"  - {msg}")

    summary = "\n".join(summary_parts)

    # Truncate if needed
    if len(summary) > max_chars:
        summary = summary[:max_chars - 20] + "\n[...truncated]"

    return summary


def extract_blockers(
    findings: List[Dict[str, Any]],
    failed_agents: List[Dict[str, Any]]
) -> List[str]:
    """
    Extract blockers from issues and failed agents.

    Identifies blockers from:
    1. Findings with type='issue' and severity='critical' or 'high'
    2. Failed agents and their error messages

    Args:
        findings: List of finding dictionaries
        failed_agents: List of agent dictionaries for failed agents

    Returns:
        List of blocker descriptions
    """
    blockers = []

    # Extract blockers from critical/high issues
    for finding in findings:
        if finding.get('finding_type') == 'issue':
            severity = finding.get('severity', 'low')
            if severity in ('critical', 'high'):
                message = finding.get('message', 'Unknown issue')
                agent_id = finding.get('agent_id', 'unknown')
                blockers.append(f"[{severity.upper()}] {message} (from {agent_id})")

    # Extract blockers from failed agents
    for agent in failed_agents:
        agent_id = agent.get('id', 'unknown')
        agent_type = agent.get('type', 'unknown')
        status = agent.get('status', 'failed')

        # Check for termination reason
        termination_reason = agent.get('termination_reason', '')
        error_message = agent.get('error', '')

        if termination_reason:
            blockers.append(f"Agent {agent_type} ({agent_id}) {status}: {termination_reason}")
        elif error_message:
            blockers.append(f"Agent {agent_type} ({agent_id}) {status}: {error_message}")
        else:
            blockers.append(f"Agent {agent_type} ({agent_id}) {status} without detailed error")

    # Deduplicate while preserving order
    seen = set()
    unique_blockers = []
    for blocker in blockers:
        if blocker not in seen:
            seen.add(blocker)
            unique_blockers.append(blocker)

    logger.debug(f"Extracted {len(unique_blockers)} blockers")
    return unique_blockers


def generate_recommendations(
    findings: List[Dict[str, Any]],
    phase_name: str
) -> List[str]:
    """
    Generate next-phase recommendations from findings.

    Creates recommendations based on:
    1. Insights discovered during the phase
    2. Solutions implemented that may need follow-up
    3. Issues that weren't fully resolved
    4. General recommendations based on findings

    Args:
        findings: List of finding dictionaries
        phase_name: Name of the completed phase

    Returns:
        List of recommendation strings
    """
    recommendations = []

    # Extract explicit recommendations from findings
    for finding in findings:
        if finding.get('finding_type') == 'recommendation':
            message = finding.get('message', '')
            if message:
                recommendations.append(message)

    # Generate recommendations from insights
    insights = [f for f in findings if f.get('finding_type') == 'insight']
    if insights:
        recommendations.append(
            f"Review {len(insights)} insights from {phase_name} phase before proceeding"
        )

    # Check for unresolved issues
    issues = [f for f in findings if f.get('finding_type') == 'issue']
    solutions = [f for f in findings if f.get('finding_type') == 'solution']

    if len(issues) > len(solutions):
        unresolved_count = len(issues) - len(solutions)
        recommendations.append(
            f"Address {unresolved_count} potentially unresolved issues from {phase_name}"
        )

    # Check for critical items that need attention
    critical_items = [
        f for f in findings
        if f.get('severity') == 'critical'
    ]
    if critical_items:
        recommendations.append(
            f"PRIORITY: Verify {len(critical_items)} critical items have been fully addressed"
        )

    # Add phase-specific recommendations based on name patterns
    phase_lower = phase_name.lower()
    if 'investigation' in phase_lower or 'analysis' in phase_lower:
        recommendations.append(
            "Ensure implementation addresses all issues identified during investigation"
        )
    elif 'implementation' in phase_lower or 'build' in phase_lower:
        recommendations.append(
            "Verify all implementations are tested before marking phase complete"
        )
    elif 'test' in phase_lower:
        recommendations.append(
            "Address any test failures before deployment"
        )

    # Deduplicate
    seen = set()
    unique_recommendations = []
    for rec in recommendations:
        if rec not in seen:
            seen.add(rec)
            unique_recommendations.append(rec)

    logger.debug(f"Generated {len(unique_recommendations)} recommendations")
    return unique_recommendations


def auto_generate_handover(
    task_workspace: str,
    phase_id: str,
    phase_name: str,
    registry: Dict[str, Any]
) -> HandoverDocument:
    """
    Auto-generate a handover document from phase data.

    Collects all findings, calculates metrics, summarizes accomplishments,
    identifies blockers, and generates recommendations automatically.

    This is the main entry point for automatic handover generation.

    Args:
        task_workspace: Path to task workspace directory
        phase_id: ID of the phase to generate handover for
        phase_name: Human-readable name of the phase
        registry: Registry dictionary containing phase and agent data

    Returns:
        HandoverDocument with all fields populated from phase data
    """
    logger.info(f"Auto-generating handover for phase {phase_id} ({phase_name})")

    # Collect all findings for this phase
    findings = collect_phase_findings(task_workspace, phase_id, registry)

    # Calculate phase metrics
    metrics = calculate_phase_metrics(registry, phase_id)
    metrics['findings_count'] = len(findings)

    # Get failed agents for blocker extraction
    failed_statuses = {'failed', 'error', 'terminated'}
    failed_agents = [
        agent for agent in registry.get('agents', [])
        if agent.get('phase_id') == phase_id and agent.get('status') in failed_statuses
    ]

    # Generate summary from findings
    summary = summarize_findings(findings, max_chars=1500)

    # Extract key findings (convert to expected format)
    key_findings = []
    for finding in findings:
        if finding.get('severity') in ('critical', 'high'):
            key_findings.append({
                'type': finding.get('finding_type', 'unknown'),
                'severity': finding.get('severity', 'medium'),
                'message': finding.get('message', ''),
                'data': finding.get('data', {})
            })
            if len(key_findings) >= 10:  # Limit to 10 key findings
                break

    # Extract blockers
    blockers = extract_blockers(findings, failed_agents)

    # Generate recommendations
    recommendations = generate_recommendations(findings, phase_name)

    # Extract artifacts from findings data (files created/modified)
    artifacts = []
    for finding in findings:
        data = finding.get('data', {})
        if isinstance(data, dict):
            # Look for file references in data
            for key in ['file', 'path', 'file_path', 'created_file', 'modified_file']:
                if key in data:
                    file_path = data[key]
                    if isinstance(file_path, str):
                        artifacts.append({
                            'path': file_path,
                            'description': f"From {finding.get('finding_type', 'finding')}"
                        })
                        break

    # Create handover document
    handover = HandoverDocument(
        phase_id=phase_id,
        phase_name=phase_name,
        summary=summary,
        key_findings=key_findings,
        blockers=blockers,
        recommendations=recommendations,
        artifacts=artifacts[:10],  # Limit artifacts
        metrics=metrics
    )

    # Check token count and truncate if needed
    markdown_content = format_handover_markdown(handover)
    token_count = count_tokens(markdown_content)

    if token_count > HANDOVER_MAX_TOKENS:
        logger.warning(
            f"Handover exceeds token limit ({token_count} > {HANDOVER_MAX_TOKENS}). "
            f"Truncating content."
        )
        # Truncate summary
        max_summary_chars = 800
        if len(handover.summary) > max_summary_chars:
            handover.summary = handover.summary[:max_summary_chars] + "\n[...truncated]"

        # Limit key findings
        if len(handover.key_findings) > 5:
            handover.key_findings = handover.key_findings[:5]

        # Limit recommendations
        if len(handover.recommendations) > 5:
            handover.recommendations = handover.recommendations[:5]

        # Limit blockers
        if len(handover.blockers) > 5:
            handover.blockers = handover.blockers[:5]

    logger.info(
        f"Generated handover for phase {phase_id}: "
        f"{len(key_findings)} findings, {len(blockers)} blockers, "
        f"{len(recommendations)} recommendations, ~{count_tokens(format_handover_markdown(handover))} tokens"
    )

    return handover


# ============================================================================
# MCP TOOL WRAPPERS
# ============================================================================

def submit_phase_handover(
    task_id: str,
    phase_id: str,
    summary: str,
    key_findings: List[Dict[str, Any]],
    blockers: List[str],
    recommendations: List[str],
    artifacts: Optional[List[Dict[str, str]]] = None,
    # Dependency injection for modularity
    find_task_workspace=None,
    read_registry_with_lock=None,
) -> Dict[str, Any]:
    """
    Submit explicit handover for a phase.

    Called by orchestrator before advancing phase. Creates a structured
    handover document capturing the phase's work for the next phase.

    Args:
        task_id: Task ID
        phase_id: Phase ID being completed
        summary: Brief summary of work done
        key_findings: List of important findings (dicts with type, severity, message)
        blockers: List of blockers encountered
        recommendations: List of recommendations for next phase
        artifacts: Optional list of artifacts (dicts with path, description)
        find_task_workspace: Dependency injection - function to find workspace
        read_registry_with_lock: Dependency injection - function to read registry

    Returns:
        Dict with:
        {
            "success": bool,
            "handover_path": str,  # Path to saved handover
            "token_count": int,
            "warning": str or None  # Warning if over limit
        }
    """
    logger.info(f"Submitting phase handover for task {task_id}, phase {phase_id}")

    # Find workspace
    if find_task_workspace is None:
        return {
            "success": False,
            "error": "find_task_workspace function not provided",
            "handover_path": None,
            "token_count": 0
        }

    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found",
            "handover_path": None,
            "token_count": 0
        }

    # Get phase name from registry if available
    phase_name = "Unknown Phase"
    if read_registry_with_lock:
        try:
            registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")
            if os.path.exists(registry_path):
                registry = read_registry_with_lock(registry_path)
                phases = registry.get('phases', [])
                for phase in phases:
                    if phase.get('id') == phase_id:
                        phase_name = phase.get('name', 'Unknown Phase')
                        break
        except Exception as e:
            logger.warning(f"Could not get phase name from registry: {e}")

    # Create handover document
    handover = HandoverDocument(
        phase_id=phase_id,
        phase_name=phase_name,
        summary=summary,
        key_findings=key_findings,
        blockers=blockers,
        recommendations=recommendations,
        artifacts=artifacts or []
    )

    # Validate before saving
    valid, errors = validate_handover(handover)
    if not valid:
        return {
            "success": False,
            "error": f"Handover validation failed: {', '.join(errors)}",
            "handover_path": None,
            "token_count": 0
        }

    # Save handover
    save_result = save_handover(workspace, handover)

    if not save_result.get('success'):
        return {
            "success": False,
            "error": save_result.get('error', 'Failed to save handover'),
            "handover_path": None,
            "token_count": 0
        }

    # Build response
    response = {
        "success": True,
        "handover_path": save_result['path'],
        "token_count": save_result['token_count'],
        "warning": None
    }

    # Add warning if near token limit
    if save_result['token_count'] > HANDOVER_MAX_TOKENS:
        response['warning'] = f"Handover exceeds {HANDOVER_MAX_TOKENS} token limit, content may be truncated"
    elif save_result['token_count'] > HANDOVER_MAX_TOKENS * 0.8:
        response['warning'] = f"Handover is at {save_result['token_count']}/{HANDOVER_MAX_TOKENS} tokens (near limit)"

    logger.info(f"Phase handover submitted: {save_result['path']} ({save_result['token_count']} tokens)")

    return response


def get_phase_handover(
    task_id: str,
    phase_id: str,
    # Dependency injection
    find_task_workspace=None,
) -> Dict[str, Any]:
    """
    Get handover document for a phase.

    Args:
        task_id: Task ID
        phase_id: Phase ID to get handover for
        find_task_workspace: Dependency injection - function to find workspace

    Returns:
        Dict with:
        {
            "success": bool,
            "handover": HandoverDocument dict or None,
            "path": str or None
        }
    """
    logger.debug(f"Getting phase handover for task {task_id}, phase {phase_id}")

    if find_task_workspace is None:
        return {
            "success": False,
            "error": "find_task_workspace function not provided",
            "handover": None,
            "path": None
        }

    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found",
            "handover": None,
            "path": None
        }

    # Load handover
    handover = load_handover(workspace, phase_id)

    if handover is None:
        return {
            "success": True,  # Not an error, just no handover exists
            "handover": None,
            "path": None,
            "message": f"No handover found for phase {phase_id}"
        }

    return {
        "success": True,
        "handover": handover.to_dict(),
        "path": get_handover_path(workspace, phase_id)
    }


def get_handover_context(
    task_id: str,
    current_phase_id: str,
    # Dependency injection
    find_task_workspace=None,
    read_registry_with_lock=None,
) -> str:
    """
    Get previous phase handover formatted for agent context.

    This function finds the phase immediately before current_phase_id
    and returns its handover document as a markdown string ready to
    include in agent prompts.

    Args:
        task_id: Task ID
        current_phase_id: Current phase ID (will get handover from previous phase)
        find_task_workspace: Dependency injection
        read_registry_with_lock: Dependency injection

    Returns:
        Markdown string ready to include in agent prompt.
        Empty string if no previous handover exists.
    """
    logger.debug(f"Getting handover context for task {task_id}, current phase {current_phase_id}")

    if find_task_workspace is None:
        logger.warning("find_task_workspace not provided to get_handover_context")
        return ""

    workspace = find_task_workspace(task_id)
    if not workspace:
        logger.warning(f"Task {task_id} not found")
        return ""

    # Find previous phase from registry
    previous_phase_id = None

    if read_registry_with_lock:
        try:
            registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")
            if os.path.exists(registry_path):
                registry = read_registry_with_lock(registry_path)
                phases = registry.get('phases', [])

                # Sort phases by order
                sorted_phases = sorted(phases, key=lambda p: p.get('order', 0))

                # Find current phase and get the one before it
                for i, phase in enumerate(sorted_phases):
                    if phase.get('id') == current_phase_id and i > 0:
                        previous_phase_id = sorted_phases[i - 1].get('id')
                        break
        except Exception as e:
            logger.warning(f"Could not determine previous phase: {e}")

    if not previous_phase_id:
        # Try to get previous handover without registry (fallback)
        handover = get_previous_handover(workspace, current_phase_id)
        if handover:
            return _format_handover_for_context(handover)
        logger.debug(f"No previous phase found for {current_phase_id}")
        return ""

    # Load previous phase handover
    handover = load_handover(workspace, previous_phase_id)

    if handover is None:
        logger.debug(f"No handover found for previous phase {previous_phase_id}")
        return ""

    return _format_handover_for_context(handover)


def _format_handover_for_context(handover: HandoverDocument) -> str:
    """
    Format a handover document for inclusion in agent context/prompts.

    Args:
        handover: HandoverDocument to format

    Returns:
        Formatted markdown string with context header
    """
    context_header = """
================================================================================
PREVIOUS PHASE HANDOVER CONTEXT
================================================================================

The following is a summary from the previous phase. Use this context to
understand what has been done and what needs attention.

"""
    markdown = format_handover_markdown(handover)

    return context_header + markdown


def validate_handover(handover: HandoverDocument) -> tuple:
    """
    Validate handover document.

    Checks:
    - Has required fields (phase_id, phase_name, summary)
    - Summary is not empty
    - Within token limit
    - Key findings have required structure

    Args:
        handover: HandoverDocument to validate

    Returns:
        Tuple of (valid: bool, errors: List[str])
    """
    errors = []

    # Check required fields
    if not handover.phase_id:
        errors.append("phase_id is required")

    if not handover.phase_name:
        errors.append("phase_name is required")

    if not handover.summary:
        errors.append("summary is required and cannot be empty")
    elif len(handover.summary.strip()) < 10:
        errors.append("summary is too short (minimum 10 characters)")

    # Check token limit
    markdown = format_handover_markdown(handover)
    token_count = count_tokens(markdown)

    if token_count > HANDOVER_MAX_TOKENS:
        errors.append(f"Handover exceeds token limit ({token_count} > {HANDOVER_MAX_TOKENS})")

    # Validate key_findings structure
    for i, finding in enumerate(handover.key_findings):
        if not isinstance(finding, dict):
            errors.append(f"key_findings[{i}] must be a dict")
        elif 'message' not in finding:
            errors.append(f"key_findings[{i}] missing 'message' field")

    # Validate artifacts structure if provided
    if handover.artifacts:
        for i, artifact in enumerate(handover.artifacts):
            if not isinstance(artifact, dict):
                errors.append(f"artifacts[{i}] must be a dict")
            elif 'path' not in artifact:
                errors.append(f"artifacts[{i}] missing 'path' field")

    valid = len(errors) == 0

    if not valid:
        logger.warning(f"Handover validation failed: {errors}")

    return valid, errors


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Constants
    'HANDOVER_MAX_TOKENS',
    'HANDOVER_MAX_CHARS',
    'CHARS_PER_TOKEN',
    # Schema
    'HandoverDocument',
    'FindingDict',
    'ArtifactDict',
    'MetricsDict',
    # Token utilities
    'count_tokens',
    'truncate_to_tokens',
    'truncate_list_to_tokens',
    # Path utilities
    'get_handover_path',
    'ensure_handovers_dir',
    # Markdown formatting
    'format_handover_markdown',
    'parse_handover_markdown',
    # File operations
    'save_handover',
    'load_handover',
    'list_handovers',
    'get_previous_handover',
    # Auto-generation functions
    'auto_generate_handover',
    'collect_phase_findings',
    'calculate_phase_metrics',
    'summarize_findings',
    'extract_blockers',
    'generate_recommendations',
    # MCP Tool Wrappers
    'submit_phase_handover',
    'get_phase_handover',
    'get_handover_context',
    'validate_handover',
]
