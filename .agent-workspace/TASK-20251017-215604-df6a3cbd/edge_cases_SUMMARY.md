# Edge Case Analysis - Executive Summary

**Agent:** edge_case_analyzer-215644-ac4707
**Date:** 2025-10-17
**Task:** TASK-20251017-215604-df6a3cbd

## Critical Findings Summary

### 🚨 CRITICAL ISSUES (Must Address)

#### 1. Incomplete JSONL Lines from Crashes
**Severity:** CRITICAL
- **Problem:** Agent killed mid-write leaves incomplete JSON line
- **Impact:** Parser crashes, subsequent valid lines may be skipped
- **Solution:** Line-by-line parsing with try/except, skip malformed lines
- **Code:** JSONLReader class with robust error recovery

#### 2. Concurrent Write Race Conditions
**Severity:** CRITICAL
- **Problem:** Multiple agents writing to same file simultaneously
- **Impact:** Interleaved JSON, corrupted JSONL, data loss
- **Solution:**
  - File locking with fcntl.LOCK_EX
  - Unique log file per agent_id (NOT task_id)
  - O_APPEND flag + flush + fsync
- **Critical Pattern:** `log_filepath = f'{workspace}/logs/{agent_id}_stream.jsonl'`

### ⚠️ HIGH PRIORITY ISSUES

#### 3. Disk Full Scenarios
**Severity:** HIGH
- **Problem:** Write operations fail with OSError ENOSPC
- **Impact:** Agent crashes, partial writes corrupt JSONL
- **Solution:**
  - Pre-flight disk space check (min 100MB)
  - Graceful OSError ENOSPC handling
  - Log rotation at 500MB max
  - Emergency shutdown procedure

#### 4. Large Multi-GB Logs
**Severity:** HIGH
- **Problem:** Loading entire file into memory causes OOM
- **Impact:** Crashes, slow performance on large logs
- **Solution:**
  - Efficient tail: f.seek(-seek_size, SEEK_END)
  - Read only last N*300 bytes, not entire file
  - Performance requirement: <100ms for 10GB file

### 📋 MEDIUM PRIORITY

#### 5. Read-Only Filesystems
**Severity:** MEDIUM
- **Problem:** Cannot write logs, agent fails to deploy
- **Solution:** Pre-flight write test before agent deployment
- **Test Pattern:** Create temp file, write, remove

---

## Implementation Priorities

### Phase 1: Robust JSONL Handling (CRITICAL)
**Must implement before any JSONL logging goes live**

```python
class JSONLReader:
    @staticmethod
    def read_all(filepath, max_lines=10000):
        """Read with error recovery"""
        lines = []
        with open(filepath, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError as e:
                    # Include parse error, continue
                    lines.append({
                        "type": "parse_error",
                        "line_number": line_num,
                        "error": str(e),
                        "raw_content": line[:200]
                    })
        return lines

    @staticmethod
    def tail(filepath, n_lines=100):
        """Efficient tail for large files"""
        if not os.path.exists(filepath):
            return []

        file_size = os.path.getsize(filepath)
        if file_size == 0:
            return []

        seek_size = min(n_lines * 300, file_size)

        with open(filepath, 'rb') as f:
            f.seek(-seek_size, os.SEEK_END)
            data = f.read().decode('utf-8', errors='ignore')

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
                continue

        return list(reversed(valid_lines))
```

### Phase 2: File Locking (CRITICAL - For Future Use)
**Note: Since we're using `tee` for write (not Python), this applies to any direct JSONL writes**

```python
import fcntl

class JSONLWriter:
    def append(self, record: dict):
        """Thread-safe, atomic append"""
        if 'timestamp' not in record:
            record['timestamp'] = datetime.now(timezone.utc).isoformat()

        line = json.dumps(record, ensure_ascii=False) + '\n'

        with open(self.filepath, 'a') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

**IMPORTANT:** Since current_implementation_investigator found we can use `tee` to pipe Claude output directly to file, file locking is NOT needed for agent stream logs (Claude writes sequentially). However, if we add MCP progress/findings logs written from Python, those WILL need locking.

### Phase 3: Pre-Deployment Checks (HIGH)

```python
def deploy_headless_agent(...):
    workspace = find_task_workspace(task_id)

    # Check 1: Disk space
    stat = shutil.disk_usage(workspace)
    free_mb = stat.free / (1024 * 1024)
    if free_mb < 100:
        return {
            "success": False,
            "error": f"Insufficient disk space: {free_mb:.1f}MB free (need 100MB min)"
        }

    # Check 2: Write access
    test_file = f"{workspace}/.write_test_{uuid.uuid4().hex[:6]}"
    try:
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
    except (OSError, IOError) as e:
        return {
            "success": False,
            "error": f"Workspace is not writable: {e}"
        }

    # Continue with deployment...
