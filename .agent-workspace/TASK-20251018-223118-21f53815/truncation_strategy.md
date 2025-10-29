# JSONL Log Truncation Strategy

**Author:** truncation_strategy_designer-223212-36569a
**Date:** 2025-10-18
**Task:** TASK-20251018-223118-21f53815

## Executive Summary

This document defines a comprehensive truncation strategy for JSONL agent logs to prevent excessive bloat from file reads and large tool outputs. The strategy balances storage efficiency with debuggability, specifically optimized for the orchestrator's use case of monitoring agent progress rather than reviewing full file contents.

**Key Finding:** 93% of bloat comes from `tool_result` content fields in `user` message types, particularly from Read tool operations logging entire file contents (observed: 36KB content in 39KB line).

---

## 1. TRUNCATION LIMITS

### 1.1 Recommended Line Length Limits

```python
# Per-line truncation limits
MAX_LINE_LENGTH = 8192  # 8KB per JSONL line (configurable)
HARD_LIMIT = 16384      # 16KB absolute maximum (safety)

# Field-specific limits
MAX_TOOL_RESULT_CONTENT = 2048    # 2KB for tool_result.content
MAX_ASSISTANT_TEXT = 4096         # 4KB for assistant text messages
MAX_SYSTEM_MESSAGE = 1024         # 1KB for system messages
```

**Rationale:**
- **8KB default**: Allows ~200 lines of code context (40 chars/line avg) while preventing massive file dumps
- **16KB hard limit**: Safety backstop for edge cases
- **Tool result 2KB**: Enough for error messages, short outputs, file previews (50 lines of code)
- **Assistant 4KB**: Reasoning/explanations should be concise, not essays
- **System 1KB**: Init messages and metadata are naturally small

### 1.2 Log File Size Limits

```python
# Total log file size management
MAX_LOG_SIZE_BEFORE_ROTATION = 10 * 1024 * 1024  # 10MB
ROTATE_TO_SIZE = 5 * 1024 * 1024                 # Keep 5MB after rotation

# OR use line count rotation
MAX_LOG_LINES = 50000  # ~400KB avg if all truncated
```

**Recommendation:** Implement line-based truncation FIRST (this strategy), then add rotation LATER if still needed.

---

## 2. WHERE TO TRUNCATE

### Option Analysis

| Option | Location | Pros | Cons | Verdict |
|--------|----------|------|------|---------|
| **A** | Write-time (modify tee pipe) | Real-time, no post-processing | Complex pipe replacement, harder to debug raw output | ❌ REJECT |
| **B** | Read-time (in get_agent_output) | Simple, backward compatible, preserves raw logs | Repeated processing overhead | ✅ **RECOMMENDED** |
| **C** | Post-process (periodic cron/daemon) | Clean separation, can reprocess | Lag time, complexity, resource overhead | ❌ REJECT |
| **D** | Hybrid (truncate on write + safety on read) | Belt-and-suspenders | Most complex, duplicate logic | ❌ OVERKILL |

### 2.1 RECOMMENDED: Read-Time Truncation (Option B)

**Implementation Point:** `get_agent_output()` function in `real_mcp_server.py:2109`

**Why Read-Time is Optimal:**

1. **Preserves Raw Data**: Full logs remain on disk for deep debugging if needed
2. **Backward Compatible**: Existing logs work unchanged
3. **Simple Implementation**: Add truncation helper in existing parsing flow
4. **Configurable**: Different consumers can request different truncation levels
5. **Coordinates with Impact Assessor Finding**: Doesn't interfere with tee pipe at line 1666

**Trade-off Accepted:** Small performance cost on each `get_agent_output()` call (mitigated by efficient implementation).

---

## 3. WHAT TO TRUNCATE

### 3.1 Message Type Truncation Rules

