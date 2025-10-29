"""
Enhanced Task Creation - Validation Implementation
===================================================

This module provides validation logic for the enhanced create_real_task() function.
Designed to be integrated into real_mcp_server.py.

Author: schema_architect-124235-2882df
Date: 2025-10-29
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
import os
import re


class TaskValidationError(ValueError):
    """Raised when task parameters fail validation"""

    def __init__(self, field: str, reason: str, value: Any):
        self.field = field
        self.reason = reason
        self.value = value
        super().__init__(f"Validation failed for '{field}': {reason}")


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


def validate_task_parameters(
    description: str,
    priority: str = "P2",
    background_context: Optional[str] = None,
    expected_deliverables: Optional[List[str]] = None,
    success_criteria: Optional[List[str]] = None,
    constraints: Optional[List[str]] = None,
    relevant_files: Optional[List[str]] = None,
    related_documentation: Optional[List[str]] = None,
    client_cwd: Optional[str] = None
) -> Tuple[Dict[str, Any], List[TaskValidationWarning]]:
    """
    Validate all task parameters and return cleaned data + warnings.

    Args:
        description: Task description (required)
        priority: Priority level (P0-P3)
        background_context: Multi-line context about the problem
        expected_deliverables: List of concrete outputs required
        success_criteria: List of measurable completion criteria
        constraints: List of boundaries agents must respect
        relevant_files: List of file paths to examine
        related_documentation: List of docs to reference
        client_cwd: Client working directory for path resolution

    Returns:
        Tuple of (validated_data, warnings)

    Raises:
        TaskValidationError: On critical validation failures
    """
    warnings: List[TaskValidationWarning] = []
    validated: Dict[str, Any] = {}

    # =========================================================================
    # REQUIRED FIELDS
    # =========================================================================

    # Validate description
    description = description.strip()
    if len(description) < 10:
        raise TaskValidationError(
            "description",
            "Must be at least 10 characters",
            description
        )
    if len(description) > 500:
        raise TaskValidationError(
            "description",
            "Must be at most 500 characters",
            description
        )

    # Check for overly generic descriptions
    generic_patterns = [
        r'^fix bug$',
        r'^do task$',
        r'^implement feature$',
        r'^update code$'
    ]
    if any(re.match(pattern, description.lower()) for pattern in generic_patterns):
        warnings.append(TaskValidationWarning(
            "description",
            f"Description is too generic: '{description}'. Consider being more specific."
        ))

    validated['description'] = description

    # =========================================================================
    # OPTIONAL FIELDS WITH DEFAULTS
    # =========================================================================

    # Validate priority
    priority = priority.upper()
    if priority not in ["P0", "P1", "P2", "P3"]:
        raise TaskValidationError(
            "priority",
            "Must be P0, P1, P2, or P3",
            priority
        )
    validated['priority'] = priority

    # =========================================================================
    # OPTIONAL ENHANCEMENT FIELDS
    # =========================================================================

    # Validate background_context
    if background_context is not None:
        background_context = background_context.strip()

        if len(background_context) < 50:
            warnings.append(TaskValidationWarning(
                "background_context",
                f"Background context is very short ({len(background_context)} chars). "
                "Consider adding more detail for better agent understanding."
            ))

        if len(background_context) > 5000:
            raise TaskValidationError(
                "background_context",
                "Must be at most 5000 characters",
                f"{background_context[:100]}..."
            )

        validated['background_context'] = background_context

    # Validate expected_deliverables
    if expected_deliverables is not None:
        # Clean and deduplicate
        deliverables = [d.strip() for d in expected_deliverables if d and d.strip()]
        deliverables = list(dict.fromkeys(deliverables))  # Remove duplicates, preserve order

        if len(deliverables) == 0:
            warnings.append(TaskValidationWarning(
                "expected_deliverables",
                "List is empty after filtering. Consider omitting this parameter."
            ))

        if len(deliverables) > 20:
            raise TaskValidationError(
                "expected_deliverables",
                f"Maximum 20 items allowed, got {len(deliverables)}",
                deliverables
            )

        for i, item in enumerate(deliverables):
            if len(item) < 10:
                warnings.append(TaskValidationWarning(
                    f"expected_deliverables[{i}]",
                    f"Deliverable is very short: '{item}'. Consider being more specific."
                ))

            if len(item) > 200:
                raise TaskValidationError(
                    f"expected_deliverables[{i}]",
                    "Each item must be at most 200 characters",
                    item
                )

        validated['expected_deliverables'] = {
            'items': deliverables,
            'validation_added': datetime.now().isoformat()
        }

    # Validate success_criteria
    if success_criteria is not None:
        # Clean and deduplicate
        criteria = [c.strip() for c in success_criteria if c and c.strip()]
        criteria = list(dict.fromkeys(criteria))

        if len(criteria) == 0:
            warnings.append(TaskValidationWarning(
                "success_criteria",
                "List is empty after filtering. Consider omitting this parameter."
            ))

        if len(criteria) > 15:
            raise TaskValidationError(
                "success_criteria",
                f"Maximum 15 items allowed, got {len(criteria)}",
                criteria
            )

        # Check each criterion
        measurable_keywords = [
            'pass', 'complete', 'under', 'above', 'below', 'equal', 'verify',
            'test', 'validate', 'all', 'no', 'zero', 'every', 'none',
            'within', 'less than', 'greater than', 'at least', 'at most'
        ]

        for i, item in enumerate(criteria):
            if len(item) < 10:
                warnings.append(TaskValidationWarning(
                    f"success_criteria[{i}]",
                    f"Criterion is very short: '{item}'. Consider being more specific."
                ))

            if len(item) > 200:
                raise TaskValidationError(
                    f"success_criteria[{i}]",
                    "Each item must be at most 200 characters",
                    item
                )

            # Check if criterion is measurable
            if not any(keyword in item.lower() for keyword in measurable_keywords):
                warnings.append(TaskValidationWarning(
                    f"success_criteria[{i}]",
                    f"Criterion may not be measurable: '{item}'. "
                    "Consider adding quantifiable metrics (e.g., 'all tests pass', 'latency under 100ms')."
                ))

        validated['success_criteria'] = {
            'criteria': criteria,
            'all_required': True
        }

    # Validate constraints
    if constraints is not None:
        # Clean and deduplicate
        constraint_list = [c.strip() for c in constraints if c and c.strip()]
        constraint_list = list(dict.fromkeys(constraint_list))

        if len(constraint_list) == 0:
            warnings.append(TaskValidationWarning(
                "constraints",
                "List is empty after filtering. Consider omitting this parameter."
            ))

        if len(constraint_list) > 15:
            raise TaskValidationError(
                "constraints",
                f"Maximum 15 items allowed, got {len(constraint_list)}",
                constraint_list
            )

        # Check each constraint
        constraint_keywords = [
            'do not', 'must not', 'never', 'cannot', 'should not',
            'must use', 'required to', 'only use', 'must maintain'
        ]

        for i, item in enumerate(constraint_list):
            if len(item) < 10:
                warnings.append(TaskValidationWarning(
                    f"constraints[{i}]",
                    f"Constraint is very short: '{item}'. Consider being more specific."
                ))

            if len(item) > 200:
                raise TaskValidationError(
                    f"constraints[{i}]",
                    "Each item must be at most 200 characters",
                    item
                )

            # Check if constraint follows recommended format
            if not any(keyword in item.lower() for keyword in constraint_keywords):
                warnings.append(TaskValidationWarning(
                    f"constraints[{i}]",
                    f"Constraint should start with imperative (e.g., 'Do not...', 'Must use...'): '{item}'"
                ))

        validated['constraints'] = {
            'rules': constraint_list,
            'enforcement_level': 'strict'
        }

    # Validate relevant_files
    if relevant_files is not None:
        # Clean and deduplicate
        file_list = [f.strip() for f in relevant_files if f and f.strip()]
        file_list = list(dict.fromkeys(file_list))

        if len(file_list) == 0:
            warnings.append(TaskValidationWarning(
                "relevant_files",
                "List is empty after filtering. Consider omitting this parameter."
            ))

        if len(file_list) > 50:
            raise TaskValidationError(
                "relevant_files",
                f"Maximum 50 files allowed, got {len(file_list)}",
                file_list
            )

        validated_files = []
        for filepath in file_list:
            original_path = filepath

            # Resolve relative paths
            if not os.path.isabs(filepath):
                if client_cwd:
                    filepath = os.path.join(client_cwd, filepath)
                else:
                    filepath = os.path.abspath(filepath)

            # Resolve symlinks
            try:
                filepath = os.path.realpath(filepath)
            except Exception as e:
                warnings.append(TaskValidationWarning(
                    "relevant_files",
                    f"Could not resolve path '{original_path}': {e}"
                ))
                continue

            # Check existence (warning, not error)
            if not os.path.exists(filepath):
                warnings.append(TaskValidationWarning(
                    "relevant_files",
                    f"File not found: '{filepath}' - agents will skip if unavailable"
                ))
            elif not os.path.isfile(filepath):
                warnings.append(TaskValidationWarning(
                    "relevant_files",
                    f"Path is not a file: '{filepath}' - may be a directory"
                ))

            validated_files.append(filepath)

        validated['relevant_files'] = validated_files

    # Validate related_documentation
    if related_documentation is not None:
        # Clean and deduplicate
        doc_list = [d.strip() for d in related_documentation if d and d.strip()]
        doc_list = list(dict.fromkeys(doc_list))

        if len(doc_list) == 0:
            warnings.append(TaskValidationWarning(
                "related_documentation",
                "List is empty after filtering. Consider omitting this parameter."
            ))

        if len(doc_list) > 20:
            raise TaskValidationError(
                "related_documentation",
                f"Maximum 20 items allowed, got {len(doc_list)}",
                doc_list
            )

        validated_docs = []
        for item in doc_list:
            # Check if URL
            if item.startswith('http://') or item.startswith('https://'):
                # Basic URL validation
                if ' ' in item:
                    warnings.append(TaskValidationWarning(
                        "related_documentation",
                        f"URL contains spaces (may be invalid): '{item}'"
                    ))

                # Check for common URL issues
                if item.endswith('.'):
                    warnings.append(TaskValidationWarning(
                        "related_documentation",
                        f"URL ends with period (may be typo): '{item}'"
                    ))

                validated_docs.append(item)
            else:
                # Treat as file path
                original_path = item

                if not os.path.isabs(item):
                    if client_cwd:
                        item = os.path.join(client_cwd, item)
                    else:
                        item = os.path.abspath(item)

                if not os.path.exists(item):
                    warnings.append(TaskValidationWarning(
                        "related_documentation",
                        f"Documentation file not found: '{original_path}' - agents will skip if unavailable"
                    ))

                validated_docs.append(item)

        validated['related_documentation'] = validated_docs

    return validated, warnings


def build_agent_context_section(task_context: Dict[str, Any]) -> str:
    """
    Build structured context section for agent prompts.

    This function is called by deploy_headless_agent() to inject
    enhanced task context into agent prompts.

    Args:
        task_context: The 'task_context' field from registry

    Returns:
        Formatted context section string, or empty string if no context
    """
    if not task_context:
        return ""

    sections = []

    # Background context
    if bg := task_context.get('background_context'):
        sections.append(f"""
