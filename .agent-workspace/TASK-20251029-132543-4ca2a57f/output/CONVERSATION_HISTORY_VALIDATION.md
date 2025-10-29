# Conversation History Validation Rules Design

## Overview
Validation rules for `conversation_history` parameter in `create_real_task()` to ensure data quality and prevent token overflow.

**Integration Point:** `real_mcp_server.py:1482-1652` (validate_task_parameters function)

---

## 1. VALIDATION RULES

### 1.1 Data Structure
```python
conversation_history: Optional[List[Dict[str, str]]] = None

# Expected structure per message:
{
    "role": str,        # Required: "user" or "assistant"
    "content": str,     # Required: message content
    "timestamp": str    # Required: ISO 8601 format (e.g., "2025-10-29T13:30:00.123456")
}
```

### 1.2 Configuration Constants
```python
MAX_MESSAGES = 50                  # Maximum number of messages allowed
MAX_USER_MESSAGE_LENGTH = 150      # Max chars per user message (before truncation)
MAX_ASSISTANT_MESSAGE_LENGTH = 8192  # Max chars per assistant message (8KB)
MAX_TOTAL_HISTORY_SIZE = 15360      # Max total history after truncation (15KB)
VALID_ROLES = {"user", "assistant"}  # Only these roles are allowed
```

### 1.3 Critical Validation Checks (Raise TaskValidationError)

#### Check 1: Type Validation
```python
if conversation_history is not None:
    if not isinstance(conversation_history, list):
        raise TaskValidationError(
            "conversation_history",
            "Must be a list of message dictionaries",
            type(conversation_history).__name__
        )
```

#### Check 2: Message Structure Validation
```python
for i, msg in enumerate(conversation_history):
    if not isinstance(msg, dict):
        raise TaskValidationError(
            f"conversation_history[{i}]",
            "Each message must be a dictionary",
            type(msg).__name__
        )

    # Check required fields exist
    missing_fields = []
    if "role" not in msg:
        missing_fields.append("role")
    if "content" not in msg:
        missing_fields.append("content")

    if missing_fields:
        raise TaskValidationError(
            f"conversation_history[{i}]",
            f"Missing required fields: {', '.join(missing_fields)}",
            list(msg.keys())
        )
```

#### Check 3: Role Validation
```python
for i, msg in enumerate(conversation_history):
    role = msg.get("role", "").strip().lower()
    if role not in VALID_ROLES:
        raise TaskValidationError(
            f"conversation_history[{i}].role",
            f"Role must be one of {VALID_ROLES}, got '{role}'",
            role
        )
```

#### Check 4: Content Length Validation (Hard Limits)
```python
for i, msg in enumerate(conversation_history):
    content = msg.get("content", "")
    role = msg.get("role", "").strip().lower()

    # Hard maximum before truncation
    if role == "user" and len(content) > MAX_USER_MESSAGE_LENGTH * 2:  # 300 chars hard limit
        raise TaskValidationError(
            f"conversation_history[{i}].content",
            f"User message exceeds hard limit of {MAX_USER_MESSAGE_LENGTH * 2} characters",
            f"{len(content)} characters"
        )

    if role == "assistant" and len(content) > MAX_ASSISTANT_MESSAGE_LENGTH * 2:  # 16KB hard limit
        raise TaskValidationError(
            f"conversation_history[{i}].content",
            f"Assistant message exceeds hard limit of {MAX_ASSISTANT_MESSAGE_LENGTH * 2} characters",
            f"{len(content)} characters"
        )
```

---

## 2. VALIDATION WARNINGS (Non-Fatal)

### Warning 1: Too Many Messages (Auto-Truncate)
```python
if len(conversation_history) > MAX_MESSAGES:
    warnings.append(TaskValidationWarning(
        "conversation_history",
        f"Too many messages ({len(conversation_history)} > {MAX_MESSAGES}). "
        f"Will keep only the last {MAX_MESSAGES} messages to preserve recent context."
    ))
    # Truncate to last MAX_MESSAGES
    conversation_history = conversation_history[-MAX_MESSAGES:]
```

### Warning 2: Missing Timestamp (Auto-Add)
```python
for i, msg in enumerate(conversation_history):
    if "timestamp" not in msg or not msg["timestamp"]:
        current_time = datetime.now().isoformat()
        msg["timestamp"] = current_time
        warnings.append(TaskValidationWarning(
            f"conversation_history[{i}].timestamp",
            f"Missing timestamp - added current time: {current_time}"
        ))
```

