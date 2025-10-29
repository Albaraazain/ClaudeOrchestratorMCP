# Enhanced get_agent_output API Design

## Current Implementation Analysis

**Location:** `real_mcp_server.py:1636-1697`

**Current Signature:**
```python
@mcp.tool
def get_agent_output(task_id: str, agent_id: str) -> Dict[str, Any]
```

**Current Behavior:**
- Reads output directly from tmux session via `tmux capture-pane`
- Returns ALL captured output (no filtering or limiting)
- No persistence - output lost when tmux session terminates
- Returns: `{success, agent_id, tmux_session, session_status, output}`

**Problems:**
1. No tail functionality - always returns full output
2. No filtering capability
3. No persistence after session ends
4. No structured format options
5. Output becomes very large over time

---

## Enhanced API Design

### Function Signature

```python
@mcp.tool
def get_agent_output(
    task_id: str,
    agent_id: str,
    tail: Optional[int] = None,
    filter: Optional[str] = None,
    format: str = "text",
    include_metadata: bool = False
) -> Dict[str, Any]:
    """
    Get agent output from persistent JSONL log file with filtering and tail support.

    Args:
        task_id: Task ID containing the agent
        agent_id: Agent ID to get output from
        tail: Number of most recent lines to return (None = all lines)
        filter: Regex pattern to filter output lines (applied before tail)
        format: Output format - "text", "jsonl", or "parsed"
        include_metadata: Include file metadata (size, line count, timestamps)

    Returns:
        Dict with output and metadata
    """
```

### Parameters Specification

#### `tail: Optional[int] = None`
- **Default:** `None` (return all lines)
- **Behavior:** Return only the last N lines from the log
- **Use Cases:**
  - `tail=10`: Get latest progress for monitoring
  - `tail=50`: Quick check of recent activity
  - `tail=None`: Get full log for debugging
- **Implementation:** Read file from end using efficient tail algorithm
- **Edge Cases:**
  - If `tail > total_lines`: Return all available lines
  - If `tail <= 0`: Return empty output with warning

#### `filter: Optional[str] = None`
- **Default:** `None` (no filtering)
- **Behavior:** Apply regex pattern to filter lines BEFORE tail
- **Use Cases:**
  - `filter="ERROR|WARN"`: Find error/warning lines
  - `filter="progress.*completed"`: Track completion progress
  - `filter="mcp__.*__update"`: Find MCP progress calls
- **Implementation:** Use Python `re.search()` on each line
- **Edge Cases:**
  - Invalid regex: Return error with helpful message
  - No matches: Return empty output with metadata showing 0 matches
- **Note:** Filter is applied BEFORE tail, so `filter="ERROR" tail=10` means "last 10 ERROR lines"

#### `format: str = "text"`
- **Options:** `"text"`, `"jsonl"`, `"parsed"`
- **Default:** `"text"`
- **Behavior:**
  - `"text"`: Return raw text output (backward compatible)
  - `"jsonl"`: Return raw JSONL lines (each line is valid JSON)
  - `"parsed"`: Parse JSONL and return array of JSON objects
- **Use Cases:**
  - `"text"`: Human-readable output, orchestrator display
  - `"jsonl"`: Streaming/appending, log processing
  - `"parsed"`: Structured analysis, extracting specific fields
- **Edge Cases:**
  - Invalid JSONL lines: In `"parsed"` mode, include parse errors in metadata
  - Non-JSONL files: `"parsed"` mode returns error

#### `include_metadata: bool = False`
- **Default:** `False` (backward compatible)
- **Behavior:** Include additional file and processing metadata
- **Metadata Fields:**
  ```python
  {
      "file_path": str,           # Full path to log file
      "file_size_bytes": int,     # File size
      "total_lines": int,         # Total lines in file
      "matched_lines": int,       # Lines matching filter (if filter applied)
      "returned_lines": int,      # Lines actually returned
      "first_timestamp": str,     # Timestamp of first line
      "last_timestamp": str,      # Timestamp of last line
      "parse_errors": List[dict], # JSONL parse errors (if format="parsed")
      "log_source": str,          # "jsonl_file" or "tmux_fallback"
  }
  ```

