# Current Agent Deployment & Output Capture Implementation Analysis

**Analyzed by:** current_implementation_investigator-215637-4722d7
**Date:** 2025-10-17
**File:** real_mcp_server.py

---

## Executive Summary

The current implementation deploys agents in tmux sessions running Claude CLI with `--output-format stream-json`, but **DOES NOT CAPTURE OR PERSIST** this structured output. Instead, it uses `tmux capture-pane` which only captures the visible terminal buffer (~2000 lines), losing all history when the buffer scrolls.

**CRITICAL LIMITATION:** No persistent logging exists - agent conversation history is lost forever once tmux buffer scrolls.

---

## 1. Current Deployment Flow (deploy_headless_agent)

### Location
- **Function:** `deploy_headless_agent`
- **Line:** 1201-1498 in real_mcp_server.py

### How It Works

1. **Validates prerequisites:**
   - Check tmux available (line 1219)
   - Find task workspace (line 1227)
   - Check agent spawn limits (lines 1241-1251)

2. **Generates agent identity:**
   ```python
   agent_id = f"{agent_type}-{datetime.now().strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"
   session_name = f"agent_{agent_id}"
   ```
   - Line 1254-1255

3. **Constructs Claude command:**
   ```bash
   cd '{calling_project_dir}' && {claude_executable} {claude_flags} '{agent_prompt}'
   ```
   - Line 1392-1397
   - **Claude flags:** `--print --output-format stream-json --verbose --dangerously-skip-permissions --model sonnet`
   - **Output format:** Claude produces JSONL stream (newline-delimited JSON)

4. **Creates tmux session:**
   - Calls `create_tmux_session()` (line 1400-1404)
   - Command: `tmux new-session -d -s {session_name} -c {working_dir} {claude_command}`
   - Location: real_mcp_server.py:154-192

5. **Updates registries:**
   - Task agent registry (lines 1436-1447)
   - Global agent registry (lines 1449-1466)
   - Deployment log (lines 1469-1480)

---

## 2. Current Output Capture (get_agent_output)

### Location
- **Function:** `get_agent_output`
- **Line:** 1636-1697 in real_mcp_server.py

### How It Works

1. **Validates agent:**
   - Find task workspace (line 1648)
   - Load agent registry (line 1657)
   - Find agent by ID (lines 1661-1665)

2. **Checks tmux session:**
   - Verify session exists (line 1681)
   - If terminated, return "Agent session has terminated" (lines 1682-1687)

3. **Captures output:**
   ```python
   output = get_tmux_session_output(session_name)
   ```
   - Line 1689
   - Calls `get_tmux_session_output()` at line 194

### get_tmux_session_output Implementation

**Location:** real_mcp_server.py:194-205

```python
def get_tmux_session_output(session_name: str) -> str:
    """Capture output from tmux session"""
    try:
        result = subprocess.run([
            'tmux', 'capture-pane', '-t', session_name, '-p'
        ], capture_output=True, text=True)

        if result.returncode == 0:
            return result.stdout
        return f"Error capturing output: {result.stderr}"
    except Exception as e:
        return f"Exception capturing output: {str(e)}"
```

**Command:** `tmux capture-pane -t {session_name} -p`

---

## 3. CRITICAL LIMITATIONS

### 3.1 NO PERSISTENCE
- `tmux capture-pane` only captures **visible pane buffer**
- Tmux default buffer: ~2000 lines (can be configured, but still finite)
- **Once buffer scrolls, old output is LOST FOREVER**
- No file-based logging exists

### 3.2 STRUCTURED OUTPUT IGNORED
- Claude produces `--output-format stream-json` (JSONL)
- Each line is a JSON object with structured data
- We capture it as **plain text** via tmux
- Cannot parse, filter, or query structured events

### 3.3 NO TAIL FUNCTIONALITY
- `get_agent_output()` always returns ENTIRE buffer
- No way to get "last N lines"
- No filtering or pagination

### 3.4 NO OUTPUT HISTORY
- Can only see what's currently in tmux buffer
- Cannot retrieve historical output after buffer scrolls
- Cannot debug completed agents

---

## 4. Claude Stream-JSON Output Format

Based on Claude CLI flags (line 1393), agents produce:

```jsonl
{"type": "message_start", "message": {...}}
{"type": "content_block_start", "index": 0, "content_block": {...}}
{"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "..."}}
{"type": "content_block_stop", "index": 0}
{"type": "message_delta", "delta": {...}, "usage": {...}}
{"type": "message_stop"}
```

**This structured data is currently WASTED** - we just capture it as text.

---