### Warning 3: Invalid Timestamp Format (Auto-Fix)
```python
for i, msg in enumerate(conversation_history):
    timestamp = msg.get("timestamp", "")
    try:
        # Validate ISO 8601 format
        datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        current_time = datetime.now().isoformat()
        msg["timestamp"] = current_time
        warnings.append(TaskValidationWarning(
            f"conversation_history[{i}].timestamp",
            f"Invalid timestamp format '{timestamp}' - replaced with current time"
        ))
```

### Warning 4: Empty Content (Skip Message)
```python
messages_to_keep = []
for i, msg in enumerate(conversation_history):
    content = msg.get("content", "").strip()
    if not content:
        warnings.append(TaskValidationWarning(
            f"conversation_history[{i}].content",
            "Empty message content - message will be skipped"
        ))
        continue
    messages_to_keep.append(msg)
conversation_history = messages_to_keep
```

### Warning 5: Excessively Long Message (Auto-Truncate)
```python
for i, msg in enumerate(conversation_history):
    content = msg.get("content", "")
    role = msg.get("role", "").strip().lower()

    if role == "user" and len(content) > MAX_USER_MESSAGE_LENGTH:
        truncated = content[:MAX_USER_MESSAGE_LENGTH] + "... [truncated]"
        msg["content"] = truncated
        warnings.append(TaskValidationWarning(
            f"conversation_history[{i}].content",
            f"User message truncated from {len(content)} to {len(truncated)} characters"
        ))

    if role == "assistant" and len(content) > MAX_ASSISTANT_MESSAGE_LENGTH:
        truncated = content[:MAX_ASSISTANT_MESSAGE_LENGTH] + "... [truncated]"
        msg["content"] = truncated
        warnings.append(TaskValidationWarning(
            f"conversation_history[{i}].content",
            f"Assistant message truncated from {len(content)} to {len(truncated)} characters"
        ))
```

### Warning 6: Empty History After Filtering
```python
if conversation_history is not None and len(conversation_history) == 0:
    warnings.append(TaskValidationWarning(
        "conversation_history",
        "All messages were filtered out due to validation issues. History will be omitted."
    ))
    conversation_history = None
```

---

## 3. AUTO-TRUNCATION LOGIC

### Phase 1: Per-Message Truncation
Applied during validation (see Warning 5 above):
- User messages: truncate to 150 chars + "... [truncated]"
- Assistant messages: truncate to 8KB + "... [truncated]"

### Phase 2: Total Size Check
After per-message truncation, check total size:

```python
def calculate_history_size(messages: List[Dict[str, str]]) -> int:
    """Calculate approximate size in characters"""
    total = 0
    for msg in messages:
        total += len(msg.get("content", ""))
        total += len(msg.get("role", ""))
        total += len(msg.get("timestamp", ""))
        total += 10  # Overhead for JSON structure
    return total

total_size = calculate_history_size(conversation_history)

if total_size > MAX_TOTAL_HISTORY_SIZE:
    # Need to drop messages from the beginning
    warnings.append(TaskValidationWarning(
        "conversation_history",
        f"Total history size ({total_size} chars) exceeds limit ({MAX_TOTAL_HISTORY_SIZE} chars). "
        "Dropping oldest messages to fit within limit."
    ))

    # Keep dropping oldest messages until size fits
    while total_size > MAX_TOTAL_HISTORY_SIZE and len(conversation_history) > 5:
        conversation_history.pop(0)  # Remove oldest
        total_size = calculate_history_size(conversation_history)

    # Add indicator at the beginning
    if len(conversation_history) > 0:
        first_msg = conversation_history[0]
        first_msg["content"] = "... (earlier messages omitted for brevity)\n\n" + first_msg["content"]
```

### Phase 3: Minimum Context Preservation
Ensure at least the most recent exchange is preserved:

```python
MIN_MESSAGES_TO_KEEP = 5  # Always keep at least 5 most recent messages

if len(conversation_history) < MIN_MESSAGES_TO_KEEP:
    # We have few enough messages - keep all
    pass
```

---

## 4. VALIDATION FUNCTION PSEUDO-CODE

### Complete Validation Flow

