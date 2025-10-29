# Conversation History Integration Design
**Task**: Add conversation_history parameter to create_real_task and inject into agent prompts
**Date**: 2025-10-29
**Agent**: integration_designer-133032-60ff7d

---

## Executive Summary

This document specifies the complete integration of `conversation_history` parameter into the orchestrator system. The conversation history will flow from task creation → storage in task_context → formatting → injection into agent prompts, allowing agents to understand the dialogue context that led to their task.

---

## 1. PARAMETER ADDITION TO create_real_task()

### Location: `real_mcp_server.py:1656-1664`

**Current Signature:**
```python
def create_real_task(
    description: str,
    priority: str = "P2",
    client_cwd: str = None,
    background_context: Optional[str] = None,
    expected_deliverables: Optional[List[str]] = None,
    success_criteria: Optional[List[str]] = None,
    constraints: Optional[List[str]] = None,
    relevant_files: Optional[List[str]] = None
) -> Dict[str, Any]:
```

**NEW Signature:**
```python
def create_real_task(
    description: str,
    priority: str = "P2",
    client_cwd: str = None,
    background_context: Optional[str] = None,
    expected_deliverables: Optional[List[str]] = None,
    success_criteria: Optional[List[str]] = None,
    constraints: Optional[List[str]] = None,
    relevant_files: Optional[List[str]] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
```

**Change**: Add line 1665:
```python
    conversation_history: Optional[List[Dict[str, str]]] = None
```

**Docstring Addition** (after line 1677):
```python
        conversation_history: Optional list of conversation messages leading to this task.
                            Each message is a dict with 'role' (user/assistant) and 'content' keys.
```

---

## 2. VALIDATION LOGIC

### Location: After line 1777 (after relevant_files validation)

**Expected Data Structure:**
```python
conversation_history = [
    {"role": "user", "content": "Can you help me fix the authentication bug?"},
    {"role": "assistant", "content": "I'll investigate the auth system..."},
    {"role": "user", "content": "It's specifically in the JWT validation"}
]
```

**Validation Code Block:**
```python
# Validate conversation_history
if conversation_history is not None:
    if not isinstance(conversation_history, list):
        validation_warnings.append("conversation_history must be a list, ignoring invalid value")
    elif len(conversation_history) == 0:
        validation_warnings.append("conversation_history is empty, ignoring")
    else:
        # Validate each message structure
        valid_messages = []
        for i, msg in enumerate(conversation_history):
            if not isinstance(msg, dict):
                validation_warnings.append(f"conversation_history[{i}] is not a dict, skipping")
                continue
            if 'role' not in msg or 'content' not in msg:
                validation_warnings.append(f"conversation_history[{i}] missing 'role' or 'content', skipping")
                continue
            if msg['role'] not in ['user', 'assistant', 'system']:
                validation_warnings.append(f"conversation_history[{i}] has invalid role '{msg['role']}', skipping")
                continue
            if not isinstance(msg['content'], str) or len(msg['content'].strip()) == 0:
                validation_warnings.append(f"conversation_history[{i}] has empty/invalid content, skipping")
                continue

            valid_messages.append({
                'role': msg['role'],
                'content': msg['content'].strip()
            })

        if valid_messages:
            # Truncate conversation history before storing
            truncated_history = truncate_conversation_history(valid_messages)
            task_context['conversation_history'] = truncated_history
            has_enhanced_context = True
```

**Integration Point**: Insert after line 1777 (after relevant_files validation, before task_id generation at line 1779)

---

## 3. STORAGE IN task_context

### Location: Line 1820-1822 (existing pattern)

**Current Pattern:**
```python
# Add task_context to registry only if enhancement fields provided
if has_enhanced_context:
    registry['task_context'] = task_context
```

