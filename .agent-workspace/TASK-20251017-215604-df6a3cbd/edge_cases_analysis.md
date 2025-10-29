# Edge Cases and Failure Modes Analysis: JSONL Agent Logging

**Analyzer:** edge_case_analyzer-215644-ac4707
**Date:** 2025-10-17
**Task:** TASK-20251017-215604-df6a3cbd

## Executive Summary

This document analyzes edge cases, failure scenarios, and mitigation strategies for implementing persistent JSONL stream logging for Claude agents. The current system (real_mcp_server.py:194-205) uses `tmux capture-pane -p` which is ephemeral and provides no persistence.

---

## 1. CRITICAL EDGE CASES

### 1.1 Agent Crashes Mid-Stream (Incomplete JSONL Line)

**Scenario:**
```python
# Agent writing to log:
{"timestamp": "2025-10-17T21:56:00", "type": "progress", "message": "Starting anal
# ^ Process killed here, incomplete JSON
```

**Impact:** CRITICAL
- JSONL parser will fail on incomplete line
- All subsequent valid lines may be skipped if parser doesn't handle gracefully
- Tailing functionality will break

**Mitigation Strategies:**
1. **Line-by-line parsing with error recovery:**
   ```python
   def read_jsonl_robust(filepath, tail=None):
       lines = []
       with open(filepath, 'r') as f:
           for line_num, line in enumerate(f, 1):
               line = line.strip()
               if not line:  # Skip empty lines
                   continue
               try:
                   parsed = json.loads(line)
                   lines.append(parsed)
               except json.JSONDecodeError as e:
                   # Log error but continue parsing
                   logger.warning(f"Malformed JSON at line {line_num}: {e}")
                   # Include raw line with error marker
                   lines.append({
                       "type": "parse_error",
                       "line_number": line_num,
                       "raw_content": line[:200],  # Truncate for safety
                       "error": str(e)
                   })

       # Apply tail after parsing
       if tail and tail > 0:
           return lines[-tail:]
       return lines
   ```

2. **Write operations must be atomic per line:**
   - Buffer complete JSON object in memory
   - Write entire line + newline in single operation
   - Use file locking during write

3. **Signal handlers for graceful shutdown:**
   ```python
   import signal
   import atexit

   class JSONLLogger:
       def __init__(self, filepath):
           self.filepath = filepath
           self.buffer = None
           # Register cleanup handlers
           signal.signal(signal.SIGTERM, self._flush_and_exit)
           signal.signal(signal.SIGINT, self._flush_and_exit)
           atexit.register(self._flush_buffer)

       def _flush_buffer(self):
           if self.buffer:
               # Attempt to write incomplete as error record
               self._write_error_record(self.buffer)

       def _flush_and_exit(self, signum, frame):
           self._flush_buffer()
           sys.exit(0)
   ```

**Test Scenario:**
- Kill agent with `kill -9` (SIGKILL - cannot be caught)
- Kill agent with `kill -15` (SIGTERM - can be caught)
- Verify reader handles both gracefully

---

### 1.2 Concurrent Writes (Multiple Processes → Same Log)

**Scenario:**
Agent spawns child agents, both try writing to same log file simultaneously.

**Impact:** HIGH
- Race condition: interleaved JSON lines
- Corrupted JSONL (line 1 from agent A mixed with line 2 from agent B)
- Data loss if writes overwrite each other

**Current Risk in Implementation:**
Looking at real_mcp_server.py:1254-1350, each agent gets unique agent_id and should have separate log file. **HOWEVER:**
- If task creation doesn't enforce unique log paths
- If log file path derived from task_id instead of agent_id
- Multiple agents could write to same file

**Mitigation Strategies:**

1. **File-level locking (MANDATORY):**
   ```python
   import fcntl

   class JSONLWriter:
       def __init__(self, filepath):
           self.filepath = filepath

       def append(self, record: dict):
           with open(self.filepath, 'a') as f:
               # Acquire exclusive lock
               fcntl.flock(f.fileno(), fcntl.LOCK_EX)
               try:
                   line = json.dumps(record) + '\n'
                   f.write(line)
                   f.flush()  # Force to disk
                   os.fsync(f.fileno())  # Ensure kernel writes
               finally:
                   # Release lock (automatic on close, but explicit is better)
                   fcntl.flock(f.fileno(), fcntl.LOCK_UN)
   ```