📋 BACKGROUND CONTEXT:
{bg}
""")

    # Expected deliverables
    if deliverables := task_context.get('expected_deliverables', {}).get('items'):
        items = '\n'.join(f"  • {d}" for d in deliverables)
        sections.append(f"""
✅ EXPECTED DELIVERABLES:
{items}

You MUST produce these deliverables. Report each one when complete.
""")

    # Success criteria
    if criteria := task_context.get('success_criteria', {}).get('criteria'):
        items = '\n'.join(f"  • {c}" for c in criteria)
        all_required = task_context.get('success_criteria', {}).get('all_required', True)
        requirement = "ALL criteria must be met" if all_required else "Meet as many as possible"

        sections.append(f"""
🎯 SUCCESS CRITERIA ({requirement}):
{items}

Your work is only complete when these criteria are verified.
""")

    # Constraints
    if constraints := task_context.get('constraints', {}).get('rules'):
        items = '\n'.join(f"  • {c}" for c in constraints)
        enforcement = task_context.get('constraints', {}).get('enforcement_level', 'strict')

        sections.append(f"""
⚠️ CONSTRAINTS (Enforcement: {enforcement.upper()}):
{items}

CRITICAL: You MUST respect these constraints. Violating them may break other systems.
""")

    # Relevant files
    if files := task_context.get('relevant_files'):
        # Limit display to first 10 files to avoid overwhelming the prompt
        display_files = files[:10]
        items = '\n'.join(f"  • {f}" for f in display_files)

        if len(files) > 10:
            items += f"\n  • ... and {len(files) - 10} more files (check task registry for complete list)"

        sections.append(f"""