**Storage Structure:**
```python
task_context = {
    'background_context': "...",
    'expected_deliverables': [...],
    'success_criteria': [...],
    'constraints': [...],
    'relevant_files': [...],
    'conversation_history': [  # NEW FIELD
        {
            'role': 'user',
            'content': 'Can you help me fix...',
            'truncated': False
        },
        {
            'role': 'assistant',
            'content': 'I'll investigate... [8KB content truncated at 8192 chars]',
            'truncated': True
        }
    ]
}
```

**No changes required** - existing code at lines 1820-1822 will automatically store conversation_history in task_context if present.

---

## 4. TRUNCATION HELPER FUNCTION

### Location: Before create_real_task() function (suggest line 1640)

**Function Implementation:**
```python
def truncate_conversation_history(messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Truncate conversation history to prevent prompt bloat.

    Rules:
    - User messages: max 150 characters
    - Assistant messages: max 8KB (8192 characters)
    - Adds truncation indicators when content is cut

    Args:
        messages: List of message dicts with 'role' and 'content'

    Returns:
        List of truncated message dicts with 'truncated' flag
    """
    USER_MAX_CHARS = 150
    ASSISTANT_MAX_CHARS = 8192

    truncated_messages = []

    for msg in messages:
        role = msg['role']
        content = msg['content']
        truncated = False

        if role == 'user':
            if len(content) > USER_MAX_CHARS:
                content = content[:USER_MAX_CHARS] + "... [truncated]"
                truncated = True
        elif role == 'assistant':
            if len(content) > ASSISTANT_MAX_CHARS:
                content = content[:ASSISTANT_MAX_CHARS] + f"... [truncated at {ASSISTANT_MAX_CHARS} chars]"
                truncated = True
        # system messages not truncated (rare and usually short)

        truncated_messages.append({
            'role': role,
            'content': content,
            'truncated': truncated
        })

    return truncated_messages
```

**Purpose**:
- Prevents massive prompts from long conversations
- User messages keep essence (150 chars sufficient for context)
- Assistant messages preserve detail (8KB allows substantial content)
- Transparent truncation indicators

---

## 5. FORMATTING IN format_task_enrichment_prompt()

### Location: `real_mcp_server.py:740-816`

**Current Structure:**
```python
def format_task_enrichment_prompt(task_registry: Dict[str, Any]) -> str:
    task_context = task_registry.get('task_context', {})
    if not task_context:
        return ""

    sections = []

    # Background context (line 758-762)
    # Expected deliverables (line 765-770)
    # Success criteria (line 773-778)
    # Constraints (line 781-786)
    # Relevant files (line 789-796)
    # Related documentation (line 799-804)

    if sections:
        return formatted_output
    return ""
```

**NEW Section** (insert after line 804, before final `if sections:`):

```python
    # Conversation history that led to this task
    if conv_history := task_context.get('conversation_history'):
        # Build conversation display
        conv_lines = []
        for i, msg in enumerate(conv_history, 1):
            role_emoji = "👤" if msg['role'] == 'user' else "🤖"
            role_label = msg['role'].upper()
            content = msg['content']

            # Add truncation indicator if present
            truncation_note = " [TRUNCATED]" if msg.get('truncated') else ""

            conv_lines.append(f"{i}. {role_emoji} {role_label}{truncation_note}:")
            conv_lines.append(f"   {content}")
            conv_lines.append("")  # blank line for readability

        conversation_text = '\n'.join(conv_lines)
        sections.append(f"""
💬 CONVERSATION HISTORY (Context leading to this task):
{conversation_text}
""")
```

**Explanation:**
- Emoji indicators (👤 user, 🤖 assistant) for quick scanning
- Numbered messages for easy reference
- Truncation markers when content was cut
- Blank lines between messages for readability
- Indented content for visual hierarchy

**Example Output:**
```
💬 CONVERSATION HISTORY (Context leading to this task):
1. 👤 USER:
   Can you help me fix the authentication bug in the login system?

2. 🤖 ASSISTANT:
   I'll investigate the authentication system. Let me check the JWT validation... [TRUNCATED]

3. 👤 USER:
   It's specifically in the token refresh endpoint. Users report 401 errors... [truncated]

```

