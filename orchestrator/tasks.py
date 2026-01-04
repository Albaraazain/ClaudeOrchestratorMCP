"""
Task management functions for the orchestrator.

Handles task creation, validation, and complexity calculation.
"""

import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
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
]


# ============================================================================
# PHASE STATUS CONSTANTS (8-state machine per MIT-002)
# ============================================================================

PHASE_STATUSES = frozenset({
    'PENDING',           # Phase not yet started
    'ACTIVE',            # Phase currently in progress
    'AWAITING_REVIEW',   # Phase work complete, awaiting review
    'UNDER_REVIEW',      # Phase actively being reviewed
    'APPROVED',          # Phase passed review
    'REJECTED',          # Phase failed review
    'REVISING',          # Phase being revised after rejection
    'ESCALATED',         # Phase escalated for higher-level review
})


class PhaseValidationError(ValueError):
    """Raised when phase validation fails"""

    def __init__(self, reason: str, phase_data: Any = None):
        self.reason = reason
        self.phase_data = phase_data
        super().__init__(f"Phase validation failed: {reason}")


class TaskValidationWarning:
    """Non-fatal validation issue"""

    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, str]:
        return {
            'field': self.field,
            'message': self.message,
            'timestamp': self.timestamp
        }


def create_default_phase(task_description: str) -> Dict[str, Any]:
    """
    Create a default phase from task description.

    When no phases are explicitly provided, this creates a single phase
    derived from the task description. This ensures every task has at least
    one phase (mandatory per MIT-002).

    Args:
        task_description: The task description to derive phase name from

    Returns:
        Phase dict with:
        - id: "phase-{uuid}"
        - name: Derived from task description (first 50 chars, cleaned)
        - order: 1
        - status: "PENDING"
        - created_at: ISO timestamp
    """
    # Clean and truncate description for phase name
    phase_name = task_description.strip()
    if len(phase_name) > 50:
        # Truncate at word boundary if possible
        truncated = phase_name[:50]
        last_space = truncated.rfind(' ')
        if last_space > 30:  # Only use word boundary if we have reasonable length
            phase_name = truncated[:last_space] + "..."
        else:
            phase_name = truncated + "..."

    return {
        'id': f"phase-{uuid.uuid4().hex[:12]}",
        'name': phase_name,
        'order': 1,
        'status': 'PENDING',
        'created_at': datetime.now().isoformat(),
    }


