# JSONL Agent Stream Logging Architecture

## Executive Summary

This document specifies the architecture for persistent JSONL (JSON Lines) logging of agent output streams. The current system uses tmux `capture-pane` which is volatile and limited. The new architecture provides persistent, structured, and efficient logging with tail functionality.

---

## 1. File Structure & Location

### 1.1 Directory Layout

```
.agent-workspace/
└── TASK-{timestamp}-{id}/
    ├── logs/                          # NEW: Log directory
    │   ├── {agent_id}_stream.jsonl    # Raw stream capture
    │   └── {agent_id}_stream.jsonl.gz # Compressed (optional, for large logs)
    ├── AGENT_REGISTRY.json
    ├── agent_prompt_{agent_id}.txt
    └── output/                        # Existing output directory
```

### 1.2 File Location Rules

**Primary log file path:**
```
{workspace}/logs/{agent_id}_stream.jsonl
```

**Where:**
- `{workspace}` = Task workspace (from `find_task_workspace(task_id)`)
- `{agent_id}` = Full agent ID (e.g., `investigator-215637-4722d7`)

**Example:**
```
/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/.agent-workspace/TASK-20251017-215604-df6a3cbd/logs/investigator-215637-4722d7_stream.jsonl
```

---

## 2. JSONL Schema Specification

### 2.1 Line Format

Each line in the JSONL file is a complete, valid JSON object with this schema:

```json
{
  "timestamp": "2025-10-17T21:56:40.123456",
  "agent_id": "investigator-215637-4722d7",
  "type": "stdout|stderr|system|control",
  "sequence": 1234,
  "content": "Actual output text...",
  "metadata": {
    "tmux_session": "agent_investigator-215637-4722d7",
    "tool_call": "mcp__claude-orchestrator__update_agent_progress",
    "error": false
  }
}
```

### 2.2 Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `timestamp` | string | YES | ISO 8601 timestamp with microseconds |
| `agent_id` | string | YES | Agent identifier |
| `type` | enum | YES | One of: `stdout`, `stderr`, `system`, `control` |
| `sequence` | integer | YES | Monotonically increasing sequence number (starts at 1) |
| `content` | string | YES | The actual output content (can be empty string) |
| `metadata` | object | NO | Optional metadata (tmux session, tool calls, errors, etc.) |

### 2.3 Type Classification

- **`stdout`**: Normal agent output (text, tool results, thinking)
- **`stderr`**: Error messages, warnings
- **`system`**: System-level events (agent started, stopped, crashed)
- **`control`**: Control messages (progress updates, findings reports)

### 2.4 Example Lines

```jsonl
{"timestamp":"2025-10-17T21:56:40.123456","agent_id":"investigator-215637-4722d7","type":"system","sequence":1,"content":"Agent started","metadata":{"tmux_session":"agent_investigator-215637-4722d7"}}
{"timestamp":"2025-10-17T21:56:41.234567","agent_id":"investigator-215637-4722d7","type":"stdout","sequence":2,"content":"Starting investigation...","metadata":{}}
{"timestamp":"2025-10-17T21:56:42.345678","agent_id":"investigator-215637-4722d7","type":"control","sequence":3,"content":"update_agent_progress called","metadata":{"tool_call":"mcp__claude-orchestrator__update_agent_progress","progress":10}}
{"timestamp":"2025-10-17T21:56:45.456789","agent_id":"investigator-215637-4722d7","type":"stderr","sequence":4,"content":"Warning: File not found","metadata":{"error":true}}
```

---

## 3. Stream Capture Mechanism

### 3.1 Capture Strategy: Dual Approach

We use a **dual capture mechanism** for reliability:

1. **Primary: tmux pipe-pane tee**
2. **Fallback: Periodic tmux capture-pane polling**

### 3.2 Primary Mechanism: tmux pipe-pane

#### Implementation in `deploy_headless_agent`:

```python
# After creating tmux session, enable pipe-pane
log_file = f"{workspace}/logs/{agent_id}_stream.jsonl"
os.makedirs(f"{workspace}/logs", exist_ok=True)

# Create initial system event
initial_event = {
    "timestamp": datetime.now().isoformat(),
    "agent_id": agent_id,
    "type": "system",
    "sequence": 1,
    "content": "Agent deployment started",
    "metadata": {
        "tmux_session": session_name,
        "agent_type": agent_type,
        "parent": parent
    }
}

# Write initial event
with open(log_file, 'a') as f:
    f.write(json.dumps(initial_event) + '\n')

# Configure tmux to pipe output to a processing script
pipe_cmd = f"tmux pipe-pane -t {session_name} -o 'python3 -u /path/to/stream_processor.py {agent_id} {log_file}'"
subprocess.run(pipe_cmd, shell=True)
```