---

## Return Format

### Success Response

```python
{
    "success": True,
    "agent_id": str,
    "session_status": str,  # "running", "terminated", "completed"
    "output": str | List[dict],  # Depends on format parameter
    "source": str,  # "jsonl_log" or "tmux_session"
    "metadata": dict | None  # Only if include_metadata=True
}
```

### Error Response

```python
{
    "success": False,
    "error": str,
    "error_type": str,  # "task_not_found", "agent_not_found", "invalid_regex", etc.
    "agent_id": str | None
}
```

---

## Implementation Strategy

### Phase 1: Read from JSONL Log File

```python
def get_agent_output(...):
    # 1. Find task workspace
    workspace = find_task_workspace(task_id)

    # 2. Check for JSONL log file first
    log_path = f"{workspace}/logs/{agent_id}_stream.jsonl"

    if os.path.exists(log_path):
        output = read_jsonl_log(log_path, tail, filter, format)
        source = "jsonl_log"
    else:
        # 3. Fallback to tmux if log doesn't exist (backward compatibility)
        output = read_tmux_session(agent_id)
        source = "tmux_session"

    # 4. Apply format and return
    return format_response(output, source, include_metadata)
```

### Phase 2: Efficient Tail Implementation

**Challenge:** Reading last N lines from large files efficiently

**Solution:** Use reverse file reading:
```python
def read_last_n_lines(file_path: str, n: int) -> List[str]:
    """
    Read last N lines efficiently using reverse seek.
    Algorithm: Seek to end, read chunks backward until N lines found.
    """
    with open(file_path, 'rb') as f:
        # Seek to end
        f.seek(0, 2)
        file_size = f.tell()

        # Read chunks backward
        chunk_size = 4096
        lines = []
        position = file_size

        while len(lines) < n and position > 0:
            chunk_size = min(chunk_size, position)
            position -= chunk_size
            f.seek(position)
            chunk = f.read(chunk_size).decode('utf-8', errors='ignore')
            lines = chunk.split('\n') + lines

        # Return last N lines
        return lines[-n:] if len(lines) > n else lines
```

**Performance:** O(k) where k = bytes needed for N lines, NOT O(file_size)

### Phase 3: Filter Implementation

```python
def apply_filter(lines: List[str], pattern: Optional[str]) -> List[str]:
    """Apply regex filter to lines."""
    if not pattern:
        return lines

    try:
        regex = re.compile(pattern)
    except re.error as e:
        raise ValueError(f"Invalid regex pattern: {e}")

    return [line for line in lines if regex.search(line)]
```

**Note:** Filter is applied BEFORE tail for semantic correctness

### Phase 4: Format Conversion

```python
def format_output(lines: List[str], format: str) -> Union[str, List[dict]]:
    """Convert lines to requested format."""
    if format == "text":
        return '\n'.join(lines)

    elif format == "jsonl":
        return '\n'.join(lines)

    elif format == "parsed":
        parsed = []
        errors = []
        for i, line in enumerate(lines):
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError as e:
                errors.append({
                    "line_number": i,
                    "line": line[:100],  # Truncate for safety
                    "error": str(e)
                })

        # Store errors in metadata (returned if include_metadata=True)
        return parsed

    else:
        raise ValueError(f"Unknown format: {format}")
```

---

## Backward Compatibility

### Existing Callers

**Current call:**
```python
result = get_agent_output(task_id="TASK-123", agent_id="agent-456")
# Returns: {success, agent_id, tmux_session, session_status, output}
```

**After enhancement (unchanged behavior):**
```python
result = get_agent_output(task_id="TASK-123", agent_id="agent-456")
# Returns: {success, agent_id, session_status, output, source}
# output is still text format
# source indicates "jsonl_log" or "tmux_session"
```

### Migration Strategy

1. **Add new parameters with defaults** - No breaking changes
2. **Add `source` field** - Indicates log source, safe addition
3. **Keep `output` as text by default** - `format="text"` is default
4. **Deprecate `tmux_session` field** - Move to metadata
5. **Fallback to tmux if JSONL missing** - Graceful degradation