2. **Enforce unique log files per agent:**
   ```python
   # In deploy_headless_agent():
   log_filepath = f"{workspace}/logs/{agent_id}_stream.jsonl"
   # NOT: f"{workspace}/logs/{task_id}_stream.jsonl"
   ```

3. **Process-safe append mode:**
   - Always open in `'a'` (append) mode, never `'w'`
   - Use `O_APPEND` flag (guaranteed atomic on POSIX)

4. **Consider separate logs dir per agent:**
   ```
   .agent-workspace/
     TASK-xxx/
       logs/
         agent-123/
           stream.jsonl
         agent-456/
           stream.jsonl
   ```

**Test Scenario:**
- Spawn 3 agents writing to logs simultaneously
- Each writes 1000 lines
- Verify 3000 total lines, no corruption
- Verify no interleaved JSON

---

### 1.3 Disk Full Scenarios

**Scenario:**
Agent writes until filesystem is full.

**Impact:** HIGH
- Write operations fail silently or raise OSError
- Partial writes create incomplete JSONL lines
- Agent may crash if exception not handled
- System-wide impact (other services affected)

**Mitigation Strategies:**

1. **Pre-flight disk space check:**
   ```python
   import shutil

   def check_disk_space(path, min_mb=100):
       """Ensure minimum disk space available"""
       stat = shutil.disk_usage(path)
       free_mb = stat.free / (1024 * 1024)
       return free_mb >= min_mb

   # In deploy_headless_agent():
   if not check_disk_space(workspace, min_mb=100):
       return {
           "success": False,
           "error": "Insufficient disk space (<100MB available)"
       }
   ```

2. **Graceful error handling in writer:**
   ```python
   def append(self, record: dict):
       try:
           with open(self.filepath, 'a') as f:
               fcntl.flock(f.fileno(), fcntl.LOCK_EX)
               line = json.dumps(record) + '\n'
               f.write(line)
               f.flush()
               os.fsync(f.fileno())
       except OSError as e:
           if e.errno == errno.ENOSPC:  # No space left on device
               # Write to stderr instead (still captured by tmux)
               sys.stderr.write(f"DISK FULL: Cannot write to log\n")
               # Stop agent gracefully
               self.emergency_shutdown()
           else:
               raise
   ```

3. **Log rotation with size limits:**
   ```python
   MAX_LOG_SIZE_MB = 500

   def rotate_if_needed(self):
       if os.path.getsize(self.filepath) > MAX_LOG_SIZE_MB * 1024 * 1024:
           # Rotate: stream.jsonl -> stream.jsonl.1
           shutil.move(self.filepath, f"{self.filepath}.1")
           # Keep only 2 rotations max
           old_log = f"{self.filepath}.2"
           if os.path.exists(old_log):
               os.remove(old_log)
   ```

4. **Monitoring and alerts:**
   - Add disk space metric to agent progress reports
   - Warning when < 500MB free
   - Error when < 100MB free

**Test Scenario:**
- Create small loop device (100MB)
- Run agent until disk full
- Verify graceful degradation
- Verify no corruption

---

### 1.4 Very Large Logs (Multi-GB Output)

**Scenario:**
Long-running agent generates 10GB+ of logs.

**Impact:** MEDIUM
- `get_agent_output()` loads entire file into memory → OOM crash
- Tailing becomes slow without optimization
- Network transfer of full log is expensive

**Mitigation Strategies:**

1. **Streaming tail implementation (CRITICAL):**
   ```python
   def tail_jsonl(filepath, n_lines=100):
       """Efficient tail using file seeking"""
       if not os.path.exists(filepath):
           return []

       file_size = os.path.getsize(filepath)
       if file_size == 0:
           return []

       # Estimate: average line ~200 bytes
       # Read last (n_lines * 300) bytes to ensure we get n_lines
       seek_size = min(n_lines * 300, file_size)

       with open(filepath, 'rb') as f:
           f.seek(-seek_size, os.SEEK_END)
           data = f.read().decode('utf-8', errors='ignore')
           lines = data.split('\n')

           # Parse last n valid JSON lines
           valid_lines = []
           for line in reversed(lines):
               if len(valid_lines) >= n_lines:
                   break
               line = line.strip()
               if not line:
                   continue
               try:
                   valid_lines.append(json.loads(line))
               except json.JSONDecodeError:
                   continue

           return list(reversed(valid_lines))
   ```