### 3.3 Stream Processor Script

**Location:** `scripts/stream_processor.py`

```python
#!/usr/bin/env python3
"""
Stream processor for agent output -> JSONL conversion.
Reads from stdin (piped from tmux), writes JSONL to file.
"""

import sys
import json
from datetime import datetime

def process_stream(agent_id, log_file):
    sequence = 1

    # Read sequence from existing file
    if os.path.exists(log_file):
        with open(log_file, 'r') as f:
            for line in f:
                try:
                    obj = json.loads(line)
                    sequence = max(sequence, obj.get('sequence', 0) + 1)
                except:
                    pass

    # Process stdin line by line
    for line in sys.stdin:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "agent_id": agent_id,
            "type": "stdout",  # Default to stdout
            "sequence": sequence,
            "content": line.rstrip('\n'),
            "metadata": {}
        }

        # Detect type from content
        if "Error:" in line or "Exception:" in line:
            entry["type"] = "stderr"
            entry["metadata"]["error"] = True
        elif "mcp__claude-orchestrator__" in line:
            entry["type"] = "control"
            # Extract tool call name
            if "update_agent_progress" in line:
                entry["metadata"]["tool_call"] = "update_agent_progress"
            elif "report_agent_finding" in line:
                entry["metadata"]["tool_call"] = "report_agent_finding"

        # Append to log file (atomic write with newline)
        with open(log_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')

        sequence += 1

if __name__ == '__main__':
    agent_id = sys.argv[1]
    log_file = sys.argv[2]
    process_stream(agent_id, log_file)
```

### 3.4 Fallback: Periodic Polling

If pipe-pane fails (tmux version issues, permissions), implement polling:

```python
def poll_tmux_output(session_name, agent_id, log_file, interval=1.0):
    """
    Periodically capture tmux output and append to JSONL.
    Tracks last captured line to avoid duplicates.
    """
    last_line_count = 0
    sequence = 1

    while check_tmux_session_exists(session_name):
        output = get_tmux_session_output(session_name)
        lines = output.split('\n')

        # Only process new lines
        new_lines = lines[last_line_count:]
        last_line_count = len(lines)

        for line in new_lines:
            if not line.strip():
                continue

            entry = {
                "timestamp": datetime.now().isoformat(),
                "agent_id": agent_id,
                "type": "stdout",
                "sequence": sequence,
                "content": line,
                "metadata": {}
            }

            with open(log_file, 'a') as f:
                f.write(json.dumps(entry) + '\n')

            sequence += 1

        time.sleep(interval)
```

### 3.5 Capture Method Decision Tree

```
┌─────────────────────────────┐
│ Deploy Agent                │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│ Check tmux version          │
│ Check pipe-pane available?  │
└──────────┬──────────────────┘
           │
     ┌─────┴─────┐
     │           │
  YES│           │NO
     │           │
     ▼           ▼
┌──────────┐  ┌──────────────┐
│pipe-pane │  │Start polling │
│   tee    │  │  background  │
└──────────┘  └──────────────┘
     │              │
     └──────┬───────┘
            ▼
  ┌──────────────────┐
  │ JSONL log file   │
  │ being written    │
  └──────────────────┘
```

---

## 4. Concurrency & File Locking

### 4.1 Write Strategy: Append-Only

All writes use **append-only mode** (`'a'` in Python):
- POSIX guarantees atomic writes for lines < PIPE_BUF (4096 bytes on most systems)
- Each JSONL line should be < 4KB for atomic guarantee
- Use `O_APPEND` flag ensures atomic positioning

### 4.2 File Locking (Optional Enhancement)

For systems requiring explicit locking:

