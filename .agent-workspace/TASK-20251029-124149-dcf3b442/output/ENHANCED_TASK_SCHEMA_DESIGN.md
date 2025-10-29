# Enhanced Task Creation Schema Design
**Agent:** schema_architect-124235-2882df
**Date:** 2025-10-29
**Version:** 1.0

## Executive Summary

This document defines a comprehensive schema enhancement for `create_real_task()` that reduces agent hallucinations by providing structured context, clear boundaries, and measurable success criteria.

---

## 1. Enhanced Function Signature

```python
from typing import Dict, List, Optional, Any

def create_real_task(
    description: str,
    priority: str = "P2",
    client_cwd: Optional[str] = None,
    # NEW PARAMETERS - All optional for backward compatibility
    background_context: Optional[str] = None,
    expected_deliverables: Optional[List[str]] = None,
    success_criteria: Optional[List[str]] = None,
    constraints: Optional[List[str]] = None,
    relevant_files: Optional[List[str]] = None,
    related_documentation: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Create a real orchestration task with enhanced structured context.

    Args:
        description: Brief task description (required, 10-500 chars)
        priority: Task priority - "P0" (critical), "P1" (high), "P2" (medium), "P3" (low)
        client_cwd: Optional client working directory

        # Context Enhancement Fields (NEW)
        background_context: Multi-line context explaining the problem, current state,
                          and why this task is needed. Max 5000 chars.
        expected_deliverables: List of concrete outputs agents must produce.
                              Each deliverable should be specific and measurable.
                              Max 20 items, each max 200 chars.
        success_criteria: List of measurable completion criteria that define "done".
                        Each criterion should be verifiable and objective.
                        Max 15 items, each max 200 chars.
        constraints: List of boundaries agents must respect (e.g., "Do not modify X",
                   "Must use library Y", "No external API calls").
                   Max 15 items, each max 200 chars.
        relevant_files: List of file paths agents should examine. Paths will be
                      validated to ensure they exist. Max 50 files.
        related_documentation: List of documentation URLs or file paths agents should
                             reference. Max 20 items.

    Returns:
        Task creation result including task_id, workspace, and validation results

    Raises:
        ValueError: If validation fails (invalid formats, non-existent files, etc.)
    """
```

---

## 2. Type Definitions

```python
from typing import TypedDict, List, Optional
from datetime import datetime

class TaskDeliverables(TypedDict, total=False):
    """Structured deliverables specification"""
    items: List[str]  # List of deliverable descriptions
    validation_added: datetime  # When validation was added

class TaskSuccessCriteria(TypedDict, total=False):
    """Success criteria specification"""
    criteria: List[str]  # List of measurable criteria
    all_required: bool  # Whether all criteria must be met (default: True)

class TaskConstraints(TypedDict, total=False):
    """Task constraints and boundaries"""
    rules: List[str]  # List of constraint rules
    enforcement_level: str  # "strict" | "advisory" (default: "strict")

class TaskContext(TypedDict, total=False):
    """Enhanced context structure stored in registry"""
    background_context: Optional[str]
    expected_deliverables: Optional[TaskDeliverables]
    success_criteria: Optional[TaskSuccessCriteria]
    constraints: Optional[TaskConstraints]
    relevant_files: Optional[List[str]]
    related_documentation: Optional[List[str]]
    validation_performed: bool
    validation_timestamp: str  # ISO format
    validation_warnings: List[str]  # Non-fatal validation issues
```

---

## 3. Registry Storage Schema

### 3.1 Current Registry Structure (Before)
```json
{
  "task_id": "TASK-20251029-123456-abcd1234",
  "task_description": "Fix the authentication bug",
  "created_at": "2025-10-29T12:34:56.789012",
  "workspace": "/path/.agent-workspace/TASK-xxx",
  "status": "INITIALIZED",
  "priority": "P2",
  "agents": []
}
```