def validate_phases(phases: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    Validate a list of phases for a task.

    Checks:
    - At least 1 phase exists (mandatory)
    - Each phase has required fields (id, name, order, status)
    - Orders are sequential starting from 1
    - All statuses are valid (8-state enum)
    - No duplicate phase IDs
    - No duplicate orders

    Args:
        phases: List of phase dictionaries to validate

    Returns:
        Tuple of (is_valid, list_of_error_messages)
    """
    errors: List[str] = []

    # Check mandatory minimum
    if not phases or len(phases) == 0:
        errors.append("At least 1 phase is required (phases cannot be empty)")
        return False, errors

    required_fields = {'id', 'name', 'order', 'status'}
    seen_ids: set = set()
    seen_orders: set = set()
    orders: List[int] = []

    for i, phase in enumerate(phases):
        phase_idx = i + 1

        # Check type
        if not isinstance(phase, dict):
            errors.append(f"Phase {phase_idx}: Must be a dictionary, got {type(phase).__name__}")
            continue

        # Check required fields
        missing_fields = required_fields - set(phase.keys())
        if missing_fields:
            errors.append(f"Phase {phase_idx}: Missing required fields: {', '.join(sorted(missing_fields))}")
            continue  # Skip further validation if required fields missing

        # Validate id
        phase_id = phase.get('id')
        if not isinstance(phase_id, str) or not phase_id.strip():
            errors.append(f"Phase {phase_idx}: 'id' must be a non-empty string")
        elif phase_id in seen_ids:
            errors.append(f"Phase {phase_idx}: Duplicate phase id '{phase_id}'")
        else:
            seen_ids.add(phase_id)

        # Validate name
        phase_name = phase.get('name')
        if not isinstance(phase_name, str) or not phase_name.strip():
            errors.append(f"Phase {phase_idx}: 'name' must be a non-empty string")
        elif len(phase_name) > 100:
            errors.append(f"Phase {phase_idx}: 'name' exceeds 100 character limit ({len(phase_name)} chars)")

        # Validate order
        order = phase.get('order')
        if not isinstance(order, int):
            errors.append(f"Phase {phase_idx}: 'order' must be an integer, got {type(order).__name__}")
        elif order < 1:
            errors.append(f"Phase {phase_idx}: 'order' must be >= 1, got {order}")
        elif order in seen_orders:
            errors.append(f"Phase {phase_idx}: Duplicate order value {order}")
        else:
            seen_orders.add(order)
            orders.append(order)

        # Validate status
        status = phase.get('status')
        if not isinstance(status, str):
            errors.append(f"Phase {phase_idx}: 'status' must be a string")
        elif status not in PHASE_STATUSES:
            errors.append(
                f"Phase {phase_idx}: Invalid status '{status}'. "
                f"Must be one of: {', '.join(sorted(PHASE_STATUSES))}"
            )

    # Check sequential ordering (1, 2, 3, ...)
    if orders:
        orders_sorted = sorted(orders)
        expected_orders = list(range(1, len(orders) + 1))
        if orders_sorted != expected_orders:
            errors.append(
                f"Phase orders must be sequential starting from 1. "
                f"Got: {orders_sorted}, expected: {expected_orders}"
            )

    return len(errors) == 0, errors


def ensure_task_has_phases(
    phases: Optional[List[Dict[str, Any]]],
    task_description: str
) -> Tuple[List[Dict[str, Any]], List[TaskValidationWarning]]:
    """
    Ensure task has valid phases, creating default if necessary.

    This is the main entry point for phase handling in task creation.
    It either validates provided phases or creates a default phase
    from the task description.

    Args:
        phases: Optional list of phases (can be None, empty, or populated)
        task_description: Task description (used for default phase if needed)

    Returns:
        Tuple of (validated_phases, warnings)

    Raises:
        PhaseValidationError: If provided phases fail validation
    """
    warnings: List[TaskValidationWarning] = []

    # If no phases provided, create default
    if phases is None or len(phases) == 0:
        default_phase = create_default_phase(task_description)
        warnings.append(TaskValidationWarning(
            "phases",
            f"No phases provided - created default phase '{default_phase['name']}'"
        ))
        return [default_phase], warnings

    # Validate provided phases
    is_valid, errors = validate_phases(phases)
    if not is_valid:
        raise PhaseValidationError(
            f"Phase validation failed with {len(errors)} error(s): {'; '.join(errors)}",
            phase_data=phases
        )

    # Add timestamps to phases that don't have them
    validated_phases = []
    for phase in phases:
        phase_copy = dict(phase)
        if 'created_at' not in phase_copy:
            phase_copy['created_at'] = datetime.now().isoformat()
        validated_phases.append(phase_copy)

    return validated_phases, warnings


class TaskValidationError(ValueError):
    """Raised when task parameters fail critical validation"""

    def __init__(self, field: str, reason: str, value: Any):
        self.field = field
        self.reason = reason
        self.value = value
        super().__init__(f"Validation failed for '{field}': {reason}")


def calculate_task_complexity(description: str) -> int:
    """Calculate task complexity to guide orchestration depth"""
    complexity_keywords = {
        'comprehensive': 5, 'complete': 4, 'full': 4, 'entire': 4,
        'system': 3, 'platform': 3, 'application': 3, 'website': 2,
        'frontend': 2, 'backend': 2, 'database': 2, 'api': 2,
        'testing': 2, 'security': 2, 'performance': 2, 'optimization': 2,
        'deployment': 2, 'ci/cd': 2, 'monitoring': 2, 'analytics': 2,
        'authentication': 2, 'authorization': 2, 'integration': 2
    }

    score = 1  # Base complexity
    description_lower = description.lower()

    for keyword, points in complexity_keywords.items():
        if keyword in description_lower:
            score += points

    # Additional factors
    if len(description) > 200:
        score += 2
    if 'layers' in description_lower or 'multi' in description_lower:
        score += 3
    if 'specialist' in description_lower or 'expert' in description_lower:
        score += 2

    return min(score, 20)  # Cap at 20


def extract_text_from_message_content(content: Any) -> str:
    """
    Extract only TEXT content from Claude API message content.

    Filters OUT:
    - tool_use blocks (Read, Write, Edit, Grep, Bash, etc.)
    - tool_result blocks (file contents, command outputs)
    - thinking blocks

    Keeps ONLY:
    - User's actual text (questions, requests)
    - Assistant's reasoning text (explanations, plans)

    Args:
        content: Message content - can be string, list of content blocks, or dict

    Returns:
        Extracted text content as string
    """
    if content is None:
        return ""

    # Simple string content
    if isinstance(content, str):
        return content

    # List of content blocks (Claude API format)
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                block_type = block.get('type', '')

                # Keep text blocks
                if block_type == 'text':
                    text_parts.append(block.get('text', ''))

                # Skip tool_use blocks entirely (Read, Write, Edit, Grep, Bash, etc.)
                elif block_type == 'tool_use':
                    continue

                # Skip tool_result blocks entirely (file contents, outputs)
                elif block_type == 'tool_result':
                    continue

                # Skip thinking blocks
                elif block_type == 'thinking':
                    continue

            elif isinstance(block, str):
                text_parts.append(block)

        return '\n'.join(text_parts).strip()

    # Dict with content key (nested)
    if isinstance(content, dict):
        if 'content' in content:
            return extract_text_from_message_content(content['content'])
        if 'text' in content:
            return content['text']

    # Fallback: convert to string
    return str(content)


def truncate_conversation_history(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Filter and truncate conversation history for agent context.

    FILTERS OUT (completely removes):
    - tool_use blocks (Read, Write, Edit, Grep, Bash tool calls)
    - tool_result blocks (file contents, command outputs, MCP responses)
    - thinking blocks
    - Empty messages after filtering

    KEEPS (what matters for agent context):
    - User text (actual questions, requests, clarifications)
    - Assistant text (reasoning, explanations, plans)

    Truncation limits:
    - User messages: 2KB max (the actual user intent)
    - Assistant messages: 500 chars max (key reasoning)

    Args:
        messages: List of message dicts (may have nested content blocks)

    Returns:
        Dict with filtered messages and metadata
    """
    USER_MAX_CHARS = 2000    # User intent - keep concise
    ASSISTANT_MAX_CHARS = 500  # Assistant reasoning - moderate

    filtered_messages = []
    original_count = len(messages)
    filtered_out_count = 0
    truncated_count = 0

    for msg in messages:
        role = msg.get('role', 'unknown')
        raw_content = msg.get('content', '')

        # Extract only TEXT content (filters out tool blocks)
        text_content = extract_text_from_message_content(raw_content)

        # Skip empty messages (likely was all tool calls)
        if not text_content or not text_content.strip():
            filtered_out_count += 1
            continue

        original_length = len(text_content)
        truncated = False

        # Apply role-specific truncation
        if role == 'user':
            if original_length > USER_MAX_CHARS:
                text_content = text_content[:USER_MAX_CHARS] + f" ... [{original_length - USER_MAX_CHARS} more]"
                truncated = True
                truncated_count += 1
        else:  # assistant or orchestrator
            if original_length > ASSISTANT_MAX_CHARS:
                text_content = text_content[:ASSISTANT_MAX_CHARS] + " ... (truncated)"
                truncated = True
                truncated_count += 1

        filtered_messages.append({
            'role': role,
            'content': text_content,
            'timestamp': msg.get('timestamp', datetime.now().isoformat()),
            'truncated': truncated,
            'original_length': original_length
        })

    # Calculate metadata
    timestamps = [msg['timestamp'] for msg in filtered_messages] if filtered_messages else []

    return {
        'messages': filtered_messages,
        'total_messages': len(filtered_messages),
        'original_count': original_count,
        'filtered_out_count': filtered_out_count,
        'truncated_count': truncated_count,
        'metadata': {
            'collection_time': datetime.now().isoformat(),
            'oldest_message': min(timestamps) if timestamps else None,
            'newest_message': max(timestamps) if timestamps else None,
            'note': 'Tool calls and results filtered out for agent context'
        }
    }


def validate_task_parameters(
    description: str,
    priority: str = "P2",
    phases: Optional[List[Dict[str, Any]]] = None,
    background_context: Optional[str] = None,
    expected_deliverables: Optional[List[str]] = None,
    success_criteria: Optional[List[str]] = None,
    constraints: Optional[List[str]] = None,
    relevant_files: Optional[List[str]] = None,
    related_documentation: Optional[List[str]] = None,
    client_cwd: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> Tuple[Dict[str, Any], List[TaskValidationWarning]]:
    """
    Validate all task parameters and return cleaned data + warnings.

    IMPORTANT: Tasks MUST have at least 1 phase. If no phases are provided,
    a default phase is created from the task description (MIT-002 requirement).

    Args:
        description: Task description (required)
        priority: Priority level (P0-P3)
        phases: List of phase dicts (at least 1 required, created from description if not provided)
        background_context: Multi-line context about the problem
        expected_deliverables: List of concrete outputs required
        success_criteria: List of measurable completion criteria
        conversation_history: Optional conversation context (list of message dicts)
        constraints: List of boundaries agents must respect
        relevant_files: List of file paths to examine
        related_documentation: List of docs to reference
        client_cwd: Client working directory for path resolution

    Returns:
        Tuple of (validated_data, warnings)

    Raises:
        TaskValidationError: On critical validation failures
        PhaseValidationError: On phase validation failures
    """
    warnings: List[TaskValidationWarning] = []
    validated: Dict[str, Any] = {}

    # Validate description
    description = description.strip()
    if len(description) < 10:
        raise TaskValidationError("description", "Must be at least 10 characters", description)
    if len(description) > 500:
        raise TaskValidationError("description", "Must be at most 500 characters", description)

    # Check for overly generic descriptions
    generic_patterns = [r'^fix bug$', r'^do task$', r'^implement feature$', r'^update code$']
    if any(re.match(pattern, description.lower()) for pattern in generic_patterns):
        warnings.append(TaskValidationWarning("description", f"Description is too generic: '{description}'. Consider being more specific."))

    validated['description'] = description

    # Validate priority
    priority = priority.upper()
    if priority not in ["P0", "P1", "P2", "P3"]:
        raise TaskValidationError("priority", "Must be P0, P1, P2, or P3", priority)
    validated['priority'] = priority

    # Validate and ensure phases (MANDATORY - at least 1 phase required per MIT-002)
    try:
        validated_phases, phase_warnings = ensure_task_has_phases(phases, description)
        validated['phases'] = validated_phases
        warnings.extend(phase_warnings)
    except PhaseValidationError as e:
        # Re-raise as TaskValidationError for consistent handling
        raise TaskValidationError("phases", e.reason, e.phase_data)

    # Validate background_context
    if background_context is not None:
        background_context = background_context.strip()
        if len(background_context) < 50:
            warnings.append(TaskValidationWarning("background_context", f"Background context is very short ({len(background_context)} chars). Consider adding more detail."))
        if len(background_context) > 5000:
            raise TaskValidationError("background_context", "Must be at most 5000 characters", f"{background_context[:100]}...")
        validated['background_context'] = background_context

    # Validate expected_deliverables
    if expected_deliverables is not None:
        deliverables = [d.strip() for d in expected_deliverables if d and d.strip()]
        deliverables = list(dict.fromkeys(deliverables))
        if len(deliverables) == 0:
            warnings.append(TaskValidationWarning("expected_deliverables", "List is empty after filtering. Consider omitting this parameter."))
        if len(deliverables) > 20:
            raise TaskValidationError("expected_deliverables", f"Maximum 20 items allowed, got {len(deliverables)}", deliverables)
        for i, item in enumerate(deliverables):
            if len(item) < 10:
                warnings.append(TaskValidationWarning(f"expected_deliverables[{i}]", f"Deliverable is very short: '{item}'. Consider being more specific."))
            if len(item) > 200:
                raise TaskValidationError(f"expected_deliverables[{i}]", "Each item must be at most 200 characters", item)
        validated['expected_deliverables'] = {'items': deliverables, 'validation_added': datetime.now().isoformat()}

    # Validate success_criteria
    if success_criteria is not None:
        criteria = [c.strip() for c in success_criteria if c and c.strip()]
        criteria = list(dict.fromkeys(criteria))
        if len(criteria) == 0:
            warnings.append(TaskValidationWarning("success_criteria", "List is empty after filtering. Consider omitting this parameter."))
        if len(criteria) > 15:
            raise TaskValidationError("success_criteria", f"Maximum 15 items allowed, got {len(criteria)}", criteria)
        measurable_keywords = ['pass', 'complete', 'under', 'above', 'below', 'equal', 'verify', 'test', 'validate', 'all', 'no', 'zero', 'every', 'none', 'within', 'less than', 'greater than', 'at least', 'at most']
        for i, item in enumerate(criteria):
            if len(item) < 10:
                warnings.append(TaskValidationWarning(f"success_criteria[{i}]", f"Criterion is very short: '{item}'. Consider being more specific."))
            if len(item) > 200:
                raise TaskValidationError(f"success_criteria[{i}]", "Each item must be at most 200 characters", item)
            if not any(keyword in item.lower() for keyword in measurable_keywords):
                warnings.append(TaskValidationWarning(f"success_criteria[{i}]", f"Criterion may not be measurable: '{item}'. Consider adding quantifiable metrics."))
        validated['success_criteria'] = {'criteria': criteria, 'all_required': True}

    # Validate constraints
    if constraints is not None:
        constraint_list = [c.strip() for c in constraints if c and c.strip()]
        constraint_list = list(dict.fromkeys(constraint_list))
        if len(constraint_list) == 0:
            warnings.append(TaskValidationWarning("constraints", "List is empty after filtering. Consider omitting this parameter."))
        if len(constraint_list) > 15:
            raise TaskValidationError("constraints", f"Maximum 15 items allowed, got {len(constraint_list)}", constraint_list)
        constraint_keywords = ['do not', 'must not', 'never', 'cannot', 'should not', 'must use', 'required to', 'only use', 'must maintain']
        for i, item in enumerate(constraint_list):
            if len(item) < 10:
                warnings.append(TaskValidationWarning(f"constraints[{i}]", f"Constraint is very short: '{item}'. Consider being more specific."))
            if len(item) > 200:
                raise TaskValidationError(f"constraints[{i}]", "Each item must be at most 200 characters", item)
            if not any(keyword in item.lower() for keyword in constraint_keywords):
                warnings.append(TaskValidationWarning(f"constraints[{i}]", f"Constraint should start with imperative: '{item}'"))
        validated['constraints'] = {'rules': constraint_list, 'enforcement_level': 'strict'}

    # Validate relevant_files
    if relevant_files is not None:
        file_list = [f.strip() for f in relevant_files if f and f.strip()]
        file_list = list(dict.fromkeys(file_list))
        if len(file_list) == 0:
            warnings.append(TaskValidationWarning("relevant_files", "List is empty after filtering. Consider omitting this parameter."))
        if len(file_list) > 50:
            raise TaskValidationError("relevant_files", f"Maximum 50 files allowed, got {len(file_list)}", file_list)
        validated_files = []
        for filepath in file_list:
            original_path = filepath
            if not os.path.isabs(filepath):
                if client_cwd:
                    filepath = os.path.join(client_cwd, filepath)
                else:
                    filepath = os.path.abspath(filepath)
            try:
                filepath = os.path.realpath(filepath)
            except Exception as e:
                warnings.append(TaskValidationWarning("relevant_files", f"Could not resolve path '{original_path}': {e}"))
                continue
            if not os.path.exists(filepath):
                warnings.append(TaskValidationWarning("relevant_files", f"File not found: '{filepath}' - agents will skip if unavailable"))
            elif not os.path.isfile(filepath):
                warnings.append(TaskValidationWarning("relevant_files", f"Path is not a file: '{filepath}' - may be a directory"))
            validated_files.append(filepath)
        validated['relevant_files'] = validated_files

    # Validate related_documentation
    if related_documentation is not None:
        doc_list = [d.strip() for d in related_documentation if d and d.strip()]
        doc_list = list(dict.fromkeys(doc_list))
        if len(doc_list) == 0:
            warnings.append(TaskValidationWarning("related_documentation", "List is empty after filtering. Consider omitting this parameter."))
        if len(doc_list) > 20:
            raise TaskValidationError("related_documentation", f"Maximum 20 items allowed, got {len(doc_list)}", doc_list)
        validated_docs = []
        for item in doc_list:
            if item.startswith('http://') or item.startswith('https://'):
                if ' ' in item:
                    warnings.append(TaskValidationWarning("related_documentation", f"URL contains spaces (may be invalid): '{item}'"))
                if item.endswith('.'):
                    warnings.append(TaskValidationWarning("related_documentation", f"URL ends with period (may be typo): '{item}'"))
                validated_docs.append(item)
            else:
                original_path = item
                if not os.path.isabs(item):
                    if client_cwd:
                        item = os.path.join(client_cwd, item)
                    else:
                        item = os.path.abspath(item)
                if not os.path.exists(item):
                    warnings.append(TaskValidationWarning("related_documentation", f"Documentation file not found: '{original_path}' - agents will skip if unavailable"))
                validated_docs.append(item)
        validated['related_documentation'] = validated_docs

    # Validate conversation_history
    if conversation_history is not None:
        if not isinstance(conversation_history, list):
            raise TaskValidationError(
                "conversation_history",
                "Must be a list of message dictionaries",
                type(conversation_history).__name__
            )

        # Limit to 50 most recent messages
        if len(conversation_history) > 50:
            warnings.append(TaskValidationWarning(
                "conversation_history",
                f"Too many messages ({len(conversation_history)} > 50). Keeping only the last 50 messages."
            ))
            conversation_history = conversation_history[-50:]

        # Validate each message
        validated_messages = []
        for i, msg in enumerate(conversation_history):
            if not isinstance(msg, dict):
                raise TaskValidationError(
                    f"conversation_history[{i}]",
                    "Each message must be a dictionary",
                    type(msg).__name__
                )

            # Check required fields
            missing_fields = []
            if 'role' not in msg:
                missing_fields.append('role')
            if 'content' not in msg:
                missing_fields.append('content')

            if missing_fields:
                raise TaskValidationError(
                    f"conversation_history[{i}]",
                    f"Missing required fields: {', '.join(missing_fields)}",
                    list(msg.keys())
                )

            # Validate role
            role = msg['role'].strip().lower()
            if role not in ['user', 'assistant', 'orchestrator']:
                raise TaskValidationError(
                    f"conversation_history[{i}].role",
                    f"Role must be one of ['user', 'assistant', 'orchestrator'], got '{role}'",
                    role
                )

            # Get and clean content
            content = str(msg['content']).strip()

            # Skip empty messages
            if not content:
                warnings.append(TaskValidationWarning(
                    f"conversation_history[{i}].content",
                    "Empty message content - message will be skipped"
                ))
                continue

            # Validate/fix timestamp
            timestamp = msg.get('timestamp', '')
            if not timestamp:
                timestamp = datetime.now().isoformat()
                warnings.append(TaskValidationWarning(
                    f"conversation_history[{i}].timestamp",
                    f"Missing timestamp - added current time: {timestamp}"
                ))
            else:
                try:
                    datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                except (ValueError, AttributeError):
                    new_timestamp = datetime.now().isoformat()
                    timestamp = new_timestamp
                    warnings.append(TaskValidationWarning(
                        f"conversation_history[{i}].timestamp",
                        f"Invalid timestamp format - replaced with current time"
                    ))

            validated_messages.append({
                'role': role,
                'content': content,
                'timestamp': timestamp
            })

        # Check if all messages were filtered out
        if len(validated_messages) == 0:
            warnings.append(TaskValidationWarning(
                "conversation_history",
                "All messages were filtered out due to validation issues. History will be omitted."
            ))
            validated['conversation_history'] = None
        else:
            validated['conversation_history'] = validated_messages

    return validated, warnings