```python
TRUNCATION_RULES = {
    # Type: (should_truncate, max_content_length, preserve_fields)

    "system": {
        "truncate": False,  # Keep full - init messages are small, valuable
        "max_length": None,
        "preserve": ["*"]
    },

    "assistant": {
        "truncate": True,
        "max_length": MAX_ASSISTANT_TEXT,  # 4KB
        "preserve": ["type", "stop_reason", "usage"],  # Keep metadata
        "truncate_fields": ["content.text"],  # Truncate long reasoning
        "never_truncate_if": "content.tool_use"  # Keep tool calls intact
    },

    "user": {
        "truncate": True,
        "max_length": MAX_TOOL_RESULT_CONTENT,  # 2KB
        "preserve": ["type", "role"],
        "truncate_fields": ["content[].content"],  # tool_result.content is the bloat
        "keep_intact_fields": [
            "content[].type",
            "content[].tool_use_id",
            "content[].is_error",
            "message.model",
            "message.id"
        ]
    },

    "error": {
        "truncate": False,  # NEVER truncate errors!
        "max_length": None,
        "preserve": ["*"]
    },

    "tool_result": {  # Special handling for tool_result content blocks
        "truncate": True,
        "max_length": MAX_TOOL_RESULT_CONTENT,  # 2KB
        "strategy": "smart_preview",  # Use intelligent preview (see 4.3)
        "preserve_error_messages": True
    }
}
```

### 3.2 Priority: NEVER Truncate These

```python
NEVER_TRUNCATE = [
    "error",                    # Error messages: CRITICAL
    "message.usage",            # Token usage: needed for cost tracking
    "message.stop_reason",      # Completion status: needed for debugging
    "message.id",               # Message ID: needed for correlation
    "content.tool_use_id",      # Tool correlation: needed for tracing
    "content.is_error",         # Error flag: CRITICAL
    "content.type",             # Type field: needed for parsing
    "system.subtype == 'init'"  # Init messages: valuable context
]
```

### 3.3 Aggressive Truncation Targets

```python
AGGRESSIVE_TRUNCATION = {
    # These get truncated heavily (10:1 ratio)
    "tool_result.content": {
        "triggers": [
            "file_contents",     # Read tool results
            "directory_listing", # Glob/ls results
            "search_results"     # Grep results with context
        ],
        "max_length": 2048,  # 2KB max
        "strategy": "smart_preview"
    },

    # Long assistant reasoning (rare but possible)
    "assistant.content.text": {
        "max_length": 4096,  # 4KB max
        "strategy": "simple_truncate"
    }
}
```

---

## 4. HOW TO TRUNCATE

### 4.1 Simple Truncation (baseline)

```python
def simple_truncate(text: str, max_length: int) -> str:
    """
    Simple character-based truncation with marker.
    Use for: assistant text, simple strings.
    """
    if len(text) <= max_length:
        return text

    marker = "\n\n[... TRUNCATED: {removed} chars removed ...]"
    removed = len(text) - max_length + len(marker.format(removed=0))

    truncated = text[:max_length - len(marker.format(removed=removed))]
    return truncated + marker.format(removed=removed)
```

### 4.2 Line-Based Truncation (better)

```python
def line_based_truncate(text: str, max_length: int) -> str:
    """
    Truncate at line boundaries to preserve readability.
    Use for: code snippets, structured output.
    """
    if len(text) <= max_length:
        return text

    lines = text.split('\n')

    # Try to fit whole lines within max_length
    kept_lines = []
    current_length = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_length + line_len > max_length - 200:  # Reserve 200 for marker
            break
        kept_lines.append(line)
        current_length += line_len

    if len(kept_lines) == len(lines):
        return text  # All fit

    removed_lines = len(lines) - len(kept_lines)
    removed_chars = len(text) - current_length

    marker = f"\n\n[... TRUNCATED: {removed_lines} lines ({removed_chars} chars) removed ...]"
    return '\n'.join(kept_lines) + marker
```

### 4.3 Smart Preview (optimal for orchestrator use case)

```python
def smart_preview_truncate(text: str, max_length: int) -> str:
    """
    Intelligent preview: first N + last M lines.
    Use for: file contents, long outputs.

    CRITICAL: Optimized for orchestrator's use case:
    - Main agent doesn't need full file contents
    - Wants to see: what file, rough size, first/last lines
    - Debugging: can always read raw log if needed
    """
    if len(text) <= max_length:
        return text

    lines = text.split('\n')

    # Strategy: Keep first 30 lines + last 10 lines
    # This shows: file header/structure + recent changes
    PREVIEW_HEAD = 30
    PREVIEW_TAIL = 10

    if len(lines) <= PREVIEW_HEAD + PREVIEW_TAIL:
        return line_based_truncate(text, max_length)  # Fallback

    head_lines = lines[:PREVIEW_HEAD]
    tail_lines = lines[-PREVIEW_TAIL:]

    removed_lines = len(lines) - (PREVIEW_HEAD + PREVIEW_TAIL)

    marker = f"\n\n[... TRUNCATED: {removed_lines} middle lines removed ...]\n\n"

    preview = '\n'.join(head_lines) + marker + '\n'.join(tail_lines)

    # If preview still too long, use line-based truncation
    if len(preview) > max_length:
        return line_based_truncate(preview, max_length)

    return preview
```