---

## 6. INJECTION INTO AGENT PROMPTS

### Location: `real_mcp_server.py:1982`

**Current Injection:**
```python
📝 YOUR MISSION:
{prompt}
{enrichment_prompt}
{context_prompt}
```

**How It Works:**
- `enrichment_prompt` is generated by `format_task_enrichment_prompt(task_registry)` at line 1948
- If task_context contains conversation_history, the new section will be included automatically
- No changes required to line 1982 - it already injects the enrichment_prompt

**Agent Will Receive:**
```
📝 YOUR MISSION:
You are the authentication bug investigator.

CONTEXT: Users report 401 errors during token refresh.

YOUR MISSION:
1. Investigate JWT token refresh endpoint
2. Check validation logic
3. Identify why valid tokens are rejected

DELIVERABLES:
- Root cause analysis document
- Proposed fix with code snippets

================================================================================
🎯 TASK CONTEXT (Provided by task creator)
================================================================================

📋 BACKGROUND CONTEXT:
Recent deployment broke token refresh. OAuth2 flow seems affected.

💬 CONVERSATION HISTORY (Context leading to this task):
1. 👤 USER:
   Can you help me fix the authentication bug in the login system?

2. 🤖 ASSISTANT:
   I'll investigate the authentication system. Let me check the JWT validation... [TRUNCATED]

3. 👤 USER:
   It's specifically in the token refresh endpoint. Users report 401 errors... [truncated]

================================================================================

🏗️ PROJECT CONTEXT (Source: config_files):
- Language: Python
- Frameworks: FastAPI
...
```

---

## 7. GLOBAL REGISTRY TRACKING

### Location: `real_mcp_server.py:1841-1844`

**Current Pattern:**
```python
if has_enhanced_context:
    global_reg['tasks'][task_id]['deliverables_count'] = len(task_context.get('expected_deliverables', []))
    global_reg['tasks'][task_id]['success_criteria_count'] = len(task_context.get('success_criteria', []))
```

**ADD after line 1844:**
```python
    global_reg['tasks'][task_id]['conversation_messages_count'] = len(task_context.get('conversation_history', []))
```

**Purpose**: Track how many conversation messages are attached to each task for analytics.

---

## 8. RETURN VALUE ENHANCEMENT

### Location: `real_mcp_server.py:1865` (after "if has_enhanced_context:")

**Current Pattern:**
```python
if has_enhanced_context:
    # Include task_context fields in response if provided
    ...
```

**ADD to return value** (suggest after existing task_context field inclusions):
```python
    if 'conversation_history' in task_context:
        result['conversation_messages_count'] = len(task_context['conversation_history'])
```

**Purpose**: Let caller know how many conversation messages were stored (after validation/truncation).

---

## 9. FASTMCP SCHEMA EXPOSURE

### Location: `real_mcp_server.py:1655` (@mcp.tool decorator)

**Current:**
```python
@mcp.tool
def create_real_task(...):
```

**No Changes Required**: FastMCP automatically introspects function signature and exposes all parameters in the MCP tool schema. Once `conversation_history` parameter is added to function signature, it will be automatically exposed as:

```json
{
  "conversation_history": {
    "type": "array",
    "items": {
      "type": "object",
      "properties": {
        "role": {"type": "string"},
        "content": {"type": "string"}
      }
    },
    "nullable": true
  }
}
```

---

## 10. TESTING STRATEGY

### Test File: `test_conversation_history_integration.py`