### 3.2 Enhanced Registry Structure (After)
```json
{
  "task_id": "TASK-20251029-123456-abcd1234",
  "task_description": "Fix the authentication bug",
  "created_at": "2025-10-29T12:34:56.789012",
  "workspace": "/path/.agent-workspace/TASK-xxx",
  "status": "INITIALIZED",
  "priority": "P2",
  "agents": [],

  "task_context": {
    "background_context": "Users report login failures after OAuth2 migration. Current auth flow uses deprecated token format. Need to update to new JWT standard while maintaining backward compatibility with existing sessions.",

    "expected_deliverables": {
      "items": [
        "Updated authentication handler in src/auth/handler.py",
        "JWT token validation function",
        "Migration script for existing sessions",
        "Integration tests for auth flow",
        "Documentation update in docs/auth.md"
      ],
      "validation_added": "2025-10-29T12:34:56.789012"
    },

    "success_criteria": {
      "criteria": [
        "All existing integration tests pass",
        "New JWT tokens validate successfully",
        "Legacy token format still accepted for 30 days",
        "No user sessions are invalidated during migration",
        "Auth latency remains under 100ms"
      ],
      "all_required": true
    },

    "constraints": {
      "rules": [
        "Do not modify src/auth/legacy.py - used by other systems",
        "Must use existing 'pyjwt' library version 2.8.0",
        "No database schema changes allowed",
        "Maintain API backward compatibility"
      ],
      "enforcement_level": "strict"
    },

    "relevant_files": [
      "src/auth/handler.py",
      "src/auth/tokens.py",
      "tests/test_auth.py",
      "docs/auth.md"
    ],

    "related_documentation": [
      "https://jwt.io/introduction",
      "docs/oauth2-migration-guide.md",
      "https://internal-wiki/auth-standards"
    ],

    "validation_performed": true,
    "validation_timestamp": "2025-10-29T12:34:56.789012",
    "validation_warnings": [
      "File docs/oauth2-migration-guide.md not found - will be skipped",
      "URL https://internal-wiki/auth-standards not accessible - agents should verify independently"
    ]
  }
}
```

### 3.3 Global Registry Updates
```json
{
  "total_tasks": 42,
  "active_tasks": 3,
  "tasks": {
    "TASK-20251029-123456-abcd1234": {
      "description": "Fix the authentication bug",
      "created_at": "2025-10-29T12:34:56.789012",
      "status": "INITIALIZED",
      "has_enhanced_context": true,
      "deliverables_count": 5,
      "success_criteria_count": 5
    }
  }
}
```

---

## 4. Validation Rules

### 4.1 Required Field Validation
```python
# description - REQUIRED
- Minimum length: 10 characters
- Maximum length: 500 characters
- Must not be empty or only whitespace
- Should be descriptive (not just "Fix bug" or "Do task")

# priority - OPTIONAL (default: "P2")
- Must be one of: "P0", "P1", "P2", "P3"
- Case-insensitive validation
```

### 4.2 Optional Field Validation
```python
# background_context - OPTIONAL
- Maximum length: 5000 characters
- If provided, minimum length: 50 characters (encourage meaningful context)
- Stripped of leading/trailing whitespace
- Multi-line text allowed and encouraged

# expected_deliverables - OPTIONAL
- Maximum items: 20
- Each item minimum length: 10 characters
- Each item maximum length: 200 characters
- Each item should start with action verb or be specific noun phrase
- Duplicates removed automatically
- Empty strings filtered out

# success_criteria - OPTIONAL
- Maximum items: 15
- Each criterion minimum length: 10 characters
- Each criterion maximum length: 200 characters
- Should be measurable/verifiable (flag non-measurable criteria as warnings)
- Duplicates removed automatically
- Empty strings filtered out

# constraints - OPTIONAL
- Maximum items: 15
- Each constraint minimum length: 10 characters
- Each constraint maximum length: 200 characters
- Should start with negative imperative ("Do not", "Must not", "Never")
  or positive requirement ("Must use", "Required to")
- Duplicates removed automatically
- Empty strings filtered out

# relevant_files - OPTIONAL
- Maximum items: 50
- Each path validated for existence (warnings if not found, not errors)
- Relative paths resolved against client_cwd or server workspace
- Symlinks resolved to actual paths
- Duplicates removed automatically
- Non-existent files logged as warnings but not rejected

# related_documentation - OPTIONAL
- Maximum items: 20
- Each item can be URL or file path
- URLs validated for format (http/https)
- File paths validated for existence (warnings if not found)
- Duplicates removed automatically
```