### 4.4 JSON Structure Preservation

```python
def truncate_json_structure(obj: dict, max_length: int) -> dict:
    """
    Truncate while preserving JSON structure.
    Use for: nested objects that must remain valid JSON.
    """
    # Serialize to check size
    serialized = json.dumps(obj)

    if len(serialized) <= max_length:
        return obj

    # Deep copy and truncate content fields
    truncated = copy.deepcopy(obj)

    # Find and truncate the bloat
    if 'message' in truncated and 'content' in truncated['message']:
        content = truncated['message']['content']

        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'tool_result':
                    if 'content' in item and isinstance(item['content'], str):
                        item['content'] = smart_preview_truncate(
                            item['content'],
                            MAX_TOOL_RESULT_CONTENT
                        )
                        item['truncated'] = True  # Mark as truncated

        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and 'text' in item:
                    item['text'] = line_based_truncate(
                        item['text'],
                        MAX_ASSISTANT_TEXT
                    )
                    item['truncated'] = True

    return truncated
```

---

## 5. EDGE CASE HANDLING

### 5.1 Multi-line JSON Strings

**Problem:** Truncating mid-string breaks JSON parsing.

**Solution:**
```python
def safe_json_truncate(line: str, max_length: int) -> str:
    """
    Truncate JSONL line while preserving JSON validity.
    """
    if len(line) <= max_length:
        return line

    try:
        # Parse JSON
        obj = json.loads(line)

        # Truncate content fields (preserves structure)
        truncated_obj = truncate_json_structure(obj, max_length)

        # Re-serialize
        truncated_line = json.dumps(truncated_obj)

        # If still too long, aggressive truncate with error marker
        if len(truncated_line) > max_length:
            return json.dumps({
                "error": "Line too large even after truncation",
                "original_type": obj.get('type'),
                "original_size": len(line),
                "truncated_size": max_length
            })

        return truncated_line

    except json.JSONDecodeError:
        # Malformed JSON, simple truncate
        return simple_truncate(line, max_length)
```

### 5.2 Nested JSON Objects

**Problem:** tool_result.content might itself be JSON that needs parsing.

**Solution:**
```python
def smart_content_truncate(content: str, max_length: int) -> str:
    """
    Detect if content is JSON and handle appropriately.
    """
    # Try to parse as JSON
    try:
        parsed = json.loads(content)
        # It's JSON! Truncate the structure
        truncated = truncate_json_structure(parsed, max_length)
        return json.dumps(truncated)
    except:
        # Not JSON, use smart preview
        return smart_preview_truncate(content, max_length)
```

### 5.3 Binary/Base64 Data

**Problem:** Base64-encoded files (images, etc.) are massive and useless in logs.

**Solution:**
```python
import re

def detect_and_truncate_binary(content: str, max_length: int) -> str:
    """
    Aggressively truncate base64/binary data.
    """
    # Detect base64 pattern
    base64_pattern = r'^[A-Za-z0-9+/]{100,}={0,2}$'

    if re.match(base64_pattern, content[:200]):
        # Definitely base64, replace with summary
        return f"[BASE64_DATA: {len(content)} bytes, truncated]"

    # Detect binary indicators
    if any(indicator in content[:500] for indicator in ['\\x00', 'PNG\\r\\n', 'GIF89']):
        return f"[BINARY_DATA: {len(content)} bytes, truncated]"

    # Not binary, normal truncation
    return smart_preview_truncate(content, max_length)
```

### 5.4 Already Truncated Lines

**Problem:** Re-reading logs might re-truncate, losing more data.