**Test Cases:**
```python
def test_conversation_history_valid():
    """Test valid conversation history is accepted and stored"""
    result = create_real_task.fn(
        description="Test task",
        conversation_history=[
            {"role": "user", "content": "Help me"},
            {"role": "assistant", "content": "Sure, I'll help"}
        ]
    )
    assert result['has_enhanced_context'] == True
    assert result.get('conversation_messages_count') == 2

def test_conversation_history_truncation_user():
    """Test user messages truncated at 150 chars"""
    long_content = "x" * 200
    result = create_real_task.fn(
        description="Test task",
        conversation_history=[
            {"role": "user", "content": long_content}
        ]
    )
    # Read task_context from registry to verify truncation
    registry = load_task_registry(result['task_id'])
    stored_msg = registry['task_context']['conversation_history'][0]
    assert len(stored_msg['content']) <= 154  # 150 + "... [truncated]"
    assert stored_msg['truncated'] == True

def test_conversation_history_truncation_assistant():
    """Test assistant messages truncated at 8KB"""
    long_content = "x" * 10000
    result = create_real_task.fn(
        description="Test task",
        conversation_history=[
            {"role": "assistant", "content": long_content}
        ]
    )
    registry = load_task_registry(result['task_id'])
    stored_msg = registry['task_context']['conversation_history'][0]
    assert len(stored_msg['content']) <= 8220  # 8192 + truncation message
    assert stored_msg['truncated'] == True

def test_conversation_history_invalid_structure():
    """Test invalid messages are filtered with warnings"""
    result = create_real_task.fn(
        description="Test task",
        conversation_history=[
            {"role": "user", "content": "Valid message"},
            {"invalid": "structure"},  # Missing role/content
            {"role": "user", "content": ""},  # Empty content
            {"role": "invalid_role", "content": "test"}  # Invalid role
        ]
    )
    assert 'validation_warnings' in result
    assert len(result['validation_warnings']) >= 3
    # Only 1 valid message should be stored
    registry = load_task_registry(result['task_id'])
    assert len(registry['task_context']['conversation_history']) == 1

def test_conversation_history_in_agent_prompt():
    """Test conversation history appears in agent prompt"""
    result = create_real_task.fn(
        description="Test task",
        conversation_history=[
            {"role": "user", "content": "Help me fix bug"},
            {"role": "assistant", "content": "I'll investigate"}
        ]
    )

    agent_result = deploy_headless_agent.fn(
        task_id=result['task_id'],
        agent_type="investigator",
        prompt="Test mission",
        parent="orchestrator"
    )

    # Read the agent's prompt file
    prompt_path = f"{result['workspace']}/agents/{agent_result['agent_id']}/prompt.txt"
    with open(prompt_path) as f:
        agent_prompt = f.read()

    assert "💬 CONVERSATION HISTORY" in agent_prompt
    assert "👤 USER:" in agent_prompt
    assert "Help me fix bug" in agent_prompt
    assert "🤖 ASSISTANT:" in agent_prompt
    assert "I'll investigate" in agent_prompt
```

---

## 11. IMPLEMENTATION CHECKLIST

### Phase 1: Core Integration
- [ ] Add `conversation_history` parameter to `create_real_task()` signature (line 1665)
- [ ] Add docstring for new parameter (after line 1677)
- [ ] Implement `truncate_conversation_history()` helper function (before line 1656)
- [ ] Add validation logic for conversation_history (after line 1777)
- [ ] Add conversation_history formatting in `format_task_enrichment_prompt()` (after line 804)

### Phase 2: Tracking & Analytics
- [ ] Add conversation_messages_count to global registry (after line 1844)
- [ ] Add conversation_messages_count to return value (in has_enhanced_context block)

### Phase 3: Testing
- [ ] Create `test_conversation_history_integration.py`
- [ ] Implement all 5 test cases
- [ ] Run pytest and verify all tests pass
- [ ] Test with real agent deployment

### Phase 4: Documentation
- [ ] Update MCP tool documentation (if separate docs exist)
- [ ] Add usage examples to README
- [ ] Document conversation_history parameter in API reference

---

## 12. EDGE CASES & ERROR HANDLING

### Empty Conversation
- **Input**: `conversation_history=[]`
- **Behavior**: Validation warning added, field ignored, has_enhanced_context remains False