```python
import fcntl

def append_jsonl_entry(log_file, entry):
    """Append JSONL entry with file locking."""
    with open(log_file, 'a') as f:
        # Acquire exclusive lock
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(json.dumps(entry) + '\n')
            f.flush()  # Force to disk
        finally:
            # Release lock
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

### 4.3 Concurrent Reads

Reads are non-blocking and safe because:
1. We only read complete lines (JSONL format)
2. Writers always append complete lines atomically
3. Readers ignore incomplete last line if file is being written

```python
def read_jsonl_safe(log_file):
    """Read JSONL file safely during concurrent writes."""
    entries = []
    with open(log_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip incomplete line (being written)
                continue
    return entries
```

---

## 5. Tail Functionality Implementation

### 5.1 Efficient Tail Algorithm

Two approaches based on file size:

#### Small Files (<10MB): Load and slice

```python
def tail_jsonl_small(log_file, n=100):
    """Tail for small files - load all, return last N."""
    entries = read_jsonl_safe(log_file)
    return entries[-n:] if len(entries) > n else entries
```

#### Large Files (>10MB): Reverse seek

```python
def tail_jsonl_large(log_file, n=100):
    """Tail for large files - reverse seek from end."""
    entries = []
    chunk_size = 8192  # 8KB chunks

    with open(log_file, 'rb') as f:
        # Seek to end
        f.seek(0, 2)  # SEEK_END
        file_size = f.tell()

        offset = 0
        lines_found = 0
        buffer = b''

        while offset < file_size and lines_found < n:
            # Read chunk from end
            offset = min(offset + chunk_size, file_size)
            f.seek(file_size - offset)
            chunk = f.read(min(chunk_size, offset))

            # Prepend to buffer
            buffer = chunk + buffer

            # Count complete lines
            lines = buffer.split(b'\n')
            lines_found = len([l for l in lines if l.strip()])

        # Parse last N lines
        lines = buffer.split(b'\n')
        for line in lines[-(n+1):]:  # +1 for possible incomplete last line
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line.decode('utf-8')))
            except:
                pass

    return entries[-n:]
```

### 5.2 Tail with Filtering

```python
def tail_jsonl_filtered(log_file, n=100, regex_filter=None, type_filter=None):
    """
    Tail with optional filters.

    Args:
        log_file: Path to JSONL log
        n: Number of lines to return
        regex_filter: Regex pattern to match content
        type_filter: Filter by type (stdout, stderr, etc.)
    """
    import re

    # For filtered tails, we need to scan more lines
    # Start with 10x the requested amount
    entries = tail_jsonl_large(log_file, n * 10)

    filtered = []
    for entry in entries:
        # Type filter
        if type_filter and entry.get('type') != type_filter:
            continue

        # Regex filter
        if regex_filter:
            pattern = re.compile(regex_filter)
            if not pattern.search(entry.get('content', '')):
                continue

        filtered.append(entry)

    return filtered[-n:]
```

---

## 6. Performance Considerations

### 6.1 Write Performance

**Expected throughput:**
- Append-only writes: ~100,000 lines/sec (SSD)
- With file locking: ~50,000 lines/sec
- With fsync: ~5,000 lines/sec

**Optimization strategies:**
1. **Buffered writes**: Buffer in memory, flush every 100ms or 1000 lines
2. **Async I/O**: Use asyncio for non-blocking writes
3. **Batching**: Write multiple entries in single `write()` call

```python
class BufferedJSONLWriter:
    """Buffered JSONL writer with periodic flushing."""

    def __init__(self, log_file, flush_interval=0.1, buffer_size=1000):
        self.log_file = log_file
        self.buffer = []
        self.flush_interval = flush_interval
        self.buffer_size = buffer_size
        self.last_flush = time.time()
        self.lock = threading.Lock()

    def append(self, entry):
        """Append entry to buffer."""
        with self.lock:
            self.buffer.append(json.dumps(entry) + '\n')

            # Flush if buffer full or time exceeded
            if len(self.buffer) >= self.buffer_size or \
               (time.time() - self.last_flush) >= self.flush_interval:
                self._flush()

    def _flush(self):
        """Flush buffer to file."""
        if not self.buffer:
            return

        with open(self.log_file, 'a') as f:
            f.writelines(self.buffer)
            f.flush()

        self.buffer = []
        self.last_flush = time.time()