2. **Pagination API:**
   ```python
   def get_agent_output(task_id, agent_id, tail=None, offset=None, limit=None):
       """
       - tail: Last N lines (efficient)
       - offset + limit: Pagination for full log browsing
       """
       if tail:
           return tail_jsonl(log_path, tail)
       elif offset is not None and limit is not None:
           # For pagination: read specific range
           return read_jsonl_range(log_path, offset, limit)
       else:
           # Full read: warn if > 10000 lines
           return read_jsonl_with_warning(log_path)
   ```

3. **Log rotation (already discussed in 1.3):**
   - Keep active log under 500MB
   - Archive old rotations (compress with gzip)

4. **Lazy loading for UI:**
   - Default to `tail=100` in API
   - Load more on demand

**Test Scenario:**
- Generate 10GB synthetic log (1M lines)
- Time `tail_jsonl(path, 100)` vs full read
- Verify tail < 100ms, full read fails or times out

---

### 1.5 Log File Corruption

**Scenario:**
- Filesystem corruption
- Power loss during write
- Bug in writer creates invalid JSON

**Impact:** MEDIUM
- Parser fails on entire file
- Loss of historical data

**Mitigation Strategies:**

1. **Checksum per line (optional, adds overhead):**
   ```python
   {"timestamp": "...", "data": "...", "checksum": "sha256_hash"}
   ```

2. **Robust parser (already covered in 1.1):**
   - Skip corrupted lines
   - Continue parsing rest of file

3. **Backup on rotation:**
   ```python
   def rotate_with_backup(filepath):
       # Validate before rotating
       if validate_jsonl(filepath):
           shutil.copy2(filepath, f"{filepath}.backup")
           shutil.move(filepath, f"{filepath}.1")
       else:
           # Corruption detected, keep as .corrupted
           shutil.move(filepath, f"{filepath}.corrupted.{timestamp}")
   ```

4. **Periodic validation job:**
   ```python
   def validate_jsonl(filepath):
       """Return (is_valid, error_lines[])"""
       errors = []
       with open(filepath, 'r') as f:
           for line_num, line in enumerate(f, 1):
               if line.strip():
                   try:
                       json.loads(line)
                   except json.JSONDecodeError as e:
                       errors.append((line_num, str(e)))
       return len(errors) == 0, errors
   ```

**Test Scenario:**
- Manually corrupt lines in log file
- Verify parser recovery
- Verify user notified of corruption

---

### 1.6 Permission Issues

**Scenario:**
- Log file created with restrictive permissions
- Directory not writable
- SELinux/AppArmor restrictions

**Impact:** HIGH
- Agent cannot write logs → crashes or fails silently
- Reader cannot read logs

**Mitigation Strategies:**

1. **Explicit permission setting:**
   ```python
   def ensure_log_directory(workspace):
       log_dir = f"{workspace}/logs"
       os.makedirs(log_dir, mode=0o755, exist_ok=True)

       # Ensure writable
       if not os.access(log_dir, os.W_OK):
           raise PermissionError(f"Log directory not writable: {log_dir}")

       return log_dir
   ```

2. **Safe file creation:**
   ```python
   def create_log_file(filepath):
       # Create with explicit permissions
       fd = os.open(filepath, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)
       os.close(fd)
   ```

3. **Fallback to tmpfs:**
   ```python
   def get_log_filepath(workspace, agent_id):
       primary = f"{workspace}/logs/{agent_id}_stream.jsonl"

       # Test write access
       try:
           ensure_log_directory(workspace)
           return primary
       except (PermissionError, OSError):
           # Fallback to /tmp
           fallback = f"/tmp/claude-orchestrator/{agent_id}_stream.jsonl"
           logger.warning(f"Cannot write to {primary}, using {fallback}")
           os.makedirs(os.path.dirname(fallback), exist_ok=True)
           return fallback
   ```

4. **Clear error messages:**
   ```python
   except PermissionError as e:
       return {
           "success": False,
           "error": f"Permission denied writing to log: {e}",
           "suggestion": "Check directory permissions or run with appropriate user"
       }
   ```