**Solution:**
```python
def is_already_truncated(obj: dict) -> bool:
    """
    Check if object was already truncated.
    """
    # Check for truncation marker
    if obj.get('truncated') == True:
        return True

    # Check for truncation text markers
    if isinstance(obj, dict):
        for value in obj.values():
            if isinstance(value, str) and '[... TRUNCATED:' in value:
                return True

    return False

def conditional_truncate(obj: dict, max_length: int) -> dict:
    """
    Only truncate if not already truncated.
    """
    if is_already_truncated(obj):
        return obj  # Already truncated, don't touch

    return truncate_json_structure(obj, max_length)
```

### 5.5 Incomplete Lines (Agent Crashed)

**Problem:** Last line might be incomplete JSON if agent crashed mid-write.

**Solution:**
```python
def robust_jsonl_parse(line: str) -> Optional[dict]:
    """
    Parse JSONL with error handling for incomplete lines.
    """
    try:
        return json.loads(line)
    except json.JSONDecodeError as e:
        # Check if it's incomplete (missing closing brace)
        if line.rstrip().endswith(',') or not line.rstrip().endswith('}'):
            # Incomplete line, skip it
            logger.warning(f"Skipping incomplete JSONL line: {line[:100]}...")
            return None
        else:
            # Corrupt line, try to salvage
            logger.error(f"Corrupt JSONL line: {e}")
            return None
```

---

## 6. BACKWARD COMPATIBILITY

### 6.1 Old Logs Without Truncation

**Status:** ✅ Fully compatible

**Reason:** Read-time truncation processes ALL logs consistently, old or new.

**Handling:**
```python
def read_and_truncate_log(log_path: str, max_line_length: int) -> List[str]:
    """
    Read any JSONL log and apply truncation on read.
    Works for old and new logs identically.
    """
    truncated_lines = []

    with open(log_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Apply truncation to every line (old or new)
            if len(line) > max_line_length:
                truncated = safe_json_truncate(line, max_line_length)
                truncated_lines.append(truncated)
            else:
                truncated_lines.append(line)

    return truncated_lines
```

### 6.2 Fallback to tmux

**Status:** ✅ Unchanged

**Reason:** Truncation happens AFTER determining source (JSONL vs tmux). Tmux path unchanged.

---

## 7. IMPLEMENTATION PLAN

### 7.1 Files to Modify

```
real_mcp_server.py:
  - Add truncation helpers (lines ~1900-2100, before get_agent_output)
  - Modify get_agent_output to apply truncation (line 2109+)

New functions to add:
  1. simple_truncate(text, max_len) -> str
  2. line_based_truncate(text, max_len) -> str
  3. smart_preview_truncate(text, max_len) -> str
  4. truncate_json_structure(obj, max_len) -> dict
  5. safe_json_truncate(line, max_len) -> str
  6. detect_and_truncate_binary(content, max_len) -> str
  7. is_already_truncated(obj) -> bool
  8. apply_truncation_rules(parsed_obj) -> dict  [MAIN FUNCTION]
```

### 7.2 Integration Points

**Modify `get_agent_output()` at line 2202:**

```python
# BEFORE (line 2202):
output, parse_errors = format_output_by_type(lines, format)

# AFTER:
# Apply truncation rules to parsed lines BEFORE formatting
if format == "parsed":
    truncated_lines = [apply_truncation_rules(obj) for obj in lines]
else:
    # For text/jsonl format, truncate each line individually
    truncated_lines = [
        safe_json_truncate(line, MAX_LINE_LENGTH)
        if len(line) > MAX_LINE_LENGTH
        else line
        for line in lines
    ]

output, parse_errors = format_output_by_type(truncated_lines, format)
```

### 7.3 Configuration (Future Enhancement)

```python
# Add to MCP tool signature (future):
@mcp.tool()
def get_agent_output(
    task_id: str,
    agent_id: str,
    tail: Optional[int] = None,
    filter: Optional[str] = None,
    format: str = "text",
    include_metadata: bool = False,
    truncate: bool = True,              # NEW: enable/disable truncation
    max_line_length: int = 8192,        # NEW: configurable limit
    truncation_strategy: str = "smart"  # NEW: simple/line/smart
) -> Dict[str, Any]:
    ...
```

### 7.4 Implementation Order

**Phase 1: Core Truncation (MVP)**
1. Add `safe_json_truncate()` helper
2. Add `smart_preview_truncate()` helper
3. Modify `get_agent_output()` to apply truncation
4. Test with existing logs

**Phase 2: Intelligent Rules**
5. Add `truncate_json_structure()` for structure preservation
6. Add `apply_truncation_rules()` with type-specific logic
7. Test with different message types