### 4.3 Validation Error Handling
```python
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
```

---

## 5. Validation Logic Implementation

```python
def validate_task_parameters(
    description: str,
    priority: str,
    background_context: Optional[str],
    expected_deliverables: Optional[List[str]],
    success_criteria: Optional[List[str]],
    constraints: Optional[List[str]],
    relevant_files: Optional[List[str]],
    related_documentation: Optional[List[str]],
    client_cwd: Optional[str]
) -> tuple[Dict[str, Any], List[TaskValidationWarning]]:
    """
    Validate all task parameters and return cleaned data + warnings.

    Returns:
        Tuple of (validated_data, warnings)

    Raises:
        TaskValidationError: On critical validation failures
    """
    warnings = []
    validated = {}

    # Validate description (REQUIRED)
    description = description.strip()
    if len(description) < 10:
        raise TaskValidationError("description", "Must be at least 10 characters", description)
    if len(description) > 500:
        raise TaskValidationError("description", "Must be at most 500 characters", description)
    validated['description'] = description

    # Validate priority (OPTIONAL with default)
    priority = priority.upper()
    if priority not in ["P0", "P1", "P2", "P3"]:
        raise TaskValidationError("priority", "Must be P0, P1, P2, or P3", priority)
    validated['priority'] = priority

    # Validate background_context (OPTIONAL)
    if background_context:
        background_context = background_context.strip()
        if len(background_context) < 50:
            warnings.append(TaskValidationWarning(
                "background_context",
                "Background context is very short (<50 chars). Consider adding more detail."
            ))
        if len(background_context) > 5000:
            raise TaskValidationError("background_context", "Must be at most 5000 characters", background_context)
        validated['background_context'] = background_context

    # Validate expected_deliverables (OPTIONAL)
    if expected_deliverables:
        deliverables = [d.strip() for d in expected_deliverables if d and d.strip()]
        deliverables = list(dict.fromkeys(deliverables))  # Remove duplicates, preserve order

        if len(deliverables) > 20:
            raise TaskValidationError("expected_deliverables", "Maximum 20 items allowed", deliverables)

        for i, item in enumerate(deliverables):
            if len(item) < 10:
                warnings.append(TaskValidationWarning(
                    f"expected_deliverables[{i}]",
                    f"Deliverable is very short: '{item}'. Consider being more specific."
                ))
            if len(item) > 200:
                raise TaskValidationError(f"expected_deliverables[{i}]", "Each item must be at most 200 characters", item)

        validated['expected_deliverables'] = {
            'items': deliverables,
            'validation_added': datetime.now().isoformat()
        }

    # Validate success_criteria (OPTIONAL)
    if success_criteria:
        criteria = [c.strip() for c in success_criteria if c and c.strip()]
        criteria = list(dict.fromkeys(criteria))  # Remove duplicates

        if len(criteria) > 15:
            raise TaskValidationError("success_criteria", "Maximum 15 items allowed", criteria)

        for i, item in enumerate(criteria):
            if len(item) < 10:
                warnings.append(TaskValidationWarning(
                    f"success_criteria[{i}]",
                    f"Criterion is very short: '{item}'. Consider being more specific."
                ))
            if len(item) > 200:
                raise TaskValidationError(f"success_criteria[{i}]", "Each item must be at most 200 characters", item)

            # Check if criterion is measurable
            measurable_keywords = ['pass', 'complete', 'under', 'above', 'equal', 'verify', 'test', 'validate', 'all', 'no', 'zero']
            if not any(keyword in item.lower() for keyword in measurable_keywords):
                warnings.append(TaskValidationWarning(
                    f"success_criteria[{i}]",
                    f"Criterion may not be measurable: '{item}'. Consider adding quantifiable metrics."
                ))

        validated['success_criteria'] = {
            'criteria': criteria,
            'all_required': True
        }

    # Validate constraints (OPTIONAL)
    if constraints:
        constraint_list = [c.strip() for c in constraints if c and c.strip()]
        constraint_list = list(dict.fromkeys(constraint_list))  # Remove duplicates

        if len(constraint_list) > 15:
            raise TaskValidationError("constraints", "Maximum 15 items allowed", constraint_list)

        for i, item in enumerate(constraint_list):
            if len(item) < 10:
                warnings.append(TaskValidationWarning(
                    f"constraints[{i}]",
                    f"Constraint is very short: '{item}'. Consider being more specific."
                ))
            if len(item) > 200:
                raise TaskValidationError(f"constraints[{i}]", "Each item must be at most 200 characters", item)

            # Check if constraint follows recommended format
            constraint_keywords = ['do not', 'must not', 'never', 'must use', 'required to', 'only use', 'cannot']
            if not any(keyword in item.lower() for keyword in constraint_keywords):
                warnings.append(TaskValidationWarning(
                    f"constraints[{i}]",
                    f"Constraint should start with imperative: '{item}'"
                ))

        validated['constraints'] = {
            'rules': constraint_list,
            'enforcement_level': 'strict'
        }

    # Validate relevant_files (OPTIONAL)
    if relevant_files:
        file_list = [f.strip() for f in relevant_files if f and f.strip()]
        file_list = list(dict.fromkeys(file_list))  # Remove duplicates

        if len(file_list) > 50:
            raise TaskValidationError("relevant_files", "Maximum 50 files allowed", file_list)

        validated_files = []
        for filepath in file_list:
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
                    f"Could not resolve path '{filepath}': {e}"
                ))
                continue

            # Check existence
            if not os.path.exists(filepath):
                warnings.append(TaskValidationWarning(
                    "relevant_files",
                    f"File not found: '{filepath}' - will be skipped by agents"
                ))

            validated_files.append(filepath)

        validated['relevant_files'] = validated_files

    # Validate related_documentation (OPTIONAL)
    if related_documentation:
        doc_list = [d.strip() for d in related_documentation if d and d.strip()]
        doc_list = list(dict.fromkeys(doc_list))  # Remove duplicates

        if len(doc_list) > 20:
            raise TaskValidationError("related_documentation", "Maximum 20 items allowed", doc_list)

        validated_docs = []
        for item in doc_list:
            # Check if URL
            if item.startswith('http://') or item.startswith('https://'):
                # Basic URL validation
                if ' ' in item:
                    warnings.append(TaskValidationWarning(
                        "related_documentation",
                        f"URL contains spaces: '{item}'"
                    ))
                validated_docs.append(item)
            else:
                # Treat as file path
                if not os.path.isabs(item):
                    if client_cwd:
                        item = os.path.join(client_cwd, item)
                    else:
                        item = os.path.abspath(item)

                if not os.path.exists(item):
                    warnings.append(TaskValidationWarning(
                        "related_documentation",
                        f"Documentation file not found: '{item}'"
                    ))

                validated_docs.append(item)

        validated['related_documentation'] = validated_docs

    return validated, warnings
```