### Deprecation Path

**Current fields (keep for compatibility):**
- `success`, `agent_id`, `output`, `session_status`

**New fields:**
- `source`: "jsonl_log" | "tmux_session"
- `metadata`: (optional)

**Deprecated fields (keep for now, document as deprecated):**
- `tmux_session`: Move to `metadata.tmux_session`

---

## Use Cases & Examples

### Use Case 1: Real-time Monitoring
**Goal:** Check latest progress updates

```python
result = get_agent_output(
    task_id="TASK-123",
    agent_id="agent-456",
    tail=10,
    format="text"
)
# Returns last 10 lines as text
```

### Use Case 2: Find Errors
**Goal:** Get all error messages

```python
result = get_agent_output(
    task_id="TASK-123",
    agent_id="agent-456",
    filter="ERROR|CRITICAL",
    format="text"
)
# Returns only lines containing ERROR or CRITICAL
```

### Use Case 3: Parse MCP Progress Calls
**Goal:** Extract structured progress updates

```python
result = get_agent_output(
    task_id="TASK-123",
    agent_id="agent-456",
    filter="mcp__claude-orchestrator__update_agent_progress",
    format="parsed",
    include_metadata=True
)
# Returns: {
#   success: True,
#   output: [{"timestamp": "...", "message": "...", "progress": 50}, ...],
#   metadata: {total_lines: 1000, matched_lines: 15, ...}
# }
```

### Use Case 4: Recent Activity Check
**Goal:** Quick check of latest agent activity

```python
result = get_agent_output(
    task_id="TASK-123",
    agent_id="agent-456",
    tail=20,
    include_metadata=True
)
# Returns last 20 lines + file metadata showing total lines, timestamps
```

### Use Case 5: Full Debug Log
**Goal:** Get complete log for debugging

```python
result = get_agent_output(
    task_id="TASK-123",
    agent_id="agent-456",
    # tail=None (default) returns everything
    include_metadata=True
)
# Returns entire log with metadata
```

### Use Case 6: Streaming Recent Updates
**Goal:** Track progress of long-running agent

```python
# Poll every 30 seconds for new activity
while agent_running:
    result = get_agent_output(
        task_id="TASK-123",
        agent_id="agent-456",
        tail=50,  # Get recent activity
        include_metadata=True
    )

    # Check last_timestamp to see if new activity
    if result["metadata"]["last_timestamp"] > last_seen_timestamp:
        print(result["output"])
        last_seen_timestamp = result["metadata"]["last_timestamp"]

    time.sleep(30)
```

---

## Error Handling

### Error Types

```python
class OutputError(Exception):
    """Base class for output errors"""
    pass

class InvalidRegexError(OutputError):
    """Raised when filter regex is invalid"""
    pass

class LogFileNotFoundError(OutputError):
    """Raised when log file doesn't exist and tmux unavailable"""
    pass

class ParseError(OutputError):
    """Raised when format=parsed but JSONL is malformed"""
    pass
```

### Error Responses

```python
# Invalid regex
{
    "success": False,
    "error": "Invalid regex pattern: unbalanced parenthesis at position 5",
    "error_type": "invalid_regex",
    "agent_id": "agent-456"
}

# Agent not found
{
    "success": False,
    "error": "Agent agent-999 not found in task TASK-123",
    "error_type": "agent_not_found",
    "agent_id": "agent-999"
}

# Log unavailable
{
    "success": False,
    "error": "Agent log file not found and tmux session terminated",
    "error_type": "log_unavailable",
    "agent_id": "agent-456"
}
```

---

## Performance Considerations