```python
def validate_conversation_history(
    conversation_history: Optional[List[Dict[str, str]]],
    warnings: List[TaskValidationWarning]
) -> Optional[List[Dict[str, str]]]:
    """
    Validate and clean conversation_history parameter.

    Returns:
        Cleaned conversation_history or None if invalid/empty
        Appends warnings to warnings list
    """
    # Early return if None
    if conversation_history is None:
        return None

    # CRITICAL CHECK 1: Type validation
    if not isinstance(conversation_history, list):
        raise TaskValidationError(
            "conversation_history",
            "Must be a list of message dictionaries",
            type(conversation_history).__name__
        )

    # WARNING 1: Too many messages - truncate to last MAX_MESSAGES
    if len(conversation_history) > MAX_MESSAGES:
        warnings.append(TaskValidationWarning(
            "conversation_history",
            f"Too many messages ({len(conversation_history)} > {MAX_MESSAGES}). "
            f"Keeping only the last {MAX_MESSAGES} messages."
        ))
        conversation_history = conversation_history[-MAX_MESSAGES:]

    # Process each message
    validated_messages = []

    for i, msg in enumerate(conversation_history):
        # CRITICAL CHECK 2: Message must be dict
        if not isinstance(msg, dict):
            raise TaskValidationError(
                f"conversation_history[{i}]",
                "Each message must be a dictionary",
                type(msg).__name__
            )

        # CRITICAL CHECK 3: Required fields
        missing_fields = []
        if "role" not in msg:
            missing_fields.append("role")
        if "content" not in msg:
            missing_fields.append("content")

        if missing_fields:
            raise TaskValidationError(
                f"conversation_history[{i}]",
                f"Missing required fields: {', '.join(missing_fields)}",
                list(msg.keys())
            )

        # Normalize and validate role
        role = msg["role"].strip().lower()

        # CRITICAL CHECK 4: Valid role
        if role not in VALID_ROLES:
            raise TaskValidationError(
                f"conversation_history[{i}].role",
                f"Role must be one of {VALID_ROLES}, got '{role}'",
                role
            )

        msg["role"] = role  # Store normalized

        # Get and clean content
        content = msg["content"].strip()

        # WARNING 4: Skip empty messages
        if not content:
            warnings.append(TaskValidationWarning(
                f"conversation_history[{i}].content",
                "Empty message content - message will be skipped"
            ))
            continue

        # CRITICAL CHECK 5: Hard content length limits
        hard_limit = MAX_USER_MESSAGE_LENGTH * 2 if role == "user" else MAX_ASSISTANT_MESSAGE_LENGTH * 2
        if len(content) > hard_limit:
            raise TaskValidationError(
                f"conversation_history[{i}].content",
                f"Message exceeds hard limit of {hard_limit} characters",
                f"{len(content)} characters"
            )

        # WARNING 5: Truncate long messages
        soft_limit = MAX_USER_MESSAGE_LENGTH if role == "user" else MAX_ASSISTANT_MESSAGE_LENGTH
        if len(content) > soft_limit:
            original_length = len(content)
            content = content[:soft_limit] + "... [truncated]"
            msg["content"] = content
            warnings.append(TaskValidationWarning(
                f"conversation_history[{i}].content",
                f"Message truncated from {original_length} to {len(content)} characters"
            ))
        else:
            msg["content"] = content

        # WARNING 2 & 3: Validate/fix timestamp
        timestamp = msg.get("timestamp", "")
        if not timestamp:
            timestamp = datetime.now().isoformat()
            msg["timestamp"] = timestamp
            warnings.append(TaskValidationWarning(
                f"conversation_history[{i}].timestamp",
                f"Missing timestamp - added current time: {timestamp}"
            ))
        else:
            try:
                datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                msg["timestamp"] = timestamp
            except (ValueError, AttributeError):
                new_timestamp = datetime.now().isoformat()
                msg["timestamp"] = new_timestamp
                warnings.append(TaskValidationWarning(
                    f"conversation_history[{i}].timestamp",
                    f"Invalid timestamp format '{timestamp}' - replaced with current time"
                ))

        validated_messages.append(msg)

    # WARNING 6: Check if all messages were filtered out
    if len(validated_messages) == 0:
        warnings.append(TaskValidationWarning(
            "conversation_history",
            "All messages were filtered out due to validation issues. History will be omitted."
        ))
        return None

    conversation_history = validated_messages

    # PHASE 2: Total size truncation
    total_size = calculate_history_size(conversation_history)

    if total_size > MAX_TOTAL_HISTORY_SIZE:
        original_count = len(conversation_history)

        # Drop oldest messages until we fit
        while total_size > MAX_TOTAL_HISTORY_SIZE and len(conversation_history) > 5:
            conversation_history.pop(0)
            total_size = calculate_history_size(conversation_history)

        # Add truncation indicator
        if len(conversation_history) > 0:
            conversation_history[0]["content"] = (
                "... (earlier messages omitted for brevity)\n\n" +
                conversation_history[0]["content"]
            )

        warnings.append(TaskValidationWarning(
            "conversation_history",
            f"Total history size exceeded limit. Kept last {len(conversation_history)} of {original_count} messages."
        ))

    return conversation_history


def calculate_history_size(messages: List[Dict[str, str]]) -> int:
    """Calculate approximate size of conversation history in characters"""
    total = 0
    for msg in messages:
        total += len(msg.get("content", ""))
        total += len(msg.get("role", ""))
        total += len(msg.get("timestamp", ""))
        total += 10  # JSON overhead
    return total
```