---

## 6. Sensible Defaults

```python
DEFAULT_VALUES = {
    'priority': 'P2',
    'client_cwd': None,
    'background_context': None,
    'expected_deliverables': None,
    'success_criteria': None,
    'constraints': None,
    'relevant_files': None,
    'related_documentation': None
}

# When fields are None, they are NOT added to the registry
# This keeps registry clean and maintains backward compatibility
```

---

## 7. Usage Examples

### 7.1 Minimal Usage (Backward Compatible)
```python
# Works exactly as before - no breaking changes
result = create_real_task(
    description="Fix authentication bug in login flow"
)
```

### 7.2 Enhanced Usage (Good Example)
```python
result = create_real_task(
    description="Implement JWT token authentication",
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
        "Migration script for existing sessions in scripts/migrate_auth.py",
        "Integration tests covering auth flow in tests/test_auth_flow.py",
        "Documentation update in docs/authentication.md"
    ],
    success_criteria=[
        "All existing integration tests pass without modification",
        "New JWT tokens validate successfully with proper expiry",
        "Legacy token format accepted for 30 days grace period",
        "Zero user sessions invalidated during migration",
        "Authentication latency remains under 100ms p95"
    ],
    constraints=[
        "Do not modify src/auth/legacy.py - used by payment service",
        "Must use existing pyjwt library version 2.8.0 from requirements.txt",
        "No database schema changes allowed in this sprint",
        "Must maintain REST API backward compatibility"
    ],
    relevant_files=[
        "src/auth/handler.py",
        "src/auth/tokens.py",
        "src/auth/middleware.py",
        "tests/test_auth.py",
        "requirements.txt"
    ],
    related_documentation=[
        "https://jwt.io/introduction",
        "docs/oauth2-migration-guide.md",
        "https://pyjwt.readthedocs.io/en/stable/"
    ]
)
```