### All Invalid Messages
- **Input**: All messages fail validation (wrong structure, empty content, etc.)
- **Behavior**: Validation warnings for each message, no valid messages stored, has_enhanced_context remains False

### Mixed Valid/Invalid
- **Input**: Some valid, some invalid messages
- **Behavior**: Invalid messages filtered with warnings, valid messages stored and truncated

### Very Long Conversation
- **Input**: 100+ messages
- **Behavior**: All messages processed and truncated. Consider adding a hard limit (e.g., max 50 messages) if prompt size becomes an issue

### Unicode & Special Characters
- **Input**: Messages with emojis, Chinese characters, code blocks
- **Behavior**: Preserved as-is. Truncation works correctly with UTF-8 character counting

### Null/None Messages
- **Input**: `conversation_history=[None, {...}, None]`
- **Behavior**: None entries filtered with validation warnings

---

## 13. PERFORMANCE CONSIDERATIONS

### Truncation Performance
- **Cost**: O(n) where n = number of messages
- **Impact**: Negligible - even 100 messages process in <1ms

### Storage Size
- **Before truncation**: Could be MBs for long conversations
- **After truncation**: Max ~8KB per assistant message, 150 chars per user message
- **Typical task**: ~5 messages × 2KB avg = ~10KB overhead (acceptable)

### Prompt Size Impact
- **Agent prompt base**: ~5KB
- **With conversation history**: ~5KB + 10KB conversation = ~15KB (well within Claude's limits)
- **Risk**: Low - truncation ensures bounded growth

---

## 14. FUTURE ENHANCEMENTS

### Smart Truncation (Future)
- Summarize middle messages, preserve first/last
- Extract key information (file paths, function names) before truncating
- Use Claude API to summarize long assistant responses

### Conversation Threading (Future)
- Support multi-turn task refinement
- Agent could request conversation history from parent tasks
- Build conversation graphs for complex orchestrations

### Analytics (Future)
- Track correlation between conversation length and task success
- Identify common conversation patterns
- Optimize truncation limits based on actual usage

---

## 15. SUMMARY OF CODE CHANGES

| File | Lines | Change Type | Description |
|------|-------|-------------|-------------|
| `real_mcp_server.py` | 1640 | Addition | `truncate_conversation_history()` helper function (~50 lines) |
| `real_mcp_server.py` | 1665 | Addition | Add `conversation_history` parameter |
| `real_mcp_server.py` | 1678 | Addition | Add docstring for parameter |
| `real_mcp_server.py` | 1778-1810 | Addition | Validation logic block (~32 lines) |
| `real_mcp_server.py` | 805-825 | Addition | Formatting section in `format_task_enrichment_prompt()` (~20 lines) |
| `real_mcp_server.py` | 1845 | Addition | Global registry conversation count tracking |
| `real_mcp_server.py` | 1866 | Addition | Return value enhancement |
| `test_conversation_history_integration.py` | NEW | Addition | Test suite (~150 lines) |

**Total Impact**: ~250 lines added, 0 lines modified, 0 lines removed (purely additive)

---

## 16. DEPLOYMENT INSTRUCTIONS

### Step 1: Implement Core Changes
```bash
# Edit real_mcp_server.py with all changes from sections 1-5
# Verify syntax: python3 -m py_compile real_mcp_server.py
```

### Step 2: Implement Tracking
```bash
# Add global registry and return value enhancements (sections 6-7)
```

### Step 3: Write Tests
```bash
# Create test file
# Run: pytest test_conversation_history_integration.py -v
```

### Step 4: Manual Testing
```bash
# Start MCP server
# Use MCP inspector or client to test create_real_task with conversation_history
# Deploy agent and verify conversation appears in prompt
```

### Step 5: Restart MCP Server
```bash
# Restart to reload modified code
# Verify FastMCP exposes new parameter in schema
```

---

**END OF SPECIFICATION**

This document provides complete implementation guidance for adding conversation_history support to the orchestrator system. All line numbers, code snippets, and integration points are precisely specified.