## 5. Current Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ deploy_headless_agent (line 1201)                          │
├─────────────────────────────────────────────────────────────┤
│ 1. Generate agent_id                                        │
│ 2. Build Claude command with --output-format stream-json   │
│ 3. Create tmux session: tmux new-session -d -s agent_X ... │
│ 4. Update registries                                        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
            ┌────────────────┐
            │  Tmux Session  │
            │  (Claude CLI)  │
            │                │
            │  Produces:     │
            │  JSONL stream  │
            │  (structured)  │
            └────────┬───────┘
                     │
                     │ Output goes to tmux buffer
                     │ (finite, ~2000 lines)
                     │ OLD OUTPUT LOST WHEN SCROLLED
                     │
                     ▼
        ┌────────────────────────────┐
        │ get_agent_output (line 1636)│
        ├────────────────────────────┤
        │ tmux capture-pane -p       │
        │ Returns: visible buffer    │
        │          as plain text     │
        └────────────────────────────┘
```

---

## 6. What Needs to Change

### 6.1 Add Persistent JSONL Logging
- **Where:** Modify `deploy_headless_agent` (line 1397)
- **How:** Pipe Claude output to log file
- **Command change:**
  ```bash
  OLD: cd '{dir}' && claude {flags} '{prompt}'
  NEW: cd '{dir}' && claude {flags} '{prompt}' | tee {workspace}/logs/{agent_id}_stream.jsonl
  ```
- **Log location:** `.agent-workspace/TASK-XXX/logs/{agent_id}_stream.jsonl`

### 6.2 Modify get_agent_output
- **Where:** Line 1636-1697
- **Add parameters:**
  - `tail: int = None` - Return last N lines
  - `filter: str = None` - Regex filter
  - `format: str = "text"` - Output format (text/json/jsonl)
- **Read from:** JSONL log file instead of tmux
- **Fallback:** If log doesn't exist, use tmux capture-pane (backward compat)

### 6.3 Handle Edge Cases
- Incomplete JSONL lines (agent crash mid-stream)
- Concurrent access to log file
- Log file rotation/cleanup
- Tmux session terminated but log exists
- Log file corrupted

---

## 7. Implementation Locations Summary

| Component | Location | Lines | Purpose |
|-----------|----------|-------|---------|
| `deploy_headless_agent` | real_mcp_server.py | 1201-1498 | Deploy agent in tmux |
| `create_tmux_session` | real_mcp_server.py | 154-192 | Create tmux session |
| `get_agent_output` | real_mcp_server.py | 1636-1697 | Get agent output |
| `get_tmux_session_output` | real_mcp_server.py | 194-205 | Capture tmux buffer |
| Claude command construction | real_mcp_server.py | 1392-1397 | Build CLI command |
| Claude flags | real_mcp_server.py | 1393 | `--output-format stream-json` |

---

## 8. Recommendations

1. **PRIORITY 1:** Add `| tee {log_file}` to Claude command (line 1397)
2. **PRIORITY 2:** Modify `get_agent_output` to read from log file
3. **PRIORITY 3:** Add tail, filter, format parameters
4. **PRIORITY 4:** Handle edge cases (incomplete lines, crashes)
5. **PRIORITY 5:** Add log cleanup/rotation mechanism

---

## 9. Key Code Snippets

### Current Claude Command (line 1392-1397)
```python
escaped_prompt = agent_prompt.replace("'", "'\"'\"'")
claude_command = f"cd '{calling_project_dir}' && {claude_executable} {claude_flags} '{escaped_prompt}'"
```

### Proposed Change
```python
log_file = f"{workspace}/logs/{agent_id}_stream.jsonl"
os.makedirs(f"{workspace}/logs", exist_ok=True)
claude_command = f"cd '{calling_project_dir}' && {claude_executable} {claude_flags} '{escaped_prompt}' | tee '{log_file}'"
```

### Current Output Capture (line 194-205)
```python
def get_tmux_session_output(session_name: str) -> str:
    result = subprocess.run([
        'tmux', 'capture-pane', '-t', session_name, '-p'
    ], capture_output=True, text=True)
    return result.stdout
```

### Proposed Change
```python
def get_agent_output_from_log(agent_id: str, workspace: str, tail: int = None, filter: str = None) -> str:
    log_file = f"{workspace}/logs/{agent_id}_stream.jsonl"
    if not os.path.exists(log_file):
        return None  # Fallback to tmux

    lines = []
    with open(log_file, 'r') as f:
        for line in f:
            if filter and not re.search(filter, line):
                continue
            lines.append(line)

    if tail:
        lines = lines[-tail:]

    return ''.join(lines)
```

---

## 10. Completion Criteria

This investigation is COMPLETE when:
- [x] Analyzed deploy_headless_agent implementation
- [x] Analyzed get_agent_output implementation
- [x] Identified current limitations
- [x] Documented code locations with line numbers
- [x] Provided flow diagram
- [x] Recommended implementation changes
- [x] Documented findings in workspace

**STATUS:** ✅ COMPLETE