### 7.3 Poor Usage Example (What NOT to Do)
```python
# BAD - Too vague, no structure
result = create_real_task(
    description="Fix bug",  # Too short - will raise validation error
    expected_deliverables=["Fix it", "Test it"],  # Too vague
    success_criteria=["It works"],  # Not measurable
    constraints=["Do it fast"]  # Not a real constraint
)
# This will raise TaskValidationError or generate many warnings
```

---

## 8. Integration Points

### 8.1 How Agents Access Context
```python
# In deploy_headless_agent(), the enhanced context is injected into agent prompt:

def deploy_headless_agent(task_id, agent_type, prompt, parent):
    # Load registry
    registry = load_registry(task_id)

    # Build enhanced context section for agent prompt
    context_section = build_agent_context_section(registry.get('task_context', {}))

    # Inject into agent prompt
    full_prompt = f"""
{context_section}

{prompt}
"""

    # Deploy agent with enhanced prompt...
```

### 8.2 Helper Function for Context Injection
```python
def build_agent_context_section(task_context: Dict[str, Any]) -> str:
    """Build structured context section for agent prompts"""
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
""")

    # Success criteria
    if criteria := task_context.get('success_criteria', {}).get('criteria'):
        items = '\n'.join(f"  • {c}" for c in criteria)
        sections.append(f"""
🎯 SUCCESS CRITERIA:
{items}
""")

    # Constraints
    if constraints := task_context.get('constraints', {}).get('rules'):
        items = '\n'.join(f"  • {c}" for c in constraints)
        sections.append(f"""
⚠️ CONSTRAINTS:
{items}
""")

    # Relevant files
    if files := task_context.get('relevant_files'):
        items = '\n'.join(f"  • {f}" for f in files[:10])  # Limit to first 10
        if len(files) > 10:
            items += f"\n  • ... and {len(files) - 10} more files"
        sections.append(f"""
📁 RELEVANT FILES TO EXAMINE:
{items}
""")

    # Related documentation
    if docs := task_context.get('related_documentation'):
        items = '\n'.join(f"  • {d}" for d in docs)
        sections.append(f"""
📚 RELATED DOCUMENTATION:
{items}
""")

    if sections:
        return f"""
{'='*80}
🎯 TASK CONTEXT (Provided by task creator)
{'='*80}

{''.join(sections)}

{'='*80}
"""
    return ""
```

---

## 9. Backward Compatibility Strategy

### 9.1 Function Signature Compatibility
- All new parameters are OPTIONAL with default `None`
- Existing calls with just `description` continue to work
- Registry structure is additive (new fields, no removals)

### 9.2 Registry Reading Compatibility
- Code reading registry should use `.get('task_context', {})` pattern
- Missing `task_context` field treated as empty/None
- Old tasks without enhanced context continue to function