### Large Files
- **Problem:** Log files can grow to 100MB+
- **Solution:**
  - Use tail efficiently (read from end)
  - Apply filter during read (don't load entire file)
  - Implement pagination if needed in future

### Filter Performance
- **Compiled Regex:** Compile regex once, reuse
- **Early Termination:** If tail + filter, stop reading when enough matches found
- **Streaming:** Process line-by-line, don't load entire file into memory

### Metadata Collection
- **Lazy Computation:** Only collect metadata if `include_metadata=True`
- **File Stats:** Use `os.stat()` for size, avoid reading file for basic stats
- **Line Counting:** Use efficient counting for total_lines

---

## Testing Strategy

### Unit Tests

```python
def test_tail_basic():
    """Test tail parameter returns correct number of lines"""
    result = get_agent_output(task_id, agent_id, tail=10)
    assert len(result["output"].split('\n')) == 10

def test_filter_regex():
    """Test filter parameter applies regex correctly"""
    result = get_agent_output(task_id, agent_id, filter="ERROR")
    for line in result["output"].split('\n'):
        assert "ERROR" in line

def test_format_parsed():
    """Test parsed format returns valid JSON objects"""
    result = get_agent_output(task_id, agent_id, format="parsed")
    assert isinstance(result["output"], list)
    for obj in result["output"]:
        assert isinstance(obj, dict)

def test_backward_compatibility():
    """Test that old API calls still work"""
    result = get_agent_output(task_id, agent_id)
    assert "success" in result
    assert "output" in result
    assert isinstance(result["output"], str)
```

### Integration Tests

```python
def test_jsonl_fallback_to_tmux():
    """Test fallback to tmux when JSONL doesn't exist"""
    # Deploy agent without JSONL logging
    result = get_agent_output(task_id, agent_id)
    assert result["source"] == "tmux_session"

def test_large_file_performance():
    """Test tail performance on large files"""
    # Create 1M line log file
    result = get_agent_output(task_id, agent_id, tail=100)
    # Should complete in < 1 second
```

---

## Documentation Updates Required

### User Documentation
1. Update API reference with new parameters
2. Add examples for common use cases
3. Document migration from old API
4. Add troubleshooting section

### Developer Documentation
1. Document JSONL log file format
2. Explain tail algorithm implementation
3. Document filter semantics
4. Add performance benchmarks

---

## Future Enhancements (Out of Scope)

### Pagination
```python
get_agent_output(
    task_id, agent_id,
    limit=100,
    offset=0  # Or cursor-based pagination
)
```

### Time-based Filtering
```python
get_agent_output(
    task_id, agent_id,
    since="2025-10-17T12:00:00Z",
    until="2025-10-17T13:00:00Z"
)
```

### Field Selection (for parsed format)
```python
get_agent_output(
    task_id, agent_id,
    format="parsed",
    fields=["timestamp", "message", "progress"]
)
```

### Aggregations
```python
get_agent_output(
    task_id, agent_id,
    aggregate="count_by_level"  # Count ERROR, WARN, INFO, etc.
)
```

---

## Summary

### Key Decisions

1. **Tail parameter**: `None` = all, `N` = last N lines
2. **Filter first, then tail**: Semantic correctness
3. **Default format is text**: Backward compatibility
4. **Fallback to tmux**: Graceful degradation
5. **Metadata is optional**: Performance consideration
6. **JSONL is primary source**: Persistence guarantee

### Breaking Changes

**NONE** - Fully backward compatible with default parameters

### Migration Required

**NONE** - Existing code continues to work unchanged

### Dependencies

- Standard library: `re`, `json`, `os`, `typing`
- No new external dependencies

### Estimated Implementation Time

- JSONL read function: 2 hours
- Tail algorithm: 2 hours
- Filter implementation: 1 hour
- Format conversion: 1 hour
- Testing: 3 hours
- **Total: ~9 hours** (1-2 days)

---

## Implementation Checklist

- [ ] Implement efficient tail algorithm (read from end)
- [ ] Implement regex filter with error handling
- [ ] Implement format conversion (text/jsonl/parsed)
- [ ] Implement metadata collection
- [ ] Add fallback to tmux for backward compatibility
- [ ] Add error handling for all edge cases
- [ ] Write unit tests for each parameter
- [ ] Write integration tests for fallback behavior
- [ ] Update API documentation
- [ ] Add usage examples
- [ ] Performance test with large files
- [ ] Review backward compatibility