**Test Scenario:**
- Create workspace with chmod 555 (read-only)
- Attempt to deploy agent
- Verify clear error message
- Verify fallback works

---

### 1.7 Log Rotation During Active Agent

**Scenario:**
Agent is writing to `stream.jsonl`, rotation renames it to `stream.jsonl.1`, agent continues writing to renamed file.

**Impact:** MEDIUM
- Reader opens new `stream.jsonl`, sees no new data
- Agent writes to rotated file
- Data split across files

**Mitigation Strategies:**

1. **Rotation-safe logging (copytruncate pattern):**
   ```python
   def rotate_log_safe(filepath):
       """Rotate without breaking active writers"""
       # Copy current log
       shutil.copy2(filepath, f"{filepath}.1")

       # Truncate original (writers still have file handle)
       with open(filepath, 'r+') as f:
           fcntl.flock(f.fileno(), fcntl.LOCK_EX)
           f.truncate(0)
           fcntl.flock(f.fileno(), fcntl.LOCK_UN)
   ```

2. **Inode-based writer (Linux):**
   ```python
   class INodeSafeWriter:
       def __init__(self, filepath):
           self.filepath = filepath
           self.file_handle = None
           self.current_inode = None

       def write(self, data):
           # Check if file was rotated
           current_stat = os.stat(self.filepath)
           if self.current_inode != current_stat.st_ino:
               # File rotated, reopen
               if self.file_handle:
                   self.file_handle.close()
               self.file_handle = open(self.filepath, 'a')
               self.current_inode = current_stat.st_ino

           self.file_handle.write(data)
   ```

3. **Signal-based rotation:**
   ```python
   # Agent listens for SIGHUP → reopen log file
   signal.signal(signal.SIGHUP, self._reopen_log)

   def _reopen_log(self, signum, frame):
       self.file_handle.close()
       self.file_handle = open(self.filepath, 'a')
   ```

4. **Alternative: Never rotate active agent logs**
   - Only rotate after agent completes
   - Size limit enforcement prevents runaway growth

**Recommendation:** Option 4 (no rotation while active) is simplest and safest.

**Test Scenario:**
- Start agent writing continuously
- Rotate log file
- Verify agent detects rotation or continues safely
- Verify reader sees all data

---

### 1.8 Reading While Agent Still Writing

**Scenario:**
`get_agent_output()` called while agent actively writing JSONL.

**Impact:** LOW to MEDIUM
- Read sees incomplete line (not flushed yet)
- Race condition: read position vs write position

**Mitigation Strategies:**

1. **Reader uses shared locks:**
   ```python
   def read_jsonl(filepath):
       with open(filepath, 'r') as f:
           # Acquire shared lock (multiple readers OK, blocks writers)
           fcntl.flock(f.fileno(), fcntl.LOCK_SH)
           try:
               lines = f.readlines()
               return [json.loads(l) for l in lines if l.strip()]
           finally:
               fcntl.flock(f.fileno(), fcntl.LOCK_UN)
   ```

2. **Writer flushes after each line (already recommended):**
   ```python
   f.write(line)
   f.flush()
   os.fsync(f.fileno())
   ```

3. **Tail implementation handles incomplete lines:**
   - Skip last line if not ending with `\n`
   - Or attempt to parse and skip if invalid

4. **Consistency guarantee:**
   - Reader only returns complete, parseable lines
   - Incomplete lines silently skipped (will appear in next read)

**Test Scenario:**
- Agent writes 10 lines/sec
- Reader reads 100 times/sec
- Verify no parser errors
- Verify no data loss

---

## 2. FAILURE SCENARIOS

### 2.1 Log File Doesn't Exist

**When:** `get_agent_output()` called before agent writes first line.

**Current State:** File won't exist until first write.

**Handling:**
```python
def get_agent_output(task_id, agent_id, tail=None):
    log_path = get_log_filepath(task_id, agent_id)

    if not os.path.exists(log_path):
        # This is normal for new agents
        return {
            "success": True,
            "agent_id": agent_id,
            "output": [],
            "note": "Agent has not yet written any logs"
        }

    # Continue with read...
```

**Severity:** LOW (expected scenario)

---

### 2.2 JSONL is Malformed