**Phase 3: Edge Cases**
8. Add binary detection and handling
9. Add already-truncated detection
10. Add incomplete line handling

**Phase 4: Configuration**
11. Add truncation parameters to MCP tool
12. Add configuration file support
13. Add per-agent truncation settings

---

## 8. TESTING STRATEGY

### 8.1 Test Cases

```python
# Test 1: Large tool_result content (primary bloat)
test_bloat_tool_result = {
    "type": "user",
    "message": {
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_123",
                "content": "x" * 50000  # 50KB of content
            }
        ]
    }
}
# Expected: content truncated to 2KB with smart preview

# Test 2: Error message (never truncate)
test_error_message = {
    "type": "error",
    "error": "x" * 10000
}
# Expected: NO truncation

# Test 3: System init (never truncate)
test_system_init = {
    "type": "system",
    "subtype": "init",
    "tools": ["list", "of", "many", "tools"] * 100
}
# Expected: NO truncation

# Test 4: Already truncated
test_already_truncated = {
    "type": "user",
    "message": {
        "content": [
            {
                "type": "tool_result",
                "content": "some content\n\n[... TRUNCATED: 1000 chars removed ...]",
                "truncated": True
            }
        ]
    }
}
# Expected: NO re-truncation

# Test 5: Incomplete JSON line
test_incomplete = '{"type": "user", "message": {"content": ['
# Expected: Skip or handle gracefully

# Test 6: Base64 data
test_base64 = {
    "type": "user",
    "message": {
        "content": [
            {
                "type": "tool_result",
                "content": "iVBORw0KGgoAAAANSUhEUgAA..." * 1000  # Large base64
            }
        ]
    }
}
# Expected: Replace with "[BASE64_DATA: N bytes]"
```

### 8.2 Integration Test

```bash
# Test with real agent
python3 -c "
import sys
sys.path.append('.')
from real_mcp_server import get_agent_output

# Get output with truncation
result = get_agent_output.fn(
    task_id='TASK-20251017-215604-df6a3cbd',
    agent_id='simple_test_agent-212031-9d5ba0',
    format='parsed',
    include_metadata=True
)

# Verify truncation happened
assert result['success']
assert result['metadata']['largest_line_size'] <= 8192
print('✅ Truncation working!')
"
```

---

## 9. PERFORMANCE CONSIDERATIONS

### 9.1 Time Complexity

```python
# Current (no truncation):
# O(n) where n = number of lines to read

# With truncation:
# O(n * m) where:
#   n = number of lines
#   m = average processing per line (JSON parse + truncate)
#
# For typical logs:
#   n = 100-1000 lines
#   m = ~1ms per line (fast JSON ops)
# Total: ~100ms - 1s (acceptable)
```

### 9.2 Memory Considerations

```python
# Worst case memory:
# - Read full log: up to 10MB
# - Parse all lines: ~10MB in memory
# - Truncate: additional ~5MB temporary
# Total: ~25MB peak (acceptable for modern systems)

# Optimization if needed:
# - Stream processing: truncate line-by-line without loading all
# - Generator pattern: yield truncated lines
```

### 9.3 Optimization Opportunities

```python
# Future optimization: lazy truncation
def lazy_truncate_iterator(log_path: str, max_len: int):
    """
    Generator that truncates on-the-fly without loading full file.
    """
    with open(log_path, 'r') as f:
        for line in f:
            yield safe_json_truncate(line.strip(), max_len)

# Use in get_agent_output:
if tail:
    # Still need to load for tail, use current approach
    lines = list(lazy_truncate_iterator(log_path, MAX_LINE_LENGTH))
    lines = lines[-tail:]
else:
    # Stream without loading
    lines = lazy_truncate_iterator(log_path, MAX_LINE_LENGTH)
```

---

## 10. MONITORING & METRICS

### 10.1 Add Truncation Metrics to Metadata

```python
# Enhance metadata returned by get_agent_output:
response["metadata"]["truncation_stats"] = {
    "lines_truncated": 15,
    "total_lines": 100,
    "truncation_ratio": 0.15,
    "bytes_saved": 450000,
    "largest_line_before": 50000,
    "largest_line_after": 8192,
    "truncation_strategy": "smart_preview"
}
```

### 10.2 Logging Truncation Events