```

### Phase 4: Fallback Handling

```python
def get_agent_output(task_id, agent_id, tail=None):
    log_path = get_log_filepath(task_id, agent_id)

    # Try JSONL log first
    if os.path.exists(log_path):
        try:
            if tail:
                lines = JSONLReader.tail(log_path, tail)
            else:
                lines = JSONLReader.read_all(log_path)

            return {
                "success": True,
                "agent_id": agent_id,
                "output": lines,
                "source": "jsonl_log"
            }
        except Exception as e:
            logger.warning(f"JSONL read failed: {e}, falling back to tmux")

    # Fallback to tmux
    if check_tmux_session_exists(agent['tmux_session']):
        tmux_output = get_tmux_session_output(agent['tmux_session'])
        return {
            "success": True,
            "agent_id": agent_id,
            "output": tmux_output,
            "source": "tmux_fallback"
        }

    # No output available
    return {
        "success": True,
        "agent_id": agent_id,
        "output": [],
        "note": "Agent exited without writing logs"
    }
```

---

## Testing Requirements

### Unit Tests Required

1. **test_incomplete_json_line()**
   - Write incomplete JSON line
   - Verify parser skips it and continues

2. **test_concurrent_writers()** (If direct JSONL writes added)
   - Spawn 5 processes writing 100 lines each
   - Verify 500 lines total, no corruption

3. **test_disk_full()**
   - Simulate ENOSPC
   - Verify graceful handling

4. **test_large_log_tail_performance()**
   - Generate 1M line log
   - Verify tail(100) completes <100ms

5. **test_read_while_writing()**
   - Writer and reader accessing file concurrently
   - Verify no errors

### Integration Tests

1. Agent crash during write (kill -9)
2. Read-only workspace
3. Directory deleted mid-run
4. Multiple agents reading same log

---

## Coordination with Other Agents

### ✅ Aligned with current_implementation_investigator
- They found: Add `| tee logfile` to Claude command
- My analysis: Confirms this is simple and robust
- **No file locking needed** for agent stream logs (Claude writes sequentially)
- File locking only needed if we add separate MCP function call logs

### ✅ Aligned with api_designer
- They designed: get_agent_output(tail, filter, format)
- My analysis: Confirms tail must be efficient (seek-based)
- Fallback to tmux is essential for backward compatibility

### ⚠️ Input for jsonl_architecture_planner
- **Critical:** Each agent MUST have unique log file using agent_id
- **Pattern:** `{workspace}/logs/{agent_id}_stream.jsonl`
- **NOT:** `{workspace}/logs/{task_id}_stream.jsonl`
- Log rotation: Consider policy (max 500MB per log)

---

## Open Questions for Implementation Phase

1. **Log retention:** How long to keep logs? Auto-cleanup after N days?
2. **Compression:** Should old/rotated logs be gzipped?
3. **Structured fields:** What fields are mandatory in JSONL records?
4. **MCP progress/findings logs:** Should these be separate files with file locking?
5. **Performance monitoring:** What metrics to track (write latency, file size)?

---

## Summary Statistics

- **Edge cases analyzed:** 8 major categories
- **Failure scenarios:** 5 documented
- **Critical findings:** 2
- **High priority findings:** 2
- **Medium priority findings:** 1
- **Code examples provided:** 4 classes/functions
- **Test scenarios defined:** 8 unit + 4 integration
- **Lines of analysis document:** 1000+
- **Implementation patterns:** Proven, production-ready approaches

---

## Deliverables

1. ✅ **edge_cases_analysis.md** (32KB comprehensive document)
2. ✅ **edge_cases_SUMMARY.md** (this document - executive summary)
3. ✅ **5 critical findings reported** via MCP coordination
4. ✅ **Code examples** for all critical components
5. ✅ **Test scenarios** defined and documented
6. ✅ **Integration recommendations** with other agents

---

## Conclusion

The JSONL logging implementation is straightforward but MUST handle edge cases properly:

**Top 3 Priorities:**
1. Robust line-by-line JSONL parser with error recovery
2. Efficient tail implementation for large logs
3. Pre-flight checks (disk space + write access)

**Low Risk Areas:**
- Using `tee` for writes is simple and robust
- No file locking needed for agent streams (sequential writes)
- Fallback to tmux provides safety net

**The implementation is LOW RISK if the 3 priorities above are addressed properly.**