---

## 5. INTEGRATION INTO validate_task_parameters()

### Location: After line 1650 in real_mcp_server.py

```python
# Validate conversation_history (NEW)
if conversation_history is not None:
    conversation_history = validate_conversation_history(
        conversation_history,
        warnings
    )
    if conversation_history is not None:
        validated['conversation_history'] = conversation_history
```

---

## 6. VALIDATION SUMMARY

### Critical Errors (TaskValidationError - Fatal)
1. conversation_history is not a list
2. Message is not a dictionary
3. Missing required fields (role, content)
4. Invalid role (not "user" or "assistant")
5. Message exceeds hard length limits (300 chars user, 16KB assistant)

### Warnings (TaskValidationWarning - Non-Fatal, Auto-Fixed)
1. Too many messages (>50) → Truncate to last 50
2. Missing timestamp → Add current time
3. Invalid timestamp format → Replace with current time
4. Empty content → Skip message
5. Long message → Truncate with indicator
6. All messages filtered → Return None
7. Total size too large → Drop oldest messages

### Auto-Truncation Strategy
1. **Per-message limits:** 150 chars (user), 8KB (assistant)
2. **Total history limit:** 15KB
3. **Message count limit:** 50 messages
4. **Minimum preserved:** Last 5 messages always kept
5. **Truncation indicator:** "... [truncated]" or "... (earlier messages omitted for brevity)"

---

## 7. TESTING CONSIDERATIONS

### Test Cases Required
1. Valid conversation history with all fields
2. History with missing timestamps (auto-fix)
3. History with invalid timestamps (auto-fix)
4. History with too many messages (>50)
5. History with excessively long user message
6. History with excessively long assistant message
7. History exceeding 15KB total
8. History with invalid roles
9. History with missing required fields
10. History with empty messages
11. Edge case: Single very long message
12. Edge case: Empty list
13. Edge case: None value
14. Edge case: All messages invalid (should return None)

---

## 8. CONFIGURATION TUNABILITY

All limits are defined as module-level constants for easy adjustment:

```python
# Configuration constants (top of file)
CONVERSATION_HISTORY_MAX_MESSAGES = 50
CONVERSATION_HISTORY_MAX_USER_CHARS = 150
CONVERSATION_HISTORY_MAX_ASSISTANT_CHARS = 8192
CONVERSATION_HISTORY_MAX_TOTAL_SIZE = 15360
CONVERSATION_HISTORY_MIN_KEEP = 5
CONVERSATION_HISTORY_VALID_ROLES = {"user", "assistant"}
```

Future enhancement: Move to configuration file or environment variables.

---

## DELIVERABLE COMPLETE

**File:** CONVERSATION_HISTORY_VALIDATION.md
**Location:** /Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/.agent-workspace/TASK-20251029-132543-4ca2a57f/output/

**Contents:**
- Comprehensive validation rules (5 critical checks)
- Warning types (7 non-fatal auto-fixes)
- Auto-truncation logic (3 phases)
- Complete pseudo-code for implementation
- Integration guidance
- Testing considerations
- Tunable configuration constants