```python
# Add to logger when truncating:
logger.info(
    f"Truncated {count} lines in {agent_id} log "
    f"(saved {bytes_saved} bytes, {bytes_saved/total_bytes*100:.1f}%)"
)
```

---

## 11. ALTERNATIVE APPROACHES CONSIDERED

### 11.1 Streaming Truncation (Write-Time)

**Rejected because:**
- Breaks simple `tee` pipe (adds complexity)
- Loses raw data (can't debug later)
- Harder to adjust truncation rules without redeploying agents

**Could revisit if:** Performance becomes critical (profiling shows read-time is bottleneck).

### 11.2 Log Rotation

**Deferred because:**
- Truncation solves 90% of bloat (tool_result content)
- Rotation adds complexity (file management, multiple files)
- Can add rotation LATER if truncation insufficient

**Implementation note:** If rotation needed, use `logrotate` pattern:
```
agent_id_stream.jsonl        (current)
agent_id_stream.jsonl.1      (rotated)
agent_id_stream.jsonl.2.gz   (compressed old)
```

### 11.3 Compression

**Deferred because:**
- gzip compression adds CPU overhead on every read
- Doesn't help with individual line bloat (need truncation anyway)
- Can add LATER for archived logs

**Implementation note:** Compress rotated logs only:
```bash
# After rotation, compress old logs
gzip agent_id_stream.jsonl.1
```

---

## 12. ROLLOUT PLAN

### Phase 1: Implement Core (Week 1)
- [ ] Add truncation helpers to real_mcp_server.py
- [ ] Modify get_agent_output to apply truncation
- [ ] Test with existing logs
- [ ] Verify backward compatibility

### Phase 2: Deploy and Monitor (Week 2)
- [ ] Deploy to production
- [ ] Monitor truncation stats in metadata
- [ ] Collect feedback from orchestrator usage
- [ ] Adjust limits based on real-world data

### Phase 3: Optimize (Week 3)
- [ ] Add configuration options
- [ ] Implement lazy truncation if performance issues
- [ ] Add per-agent truncation settings
- [ ] Document best practices

### Phase 4: Enhancements (Future)
- [ ] Add log rotation if file sizes still grow
- [ ] Add compression for archived logs
- [ ] Add truncation dashboard/metrics
- [ ] Add smart summarization (LLM-based)

---

## 13. DECISION SUMMARY

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **When to truncate** | Read-time | Preserves raw data, backward compatible |
| **Max line length** | 8KB (configurable) | Balances context vs bloat |
| **Tool result limit** | 2KB | Enough for errors/previews, prevents file dumps |
| **Truncation strategy** | Smart preview (first 30 + last 10 lines) | Optimized for orchestrator use case |
| **Error handling** | Never truncate errors | Debugging is critical |
| **Binary data** | Aggressive truncation | Replace with size summary |
| **Already truncated** | Skip re-truncation | Prevent data loss |
| **Configuration** | Phase 4 enhancement | Start simple, add complexity later |

---

## 14. OPEN QUESTIONS FOR ORCHESTRATOR

1. **Is 2KB enough for tool_result previews?** (Can adjust if too aggressive)
2. **Should assistant reasoning be truncated at all?** (Currently 4KB limit)
3. **Do we need configurable truncation per agent type?** (Investigator vs Builder)
4. **Should orchestrator see truncation warnings in output?** (Currently in metadata only)

---

## 15. REFERENCES

- `real_mcp_server.py:1666` - tee pipe deployment
- `real_mcp_server.py:2109` - get_agent_output function
- `.agent-workspace/TASK-20251017-215604-df6a3cbd/logs/simple_test_agent-212031-9d5ba0_stream.jsonl` - Example bloated log
- Coordination findings from `truncation_impact_assessor-223214-70876b` and `output_bloat_analyzer-223210-7523c1`

---

**DELIVERABLE COMPLETE**

This strategy provides:
✅ Clear limits (8KB line, 2KB tool_result)
✅ WHERE to implement (read-time in get_agent_output)
✅ WHAT to truncate (tool_result.content, assistant text)
✅ HOW to truncate (smart preview algorithm + pseudocode)
✅ Edge case handling (binary, JSON, incomplete lines)
✅ Implementation plan (4 phases, file locations, integration points)

**Ready for implementation by builder agents.**