📁 RELEVANT FILES TO EXAMINE:
{items}

These files are relevant to your task. Examine them before making changes.
""")

    # Related documentation
    if docs := task_context.get('related_documentation'):
        items = '\n'.join(f"  • {d}" for d in docs)
        sections.append(f"""
📚 RELATED DOCUMENTATION:
{items}

Reference these documents to understand requirements and best practices.
""")

    # Validation warnings (if any)
    if warnings := task_context.get('validation_warnings'):
        warning_items = '\n'.join(f"  ⚠️ {w}" for w in warnings[:5])  # Limit to 5 warnings
        sections.append(f"""
🔍 VALIDATION WARNINGS:
{warning_items}

Note: Some files or URLs may not be accessible. Proceed with available resources.
""")

    if sections:
        return f"""
{'='*80}
🎯 TASK CONTEXT (Provided by task creator)
{'='*80}

The following context was provided when this task was created.
Use this information to guide your work and ensure you meet expectations.

{''.join(sections)}
{'='*80}

"""
    return ""


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    """
    Example usage of validation functions.
    Run this file directly to test validation logic.
    """

    print("=" * 80)
    print("ENHANCED TASK CREATION - VALIDATION EXAMPLES")
    print("=" * 80)
    print()

    # Example 1: Valid enhanced task
    print("Example 1: Valid Enhanced Task")
    print("-" * 80)
    try:
        validated, warnings = validate_task_parameters(
            description="Implement JWT token authentication system",
            priority="P1",
            background_context="""
                Current OAuth2 implementation uses deprecated token format.
                Users report intermittent login failures after 2 hours.
                Need to migrate to JWT standard while maintaining backward
                compatibility with existing sessions for 30 days.
            """,
            expected_deliverables=[
                "Updated authentication handler in src/auth/handler.py",
                "JWT token validation function with expiry handling",
                "Migration script for existing sessions",
                "Integration tests covering auth flow",
                "Documentation update in docs/authentication.md"
            ],
            success_criteria=[
                "All existing integration tests pass",
                "New JWT tokens validate successfully",
                "Legacy token format accepted for 30 days",
                "Zero user sessions invalidated",
                "Authentication latency under 100ms p95"
            ],
            constraints=[
                "Do not modify src/auth/legacy.py - used by payment service",
                "Must use pyjwt library version 2.8.0",
                "No database schema changes allowed",
                "Must maintain REST API backward compatibility"
            ],
            relevant_files=[
                "src/auth/handler.py",
                "src/auth/tokens.py",
                "tests/test_auth.py"
            ],
            related_documentation=[
                "https://jwt.io/introduction",
                "https://pyjwt.readthedocs.io/"
            ]
        )

        print("✅ VALIDATION PASSED")
        print(f"Validated fields: {list(validated.keys())}")
        print(f"Warnings: {len(warnings)}")
        for w in warnings:
            print(f"  ⚠️ {w.field}: {w.message}")

    except TaskValidationError as e:
        print(f"❌ VALIDATION FAILED: {e}")

    print()

    # Example 2: Invalid task (too short description)
    print("Example 2: Invalid Task (Description Too Short)")
    print("-" * 80)
    try:
        validated, warnings = validate_task_parameters(
            description="Fix bug"  # Too short!
        )
        print("✅ VALIDATION PASSED (unexpected)")
    except TaskValidationError as e:
        print(f"❌ VALIDATION FAILED (expected): {e}")

    print()

    # Example 3: Task with warnings
    print("Example 3: Task with Validation Warnings")
    print("-" * 80)
    try:
        validated, warnings = validate_task_parameters(
            description="Update authentication system with new token format",
            expected_deliverables=[
                "Fix it",  # Too vague
                "Test it",  # Too short
                "Done"  # Too short
            ],
            success_criteria=[
                "It works",  # Not measurable
                "Looks good"  # Not measurable
            ],
            relevant_files=[
                "nonexistent_file.py",  # Doesn't exist
                "another_missing.py"  # Doesn't exist
            ]
        )

        print("✅ VALIDATION PASSED (with warnings)")
        print(f"Warnings: {len(warnings)}")
        for w in warnings:
            print(f"  ⚠️ {w.field}: {w.message}")

    except TaskValidationError as e:
        print(f"❌ VALIDATION FAILED: {e}")

    print()

    # Example 4: Context section formatting
    print("Example 4: Agent Context Section Formatting")
    print("-" * 80)

    mock_task_context = {
        'background_context': "Users report login failures after OAuth2 migration.",
        'expected_deliverables': {
            'items': [
                "Updated auth handler",
                "JWT validator",
                "Migration script"
            ]
        },
        'success_criteria': {
            'criteria': [
                "All tests pass",
                "Zero session invalidations"
            ],
            'all_required': True
        },
        'constraints': {
            'rules': [
                "Do not modify legacy.py",
                "Must use pyjwt 2.8.0"
            ],
            'enforcement_level': 'strict'
        }
    }

    context_section = build_agent_context_section(mock_task_context)
    print(context_section)

    print()
    print("=" * 80)
    print("VALIDATION EXAMPLES COMPLETE")
    print("=" * 80)