```

### 6.2 Read Performance

**Tail operation benchmarks:**
- Small file (<10MB): ~10ms
- Large file (100MB): ~50ms (reverse seek)
- Very large file (1GB): ~200ms

**Indexing for faster reads:**

Create `.jsonl.idx` index file:

```
# Format: byte_offset,sequence,timestamp
0,1,2025-10-17T21:56:40.123456
147,2,2025-10-17T21:56:41.234567
294,3,2025-10-17T21:56:42.345678
...
```

Index enables:
- O(1) seek to specific sequence number
- O(log n) seek to specific timestamp
- Fast random access

### 6.3 Log Rotation

For long-running agents (>1GB logs):

```python
def rotate_log(log_file, max_size_mb=100):
    """Rotate log file if too large."""
    if not os.path.exists(log_file):
        return

    size_mb = os.path.getsize(log_file) / (1024 * 1024)
    if size_mb < max_size_mb:
        return

    # Rotate: file.jsonl -> file.jsonl.1
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    rotated = f"{log_file}.{timestamp}"

    os.rename(log_file, rotated)

    # Optionally compress
    subprocess.run(['gzip', rotated])
```

---

## 7. Error Handling & Edge Cases

### 7.1 Incomplete Lines

**Problem:** Agent crashes mid-write, leaving incomplete JSON line.

**Solution:**
```python
def read_jsonl_robust(log_file):
    """Read JSONL with incomplete line handling."""
    entries = []
    with open(log_file, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                # Log error but continue
                logger.warning(f"Invalid JSON at line {line_num}: {e}")
                # Store as raw entry
                entries.append({
                    "timestamp": datetime.now().isoformat(),
                    "type": "system",
                    "sequence": -1,
                    "content": f"PARSE_ERROR: {line}",
                    "metadata": {"error": True, "parse_error": str(e)}
                })
    return entries
```

### 7.2 Agent Crashes

**Problem:** Agent crashes, tmux session dies, pipe-pane stops.

**Solution:** Write termination event in `get_real_task_status`:

```python
# In get_real_task_status, when detecting crashed agent:
if not check_tmux_session_exists(agent['tmux_session']) and agent['status'] == 'running':
    # Write termination event to log
    log_file = f"{workspace}/logs/{agent['id']}_stream.jsonl"
    if os.path.exists(log_file):
        termination_event = {
            "timestamp": datetime.now().isoformat(),
            "agent_id": agent['id'],
            "type": "system",
            "sequence": -1,
            "content": "Agent terminated (tmux session ended)",
            "metadata": {"exit_status": "crashed"}
        }
        append_jsonl_entry(log_file, termination_event)
```

### 7.3 Disk Full

**Problem:** Disk full, writes fail silently.

**Solution:**
```python
def append_jsonl_entry_safe(log_file, entry):
    """Append with disk full handling."""
    try:
        with open(log_file, 'a') as f:
            f.write(json.dumps(entry) + '\n')
            f.flush()
        return True
    except OSError as e:
        if e.errno == errno.ENOSPC:  # No space left on device
            logger.error(f"Disk full, cannot write to {log_file}")
            # Fallback: write to in-memory buffer
            # Alert user/operator
        return False
```

### 7.4 Permissions Issues

**Problem:** Log directory not writable.

**Solution:** Check permissions in `deploy_headless_agent`:

```python
log_dir = f"{workspace}/logs"
try:
    os.makedirs(log_dir, exist_ok=True)
    # Test write
    test_file = f"{log_dir}/.write_test"
    with open(test_file, 'w') as f:
        f.write('test')
    os.remove(test_file)
except (OSError, PermissionError) as e:
    return {
        "success": False,
        "error": f"Cannot write to log directory: {e}"
    }
```

---

## 8. Integration with get_agent_output

### 8.1 Enhanced API Signature

```python
def get_agent_output(
    task_id: str,
    agent_id: str,
    tail: Optional[int] = None,        # NEW: Last N lines
    filter: Optional[str] = None,      # NEW: Regex filter
    type_filter: Optional[str] = None, # NEW: Type filter
    format: str = 'text'               # NEW: 'text' | 'jsonl' | 'json'
) -> Dict[str, Any]:
```

### 8.2 Implementation

```python
def get_agent_output(task_id, agent_id, tail=None, filter=None, type_filter=None, format='text'):
    """Get agent output from JSONL log with tail and filtering."""

    workspace = find_task_workspace(task_id)
    if not workspace:
        return {"success": False, "error": f"Task {task_id} not found"}

    log_file = f"{workspace}/logs/{agent_id}_stream.jsonl"

    # Check if log file exists
    if not os.path.exists(log_file):
        # Fallback to tmux capture for backward compatibility
        return get_agent_output_tmux(task_id, agent_id)

    # Read from JSONL log
    if tail:
        entries = tail_jsonl_filtered(log_file, n=tail, regex_filter=filter, type_filter=type_filter)
    else:
        entries = read_jsonl_safe(log_file)
        # Apply filters
        if filter or type_filter:
            entries = [e for e in entries if (
                (not type_filter or e.get('type') == type_filter) and
                (not filter or re.search(filter, e.get('content', '')))
            )]

    # Format output
    if format == 'jsonl':
        output = '\n'.join(json.dumps(e) for e in entries)
    elif format == 'json':
        output = entries  # Return as list
    else:  # format == 'text'
        output = '\n'.join(e.get('content', '') for e in entries)

    return {
        "success": True,
        "agent_id": agent_id,
        "log_file": log_file,
        "entry_count": len(entries),
        "output": output,
        "format": format
    }
```

### 8.3 Backward Compatibility

Keep tmux fallback for agents deployed before JSONL logging:

```python
def get_agent_output_tmux(task_id, agent_id):
    """Legacy tmux-based output capture."""
    # ... existing implementation ...
    session_name = agent['tmux_session']
    output = get_tmux_session_output(session_name)
    return {
        "success": True,
        "agent_id": agent_id,
        "tmux_session": session_name,
        "output": output,
        "method": "tmux_fallback"
    }
```

---

## 9. Testing Strategy

### 9.1 Unit Tests

```python
# Test JSONL writing
def test_append_jsonl_entry():
    log_file = "/tmp/test_agent.jsonl"
    entry = {
        "timestamp": "2025-10-17T21:56:40.123456",
        "agent_id": "test-agent",
        "type": "stdout",
        "sequence": 1,
        "content": "Test output"
    }
    append_jsonl_entry(log_file, entry)

    # Read back
    with open(log_file, 'r') as f:
        line = f.readline()
        assert json.loads(line) == entry

# Test tail functionality
def test_tail_jsonl():
    # Create log with 1000 entries
    log_file = "/tmp/test_tail.jsonl"
    for i in range(1000):
        entry = {"sequence": i, "content": f"Line {i}"}
        append_jsonl_entry(log_file, entry)

    # Tail 10
    entries = tail_jsonl_large(log_file, 10)
    assert len(entries) == 10
    assert entries[-1]['sequence'] == 999
```

### 9.2 Integration Tests

```python
# Test full agent deployment with logging
def test_agent_deployment_with_logging():
    task_id = create_real_task("Test task")

    # Deploy agent
    result = deploy_headless_agent(task_id, "test_agent", "echo test")
    agent_id = result['agent']['id']

    # Wait for output
    time.sleep(2)

    # Read output via API
    output_result = get_agent_output(task_id, agent_id, tail=100)
    assert output_result['success']
    assert 'test' in output_result['output']
```

### 9.3 Stress Tests

```python
# Test concurrent writes
def test_concurrent_writes():
    log_file = "/tmp/stress_test.jsonl"
    num_threads = 10
    writes_per_thread = 1000

    def writer(thread_id):
        for i in range(writes_per_thread):
            entry = {
                "timestamp": datetime.now().isoformat(),
                "sequence": thread_id * writes_per_thread + i,
                "content": f"Thread {thread_id} write {i}"
            }
            append_jsonl_entry(log_file, entry)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Verify all lines written
    with open(log_file, 'r') as f:
        lines = [l for l in f if l.strip()]
    assert len(lines) == num_threads * writes_per_thread
```

---

## 10. Implementation Roadmap

### Phase 1: Core Infrastructure (Priority: HIGH)
1. Create `scripts/stream_processor.py` script
2. Modify `deploy_headless_agent` to:
   - Create `logs/` directory
   - Write initial system event
   - Set up tmux pipe-pane to stream_processor
3. Test basic JSONL logging with simple agent

### Phase 2: API Enhancement (Priority: HIGH)
1. Implement `tail_jsonl_large()` and `tail_jsonl_filtered()`
2. Modify `get_agent_output` to:
   - Check for JSONL log file first
   - Fall back to tmux if not found
   - Support tail, filter, type_filter, format parameters
3. Update MCP tool decorator with new parameters

### Phase 3: Robustness (Priority: MEDIUM)
1. Add error handling for:
   - Incomplete JSON lines
   - Disk full scenarios
   - Permission issues
2. Implement agent crash detection and termination events
3. Add comprehensive logging and alerting

### Phase 4: Performance (Priority: MEDIUM)
1. Implement buffered writer (`BufferedJSONLWriter`)
2. Add log rotation for large files
3. Benchmark and optimize tail operations
4. Optional: Implement indexing for very large logs

### Phase 5: Testing & Documentation (Priority: HIGH)
1. Write unit tests for all JSONL functions
2. Integration tests for full agent lifecycle
3. Stress tests for concurrent writes
4. Update API documentation

---

## 11. Key Decisions & Rationale

### Decision 1: JSONL vs. Plain Text
**Choice:** JSONL
**Rationale:**
- Structured data enables filtering, parsing, metadata
- Each line is valid JSON (easy to parse)
- Append-only friendly
- Industry standard for log streaming

### Decision 2: Dual Capture (pipe-pane + polling)
**Choice:** Primary pipe-pane, fallback polling
**Rationale:**
- pipe-pane is most efficient (real-time streaming)
- Polling provides reliability fallback
- Graceful degradation if pipe-pane unavailable

### Decision 3: Append-Only Files
**Choice:** Append-only, no updates
**Rationale:**
- Atomic writes (POSIX guarantee)
- Simple concurrency model
- No need for complex locking
- Matches JSONL convention

### Decision 4: Sequence Numbers
**Choice:** Include monotonic sequence in each entry
**Rationale:**
- Detect missing/dropped lines
- Enable ordering even if timestamps conflict
- Useful for debugging

### Decision 5: Backward Compatibility
**Choice:** Keep tmux fallback in get_agent_output
**Rationale:**
- Existing agents won't break
- Gradual migration path
- No big-bang deployment required

---

## 12. Future Enhancements

### 12.1 Real-Time Streaming API
WebSocket or SSE endpoint for real-time log tailing:

```python
@mcp.tool
def stream_agent_output(task_id, agent_id, since_sequence=0):
    """Stream agent output from JSONL log."""
    log_file = f"{workspace}/logs/{agent_id}_stream.jsonl"

    # Tail -f equivalent
    with open(log_file, 'r') as f:
        # Seek to last known sequence
        for line in f:
            entry = json.loads(line)
            if entry['sequence'] > since_sequence:
                yield entry

        # Watch for new lines
        while True:
            line = f.readline()
            if line:
                yield json.loads(line)
            else:
                time.sleep(0.1)
```

### 12.2 Compression
Automatic gzip compression for rotated logs:

```python
# After rotation
subprocess.run(['gzip', f"{log_file}.{timestamp}"])
```

### 12.3 Centralized Log Aggregation
Push logs to centralized system (Elasticsearch, Loki, etc.):

```python
def push_to_loki(entries):
    """Push JSONL entries to Grafana Loki."""
    # Implementation for centralized logging
    pass
```

### 12.4 Log Analysis
Built-in analysis tools:

```python
def analyze_agent_log(log_file):
    """Analyze agent log for patterns, errors, performance."""
    entries = read_jsonl_safe(log_file)

    analysis = {
        "total_lines": len(entries),
        "error_count": len([e for e in entries if e['type'] == 'stderr']),
        "duration": (entries[-1]['timestamp'] - entries[0]['timestamp']),
        "tool_calls": [e for e in entries if e['type'] == 'control'],
        "output_rate": len(entries) / duration_seconds
    }
    return analysis
```

---

## 13. Summary

This JSONL logging architecture provides:

✅ **Persistent storage** - Survives tmux session termination
✅ **Structured data** - JSON format enables filtering, parsing, analysis
✅ **Efficient tail** - Fast access to last N lines without reading entire file
✅ **Concurrent safe** - Append-only, atomic writes
✅ **Backward compatible** - Falls back to tmux for old agents
✅ **Scalable** - Handles large logs (100MB+) efficiently
✅ **Robust** - Handles crashes, incomplete writes, disk full

**Key files to create/modify:**
1. `scripts/stream_processor.py` - NEW
2. `real_mcp_server.py::deploy_headless_agent()` - MODIFY
3. `real_mcp_server.py::get_agent_output()` - MODIFY
4. `tests/test_jsonl_logging.py` - NEW

**Ready for implementation by builder agents.**