**Already covered in 1.1 (incomplete lines) and 1.5 (corruption).**

**Summary:**
- Line-by-line parsing with error recovery
- Skip bad lines, continue parsing
- Report parse errors in output with line numbers

---

### 2.3 Agent Exits Before Writing Logs

**Scenario:**
Agent crashes in initialization, before creating log file or writing anything.

**Impact:** LOW
- Same as 2.1 (file doesn't exist)
- Fallback: use tmux capture as backup

**Handling:**
```python
def get_agent_output(task_id, agent_id, tail=None):
    log_path = get_log_filepath(task_id, agent_id)

    if not os.path.exists(log_path):
        # Fallback: try tmux capture
        if check_tmux_session_exists(agent['tmux_session']):
            tmux_output = get_tmux_session_output(agent['tmux_session'])
            return {
                "success": True,
                "agent_id": agent_id,
                "output": tmux_output,
                "source": "tmux_fallback",
                "note": "Log file not found, using tmux capture"
            }
        else:
            return {
                "success": True,
                "agent_id": agent_id,
                "output": [],
                "note": "Agent exited without writing logs"
            }
```

**Severity:** LOW (handled by fallback)

---

### 2.4 Filesystem is Read-Only

**Scenario:**
- Root partition mounted ro
- Network filesystem mount fails
- Container in read-only mode

**Impact:** CRITICAL
- Agent cannot write logs → crashes
- Entire deployment fails

**Handling:**
```python
def deploy_headless_agent(...):
    workspace = find_task_workspace(task_id)

    # Test write access BEFORE deploying agent
    test_file = f"{workspace}/.write_test_{uuid.uuid4().hex[:6]}"
    try:
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
    except (OSError, IOError) as e:
        return {
            "success": False,
            "error": f"Workspace is not writable: {e}",
            "workspace": workspace
        }

    # Continue with deployment...
```

**Severity:** HIGH (must detect before deployment)

---

### 2.5 Log Directory Deleted Mid-Run

**Scenario:**
Someone runs `rm -rf .agent-workspace` while agents running.

**Impact:** HIGH
- All agents lose ability to write logs
- Writers crash with FileNotFoundError

**Handling:**

1. **Auto-recreate directory:**
   ```python
   class ResilientJSONLWriter:
       def append(self, record):
           try:
               with open(self.filepath, 'a') as f:
                   # ... write ...
           except FileNotFoundError:
               # Directory deleted, recreate
               os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
               # Retry write
               with open(self.filepath, 'a') as f:
                   # ... write ...
   ```

2. **Watchdog monitoring:**
   ```python
   from watchdog.observers import Observer
   from watchdog.events import FileSystemEventHandler

   class WorkspaceMonitor(FileSystemEventHandler):
       def on_deleted(self, event):
           if event.src_path == self.workspace_dir:
               logger.critical("Workspace directory deleted! Recreating...")
               os.makedirs(self.workspace_dir, exist_ok=True)
   ```

3. **Graceful degradation:**
   - If auto-recreate fails, switch to tmux-only mode
   - Continue agent execution (logs lost but agent survives)

**Severity:** MEDIUM (rare but should handle)

---

## 3. RACE CONDITIONS

### 3.1 Multiple Readers Reading Same Log

**Impact:** LOW
- Shared locks allow concurrent reads (safe)
- No data corruption possible
- Slight performance impact only

**Handling:** Already covered by `fcntl.LOCK_SH` (shared locks).

---

### 3.2 Writer Writing While Reader Tails

**Impact:** LOW
**Handling:** Already covered in 1.8.

---

### 3.3 Log Rotation While Reading

**Impact:** MEDIUM
- Reader opens file, rotation renames it, reader continues reading old file
- Reader sees stale data

**Mitigation:**
```python
def read_jsonl_with_rotation_check(filepath):
    """Detect if file was rotated during read"""
    stat_before = os.stat(filepath)
    inode_before = stat_before.st_ino

    with open(filepath, 'r') as f:
        lines = f.readlines()

    stat_after = os.stat(filepath)
    inode_after = stat_after.st_ino

    if inode_before != inode_after:
        # File was rotated, re-read
        return read_jsonl_with_rotation_check(filepath)

    return lines
```

**Alternative:** If "no rotation while active" policy, this is non-issue.

---

### 3.4 Agent Restart With Same ID

**Scenario:**
Agent crashes and is restarted with same agent_id. Log file already exists.

**Impact:** MEDIUM
- Old logs mixed with new run
- Hard to distinguish runs

**Mitigation:**

1. **Append mode is correct:**
   - New run continues log (chronological history)
   - Timestamp distinguishes runs

2. **Add restart marker:**
   ```python
   def initialize_log(filepath, agent_id, restart=False):
       if os.path.exists(filepath) and restart:
           # Write restart marker
           append_jsonl(filepath, {
               "timestamp": datetime.now().isoformat(),
               "type": "lifecycle",
               "event": "agent_restart",
               "agent_id": agent_id
           })
   ```

3. **Unique log per attempt:**
   ```python
   # Include attempt number in filename
   log_path = f"{workspace}/logs/{agent_id}_attempt_{attempt_num}.jsonl"
   ```

**Recommendation:** Option 1 (append with timestamps) is simplest.

---

## 4. RECOMMENDED ARCHITECTURE

Based on above analysis, here's the robust implementation:

### 4.1 Directory Structure
```
.agent-workspace/
  TASK-xxx/
    logs/
      agent-123_stream.jsonl        # Active log
      agent-123_stream.jsonl.1      # Rotated (if enabled)
      agent-456_stream.jsonl
```

### 4.2 Core Components

**JSONLWriter Class:**
```python
class JSONLWriter:
    def __init__(self, filepath, max_size_mb=500):
        self.filepath = filepath
        self.max_size_mb = max_size_mb
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        os.makedirs(os.path.dirname(self.filepath), mode=0o755, exist_ok=True)
        if not os.path.exists(self.filepath):
            open(self.filepath, 'a').close()
            os.chmod(self.filepath, 0o644)

    def append(self, record: dict):
        """Thread-safe, atomic append"""
        # Add timestamp if not present
        if 'timestamp' not in record:
            record['timestamp'] = datetime.now(timezone.utc).isoformat()

        line = json.dumps(record, ensure_ascii=False) + '\n'

        max_retries = 3
        for attempt in range(max_retries):
            try:
                with open(self.filepath, 'a') as f:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    try:
                        f.write(line)
                        f.flush()
                        os.fsync(f.fileno())
                    finally:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                break  # Success
            except FileNotFoundError:
                # Directory deleted, recreate
                self._ensure_file_exists()
            except OSError as e:
                if e.errno == errno.ENOSPC:
                    # Disk full
                    self._handle_disk_full()
                    break
                elif attempt == max_retries - 1:
                    raise
                else:
                    time.sleep(0.1 * (attempt + 1))
```

**JSONLReader Class:**
```python
class JSONLReader:
    @staticmethod
    def tail(filepath, n_lines=100):
        """Efficiently read last N lines"""
        if not os.path.exists(filepath):
            return []

        file_size = os.path.getsize(filepath)
        if file_size == 0:
            return []

        # Estimate bytes needed (avg line ~200 bytes, read 50% extra)
        seek_size = min(n_lines * 300, file_size)

        with open(filepath, 'rb') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                f.seek(-seek_size, os.SEEK_END)
                data = f.read().decode('utf-8', errors='ignore')
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        lines = data.split('\n')
        valid_lines = []

        for line in reversed(lines):
            if len(valid_lines) >= n_lines:
                break
            line = line.strip()
            if not line:
                continue
            try:
                valid_lines.append(json.loads(line))
            except json.JSONDecodeError:
                # Skip malformed lines
                continue

        return list(reversed(valid_lines))

    @staticmethod
    def read_all(filepath, max_lines=10000):
        """Read all lines with safety limit"""
        if not os.path.exists(filepath):
            return []

        lines = []
        with open(filepath, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                for line_num, line in enumerate(f, 1):
                    if line_num > max_lines:
                        logger.warning(f"Log exceeds {max_lines} lines, truncating")
                        break

                    line = line.strip()
                    if not line:
                        continue

                    try:
                        lines.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        # Include parse error
                        lines.append({
                            "type": "parse_error",
                            "line_number": line_num,
                            "error": str(e),
                            "raw_content": line[:200]
                        })
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        return lines
```

---

## 5. TEST SCENARIOS

### 5.1 Unit Tests

```python
def test_incomplete_json_line():
    """Agent crashes mid-write"""
    with open(log_file, 'w') as f:
        f.write('{"valid": "line1"}\n')
        f.write('{"incomplete": "line')  # No closing }
        f.write('\n{"valid": "line2"}\n')

    lines = JSONLReader.read_all(log_file)
    assert len(lines) == 3  # 2 valid + 1 error
    assert lines[0]['valid'] == 'line1'
    assert lines[1]['type'] == 'parse_error'
    assert lines[2]['valid'] == 'line2'

def test_concurrent_writers():
    """Multiple processes writing simultaneously"""
    import multiprocessing

    def write_lines(filepath, prefix, count):
        writer = JSONLWriter(filepath)
        for i in range(count):
            writer.append({"source": prefix, "line": i})

    processes = [
        multiprocessing.Process(target=write_lines, args=(log_file, f"proc{i}", 100))
        for i in range(5)
    ]

    for p in processes:
        p.start()
    for p in processes:
        p.join()

    lines = JSONLReader.read_all(log_file)
    assert len(lines) == 500  # 5 processes * 100 lines
    # Verify no corrupted lines
    assert all('source' in line and 'line' in line for line in lines)

def test_disk_full():
    """Simulate disk full scenario"""
    # Create small loop device or use ulimit
    # (Implementation depends on test environment)
    pass

def test_large_log_tail_performance():
    """Verify tail is efficient on large logs"""
    # Generate 1M line log (simulate)
    import time

    start = time.time()
    lines = JSONLReader.tail(large_log_file, 100)
    elapsed = time.time() - start

    assert len(lines) == 100
    assert elapsed < 0.1  # Must complete in <100ms

def test_read_while_writing():
    """Reader and writer concurrently accessing file"""
    import threading

    writer = JSONLWriter(log_file)
    results = {'read_errors': 0}

    def continuous_write():
        for i in range(1000):
            writer.append({"line": i})
            time.sleep(0.001)

    def continuous_read():
        for _ in range(100):
            try:
                lines = JSONLReader.tail(log_file, 10)
            except Exception as e:
                results['read_errors'] += 1
            time.sleep(0.01)

    writer_thread = threading.Thread(target=continuous_write)
    reader_thread = threading.Thread(target=continuous_read)

    writer_thread.start()
    reader_thread.start()

    writer_thread.join()
    reader_thread.join()

    assert results['read_errors'] == 0  # No read errors
```

### 5.2 Integration Tests

```bash
# Test 1: Agent crash mid-stream
./test_agent_crash.sh

# Test 2: Disk full
./test_disk_full.sh

# Test 3: Large log performance
./test_large_log.sh

# Test 4: Permission issues
./test_permissions.sh

# Test 5: Concurrent agents
./test_concurrent_agents.sh
```

---

## 6. IMPLEMENTATION CHECKLIST

- [ ] Implement `JSONLWriter` class with file locking
- [ ] Implement `JSONLReader` class with tail support
- [ ] Add signal handlers for graceful shutdown
- [ ] Implement disk space checks
- [ ] Add error recovery for malformed lines
- [ ] Add fallback to tmux if JSONL fails
- [ ] Update `deploy_headless_agent()` to create log file
- [ ] Update `get_agent_output()` to read JSONL
- [ ] Add unit tests for edge cases
- [ ] Add integration tests
- [ ] Document API changes
- [ ] Add monitoring for disk space
- [ ] Consider log rotation policy

---

## 7. OPEN QUESTIONS

1. **Log retention policy:** How long to keep logs? Auto-cleanup after N days?
2. **Compression:** Should old logs be gzipped?
3. **Log aggregation:** Should all agent logs be aggregated into single file per task?
4. **Structured logging:** What fields are mandatory in each JSONL record?
5. **Performance monitoring:** What metrics to track (write latency, file size, etc.)?

---

## 8. REFERENCES

- Current implementation: real_mcp_server.py:194-205 (tmux capture)
- Current implementation: real_mcp_server.py:1636-1697 (get_agent_output)
- JSONL spec: https://jsonlines.org/
- File locking: https://docs.python.org/3/library/fcntl.html
- POSIX atomic operations: https://man7.org/linux/man-pages/man2/write.2.html

---

**END OF ANALYSIS**