### 9.3 Migration Path
- No migration required - old and new formats coexist
- Old tasks simply lack `task_context` field
- New tasks have `task_context` field when enhanced parameters provided

---

## 10. Error Handling Strategy

### 10.1 Critical Errors (Raise Exception)
- Description too short/long
- Invalid priority value
- Field length limits exceeded
- Too many items in lists

### 10.2 Warnings (Log but Continue)
- Files not found in relevant_files
- Documentation URLs not accessible
- Short deliverables/criteria (< 10 chars)
- Non-measurable success criteria
- Constraints not following recommended format

### 10.3 Return Value on Success
```python
{
    "success": True,
    "task_id": "TASK-xxx",
    "description": "...",
    "priority": "P1",
    "workspace": "/path/to/workspace",
    "status": "INITIALIZED",
    "validation": {
        "performed": True,
        "warnings": [
            "File docs/guide.md not found - will be skipped by agents",
            "Success criterion 'Code looks good' may not be measurable"
        ]
    }
}
```

### 10.4 Return Value on Validation Error
```python
{
    "success": False,
    "error": "Validation failed for 'description': Must be at least 10 characters",
    "field": "description",
    "value": "Fix bug"
}
```

---

## 11. Implementation Checklist

### Phase 1: Schema Definition
- [x] Define enhanced function signature
- [x] Create TypedDict definitions
- [x] Document validation rules
- [x] Design registry storage structure

### Phase 2: Validation Implementation
- [ ] Implement validate_task_parameters() function
- [ ] Add TaskValidationError exception class
- [ ] Add TaskValidationWarning class
- [ ] Write unit tests for validation logic

### Phase 3: Registry Integration
- [ ] Update create_real_task() to accept new parameters
- [ ] Integrate validation before registry creation
- [ ] Store validated context in registry['task_context']
- [ ] Update global registry with context metadata

### Phase 4: Agent Integration
- [ ] Implement build_agent_context_section() helper
- [ ] Update deploy_headless_agent() to inject context
- [ ] Test agents receive and utilize context correctly

### Phase 5: Testing & Documentation
- [ ] Write integration tests
- [ ] Update API documentation
- [ ] Create usage examples
- [ ] Add migration guide

---

## 12. Expected Impact

### Before Enhancement
```
Agent Prompt: "You are an analyzer. Fix the auth bug."
Agent Behavior: Guesses what "auth bug" means, makes assumptions,
                modifies wrong files, creates generic "fixes"
Result: Hallucinations, off-target work, requires human intervention
```

### After Enhancement
```
Agent Prompt:
  "You are an analyzer. Fix the JWT authentication issue.

   Background: OAuth2 tokens deprecated, users report failures...
   Deliverables: Updated handler.py, JWT validator, tests...
   Success Criteria: All tests pass, latency <100ms, zero invalidations...
   Constraints: Don't modify legacy.py, use pyjwt 2.8.0...
   Relevant Files: src/auth/handler.py, tests/test_auth.py...
   Documentation: https://jwt.io/introduction, docs/guide.md..."

Agent Behavior: Clear target, examines correct files, respects constraints,
                produces specified deliverables, validates against criteria
Result: Focused work, measurable completion, minimal hallucinations
```

---

## 13. Future Enhancements (Out of Scope)

- Agent-to-agent context sharing mechanisms
- Dynamic context updates during task execution
- Context templates for common task types
- AI-assisted context generation from description
- Validation rule customization per task type

---

## Conclusion

This schema design provides a comprehensive, backward-compatible enhancement to task creation that addresses the root cause of agent hallucinations by providing structured, validated context. The design balances flexibility (all fields optional) with guidance (validation rules, warnings) to encourage good practices without breaking existing workflows.

**Key Benefits:**
1. **Reduces hallucinations** - Clear boundaries and deliverables
2. **Backward compatible** - All new fields optional
3. **Validation-driven** - Catches errors early, provides helpful warnings
4. **Agent-friendly** - Structured context injected into prompts
5. **Measurable** - Success criteria enable objective completion verification
