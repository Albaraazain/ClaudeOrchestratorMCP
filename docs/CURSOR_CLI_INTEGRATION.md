# Cursor CLI Integration Plan

## Investigation Summary

### Overview
This document outlines the findings from investigating Cursor CLI and provides a comprehensive plan for integrating it with the Claude Orchestrator MCP server.

Date: October 31, 2025  
Cursor Agent Version: 2025.10.28-0a91dc2

---

## 1. Cursor CLI Architecture

### 1.1 Installation & Setup
```bash
curl https://cursor.com/install -fsSL | bash
# Installs to: ~/.local/bin/cursor-agent
```

### 1.2 Core Features

#### Command Structure
```bash
cursor-agent [options] [command] [prompt...]

Key Options:
  -p, --print                  Non-interactive mode (for scripts/automation)
  --output-format <format>     text | json | stream-json (default: text)
  --stream-partial-output      Stream partial output as individual deltas
  --model <model>              Specify model (e.g., gpt-5, sonnet-4, sonnet-4-thinking)
  --resume [chatId]            Resume a chat session
  -f, --force                  Force allow commands unless explicitly denied
  --approve-mcps               Auto-approve all MCP servers (headless mode)
```

#### Key Commands
- `agent [prompt]` - Start the agent
- `create-chat` - Create new empty chat and return ID
- `resume` - Resume latest chat session
- `ls` - List/resume chat sessions
- `status` - View authentication status

---

## 2. Output Formats

### 2.1 JSON Format (`--output-format json`)
**Use Case**: Single-request automation, scripts, CI/CD

**Structure**: Single JSON object emitted upon completion
```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "duration_ms": 12028,
  "duration_api_ms": 12028,
  "result": "\n4",
  "session_id": "782e7405-03c2-462b-8913-0d133301cc25",
  "request_id": "2edbfa10-281c-41ae-a3a9-32dd48c98745"
}
```

### 2.2 Stream-JSON Format (`--output-format stream-json`)
**Use Case**: Real-time monitoring, progress tracking, streaming logs

**Structure**: Newline-delimited JSON (NDJSON) events

#### Event Types:

##### System Initialization
```json
{
  "type": "system",
  "subtype": "init",
  "apiKeySource": "login",
  "cwd": "/path/to/working/directory",
  "session_id": "7eb8aa87-7951-47b7-84b4-76ea77e6ecf0",
  "model": "Auto",
  "permissionMode": "default"
}
```

##### User Message
```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [{"type": "text", "text": "Create a Python file"}]
  },
  "session_id": "7eb8aa87-7951-47b7-84b4-76ea77e6ecf0"
}
```

##### Thinking Deltas
```json
{
  "type": "thinking",
  "subtype": "delta",
  "text": "",
  "session_id": "7eb8aa87-7951-47b7-84b4-76ea77e6ecf0",
  "timestamp_ms": 1761925201790
}
```

##### Assistant Message
```json
{
  "type": "assistant",
  "message": {
    "role": "assistant",
    "content": [{"type": "text", "text": "Creating hello.py..."}]
  },
  "session_id": "7eb8aa87-7951-47b7-84b4-76ea77e6ecf0",
  "model_call_id": "ff9e5956-6f34-4f51-aff7-5154dc94b0d5",
  "timestamp_ms": 1761925221722
}
```

##### Tool Call - Started
```json
{
  "type": "tool_call",
  "subtype": "started",
  "call_id": "tool_24d8e8ec-1837-4307-bc6f-a9c5817003a",
  "tool_call": {
    "editToolCall": {
      "args": {"path": "/path/to/file.py"}
    }
  },
  "model_call_id": "ff9e5956-6f34-4f51-aff7-5154dc94b0d5",
  "session_id": "7eb8aa87-7951-47b7-84b4-76ea77e6ecf0",
  "timestamp_ms": 1761925221723
}
```

##### Tool Call - Completed
```json
{
  "type": "tool_call",
  "subtype": "completed",
  "call_id": "tool_24d8e8ec-1837-4307-bc6f-a9c5817003a",
  "tool_call": {
    "editToolCall": {
      "args": {"path": "/path/to/file.py"},
      "result": {
        "success": {
          "path": "/path/to/file.py",
          "resultForModel": "Wrote contents to file",
          "linesAdded": 1,
          "linesRemoved": 1,
          "diffString": "- \n+ print('Hello World')",
          "afterFullFileContent": "print('Hello World')"
        }
      }
    }
  },
  "model_call_id": "ff9e5956-6f34-4f51-aff7-5154dc94b0d5",
  "session_id": "7eb8aa87-7951-47b7-84b4-76ea77e6ecf0",
  "timestamp_ms": 1761925222276
}
```

##### Shell Tool Call
```json
{
  "type": "tool_call",
  "subtype": "completed",
  "call_id": "tool_465ff957-1737-43dd-b78f-5c4f829706a",
  "tool_call": {
    "shellToolCall": {
      "args": {
        "command": "python hello.py",
        "workingDirectory": "",
        "timeout": 300000,
        "toolCallId": "tool_465ff957-1737-43dd-b78f-5c4f829706a",
        "simpleCommands": ["python"],
        "hasInputRedirect": false,
        "hasOutputRedirect": false
      },
      "result": {
        "success": {
          "command": "python hello.py",
          "exitCode": 0,
          "stdout": "Hello World\n",
          "stderr": "",
          "executionTime": 221
        }
      }
    }
  },
  "session_id": "7eb8aa87-7951-47b7-84b4-76ea77e6ecf0",
  "timestamp_ms": 1761925231235
}
```

##### Final Result
```json
{
  "type": "result",
  "subtype": "success",
  "duration_ms": 20485,
  "duration_api_ms": 20485,
  "is_error": false,
  "result": "Created hello.py with code that prints 'Hello World'...",
  "session_id": "7eb8aa87-7951-47b7-84b4-76ea77e6ecf0",
  "request_id": "fb4d8fce-88b7-4113-8647-d6b6997e3d2a"
}
```

---

## 3. Storage Structure

### 3.1 Configuration Files

#### Global Config: `~/.cursor/cli-config.json`
```json
{
  "permissions": {
    "allow": ["Shell(ls)"],
    "deny": []
  },
  "version": 1,
  "editor": {
    "vimMode": false
  },
  "model": {
    "modelId": "default",
    "displayModelId": "auto",
    "displayName": "Auto",
    "displayNameShort": "Auto",
    "aliases": ["auto"]
  },
  "hasChangedDefaultModel": true,
  "privacyCache": {
    "ghostMode": true,
    "privacyMode": 2,
    "updatedAt": 1761925216933
  },
  "network": {
    "useHttp1ForAgent": false
  }
}
```

#### Project Config: `<project>/.cursor/cli.json`
Project-specific permissions and settings

### 3.2 Chat Storage

#### Directory Structure
```
~/.cursor/chats/
├── {project_hash}/
│   └── {session_id}/
│       ├── store.db          # SQLite database
│       ├── store.db-shm      # Shared memory file
│       └── store.db-wal      # Write-ahead log
```

#### Database Schema
```sql
CREATE TABLE blobs (
    id TEXT PRIMARY KEY,
    data BLOB
);

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

#### Meta Table Example (hex-decoded):
```json
{
  "agentId": "7eb8aa87-7951-47b7-84b4-76ea77e6ecf0",
  "latestRootBlobId": "3f8f1f1dd9144123d9a1a53fbc6efd51...",
  "name": "New Agent",
  "mode": "auto-run",
  "createdAt": 1761925214886
}
```

---

## 4. Comparison: Current System vs Cursor CLI

### 4.1 Current Claude Orchestrator System

**Deployment Method:**
- Uses `tmux` sessions for background execution
- Runs `claude` CLI with custom flags
- Pipes output to JSONL log files

**Logging:**
- Custom JSONL format
- Manual parsing and event extraction
- Separate files for progress, findings, logs

**Session Management:**
- tmux-based: kill sessions, attach, capture panes
- Registry-based tracking in JSON files
- Custom agent lifecycle management

**Tool Invocation:**
```bash
cd {workspace} && tmux new-session -d -s {session_name} \
  'claude {flags} "{prompt}" > {log_file} 2>&1'
```

### 4.2 Cursor CLI System

**Deployment Method:**
- Native non-interactive mode (`--print`)
- Background execution via `&` or process management
- Built-in session management

**Logging:**
- Structured JSON/NDJSON output
- Rich event types (thinking, tool calls, results)
- Real-time streaming support

**Session Management:**
- Built-in session IDs and resumption
- SQLite-based chat persistence
- Native `--resume` functionality

**Tool Invocation:**
```bash
cursor-agent -p "prompt" \
  --output-format stream-json \
  --force \
  --approve-mcps \
  > output.jsonl 2>&1 &
```

---

## 5. Integration Strategy

### 5.1 Proposed Architecture

#### Option 1: Dual Mode Support (RECOMMENDED)
Add configuration option to choose between `claude` CLI and `cursor-agent`:

```python
AGENT_BACKEND = os.getenv('CLAUDE_ORCHESTRATOR_BACKEND', 'claude')  # 'claude' or 'cursor'
```

**Benefits:**
- Backward compatibility
- Gradual migration path
- User choice based on needs

#### Option 2: Cursor CLI Only
Replace tmux+claude with cursor-agent entirely

**Benefits:**
- Cleaner codebase
- Better structured output
- Native session management

**Drawbacks:**
- Breaking change
- Requires cursor-agent installation

### 5.2 Implementation Plan

#### Phase 1: Core Integration (PRIORITY)

1. **Add Cursor Agent Detection**
   ```python
   def check_cursor_agent_available() -> bool:
       """Check if cursor-agent is installed and accessible"""
   ```

2. **Create Cursor Agent Wrapper**
   ```python
   def deploy_cursor_agent(
       task_id: str,
       agent_type: str,
       prompt: str,
       parent: str = "orchestrator"
   ) -> Dict[str, Any]:
       """Deploy agent using cursor-agent instead of tmux+claude"""
   ```

3. **Add Stream-JSON Parser**
   ```python
   def parse_cursor_stream_jsonl(log_file: str) -> Dict[str, Any]:
       """Parse cursor-agent stream-json output"""
       # Extract:
       # - Thinking deltas
       # - Tool calls (with args and results)
       # - Assistant messages
       # - Final result
       # - Session metadata
   ```

4. **Adapt get_agent_output()**
   - Detect log format (cursor vs claude)
   - Parse accordingly
   - Normalize output structure

#### Phase 2: Session Management

1. **Add Session Resume Support**
   ```python
   def resume_cursor_session(session_id: str, additional_prompt: str) -> str:
       """Resume a cursor-agent session with new prompt"""
   ```

2. **Session Registry Integration**
   - Store `session_id` in agent registry
   - Track cursor chat database paths
   - Enable multi-turn conversations

#### Phase 3: Enhanced Features

1. **Tool Call Extraction**
   - Parse `editToolCall` events for file changes
   - Parse `shellToolCall` events for command execution
   - Extract execution times and results

2. **Thinking Visibility**
   - Capture thinking deltas
   - Display internal reasoning
   - Debug mode for thought process

3. **Model Selection**
   - Support `--model` flag
   - Per-agent model configuration
   - Auto model selection based on task type

#### Phase 4: Configuration & Documentation

1. **Environment Variables**
   ```bash
   CLAUDE_ORCHESTRATOR_BACKEND=cursor     # 'claude' or 'cursor'
   CURSOR_AGENT_PATH=/path/to/cursor-agent
   CURSOR_AGENT_MODEL=sonnet-4
   CURSOR_AGENT_FLAGS=--approve-mcps --force
   ```

2. **Configuration File Support**
   - Project-specific `.cursor/cli.json`
   - Permission management
   - Model preferences

3. **Documentation Updates**
   - Installation instructions
   - Migration guide (claude → cursor)
   - Comparison table
   - Usage examples

---

## 6. Key Implementation Details

### 6.1 Log Format Compatibility

**Current JSONL Format (claude):**
```jsonl
{"timestamp": "...", "level": "info", "message": "..."}
```

**Cursor Stream-JSON Format:**
```jsonl
{"type": "assistant", "message": {...}, "session_id": "...", "timestamp_ms": 123}
```

**Solution:** Normalize both formats to common structure:
```python
def normalize_log_entry(entry: Dict[str, Any], source: str) -> Dict[str, Any]:
    """Normalize log entry from claude or cursor format"""
    if source == "cursor":
        return {
            "timestamp": entry.get("timestamp_ms", 0) / 1000,
            "type": entry.get("type"),
            "subtype": entry.get("subtype"),
            "content": extract_cursor_content(entry),
            "session_id": entry.get("session_id"),
            "metadata": entry
        }
    elif source == "claude":
        # Existing parsing logic
        pass
```

### 6.2 Process Management

**Current (tmux):**
```python
subprocess.run([
    "tmux", "new-session", "-d", "-s", session_name,
    f"cd {workspace} && claude {flags} '{prompt}' > {log} 2>&1"
])
```

**New (cursor-agent):**
```python
process = subprocess.Popen(
    [
        "cursor-agent", "-p", prompt,
        "--output-format", "stream-json",
        "--force",
        "--approve-mcps",
        "--model", model
    ],
    cwd=workspace,
    stdout=open(log_file, 'w'),
    stderr=subprocess.STDOUT,
    start_new_session=True  # Detach from parent
)

# Store PID in registry
registry["agents"][agent_id]["pid"] = process.pid
```

### 6.3 Session Resume Flow

```python
def handle_agent_resume(task_id: str, agent_id: str, new_prompt: str):
    """Resume a cursor-agent session with additional prompt"""
    
    # Get session_id from registry
    registry = load_registry(task_id)
    agent = next(a for a in registry["agents"] if a["id"] == agent_id)
    session_id = agent.get("session_id")
    
    if not session_id:
        return {"error": "Agent has no resumable session"}
    
    # Resume with new prompt
    process = subprocess.Popen(
        [
            "cursor-agent", "-p", new_prompt,
            "--resume", session_id,
            "--output-format", "stream-json",
            "--force"
        ],
        cwd=workspace,
        stdout=open(log_file, 'a'),  # Append to existing log
        stderr=subprocess.STDOUT
    )
    
    return {"success": True, "pid": process.pid}
```

---

## 7. Testing Plan

### 7.1 Unit Tests

```python
# test_cursor_cli_integration.py

def test_cursor_agent_detection():
    """Test cursor-agent binary detection"""
    assert check_cursor_agent_available() in [True, False]

def test_stream_json_parsing():
    """Test parsing cursor stream-json output"""
    sample_log = """
    {"type":"system","subtype":"init","session_id":"abc123"}
    {"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"}]}}
    {"type":"result","subtype":"success","result":"Done"}
    """
    events = parse_cursor_stream_jsonl(sample_log)
    assert len(events) == 3
    assert events[0]["type"] == "system"
    assert events[-1]["type"] == "result"

def test_tool_call_extraction():
    """Test extracting tool calls from cursor logs"""
    log_entry = {
        "type": "tool_call",
        "subtype": "completed",
        "tool_call": {
            "shellToolCall": {
                "args": {"command": "ls -la"},
                "result": {"success": {"stdout": "file.txt"}}
            }
        }
    }
    tool_info = extract_tool_call_info(log_entry)
    assert tool_info["tool_type"] == "shell"
    assert tool_info["command"] == "ls -la"
    assert tool_info["success"] == True
```

### 7.2 Integration Tests

1. **Deploy Agent Test**
   - Deploy agent using cursor-agent
   - Verify log file created
   - Verify stream-json format
   - Check session_id in registry

2. **Get Output Test**
   - Deploy cursor-agent
   - Wait for completion
   - Call get_agent_output()
   - Verify parsed results

3. **Session Resume Test**
   - Create initial session
   - Complete task
   - Resume with new prompt
   - Verify continuation

4. **Multi-Agent Test**
   - Deploy 3 cursor-agents
   - Verify concurrent execution
   - Check all logs parsed correctly

### 7.3 Manual Testing

```bash
# Test 1: Simple task
curl-agent -p "What is 2+2?" --output-format json

# Test 2: File operations
cursor-agent -p "Create test.py with hello world" \
  --output-format stream-json --force > test_stream.jsonl

# Test 3: Complex task with tool calls
cursor-agent -p "Analyze this Python file and suggest improvements" \
  --output-format stream-json --force > analysis.jsonl

# Verify log parsing
cat test_stream.jsonl | jq -c 'select(.type == "tool_call")'
```

---

## 8. Migration Guide

### 8.1 For Users

**Current Usage (tmux + claude):**
```bash
export CLAUDE_ORCHESTRATOR_BACKEND=claude
# Works as before
```

**New Usage (cursor-agent):**
```bash
# Install cursor-agent
curl https://cursor.com/install -fsSL | bash

# Switch backend
export CLAUDE_ORCHESTRATOR_BACKEND=cursor

# Use orchestrator normally
```

### 8.2 Configuration Changes

**Add to `.env` or environment:**
```bash
# Backend selection
CLAUDE_ORCHESTRATOR_BACKEND=cursor

# Cursor-specific settings
CURSOR_AGENT_PATH=/Users/yourname/.local/bin/cursor-agent
CURSOR_AGENT_MODEL=sonnet-4
CURSOR_AGENT_FLAGS="--approve-mcps --force"
CURSOR_ENABLE_THINKING_LOGS=true
```

### 8.3 Breaking Changes

**None initially** - dual mode support maintains compatibility

**Future (optional):**
- Deprecate tmux backend
- Make cursor-agent default
- Remove tmux dependencies

---

## 9. Benefits of Integration

### 9.1 Immediate Benefits

1. **Richer Logging**
   - Structured JSON events
   - Thinking process visibility
   - Detailed tool call tracking

2. **Better Session Management**
   - Native resume support
   - SQLite-backed persistence
   - Multi-turn conversations

3. **Improved Debugging**
   - Clear event types
   - Timestamp tracking
   - Tool execution details

### 9.2 Long-term Benefits

1. **Reduced Complexity**
   - Eliminate tmux dependency
   - Simpler deployment code
   - Native process management

2. **Enhanced Features**
   - Model selection per agent
   - Permission management
   - Browser automation support

3. **Better Integration**
   - Cursor IDE awareness
   - Project context
   - MCP server compatibility

---

## 10. Risks & Mitigation

### 10.1 Risks

1. **cursor-agent not installed**
   - Mitigation: Fallback to claude/tmux, clear error messages

2. **Different log format breaks parsing**
   - Mitigation: Robust parsing with error recovery, format detection

3. **Session resume issues**
   - Mitigation: Validate session_id before resume, handle failures gracefully

4. **Performance differences**
   - Mitigation: Benchmark both backends, make configurable

### 10.2 Testing Requirements

- Test on macOS, Linux
- Test with/without cursor-agent installed
- Test backward compatibility with existing logs
- Test concurrent agent deployment
- Test session resume edge cases

---

## 11. Implementation Checklist

### Phase 1: Core (Week 1)
- [ ] Add cursor-agent detection function
- [ ] Implement deploy_cursor_agent()
- [ ] Add stream-json parser
- [ ] Update get_agent_output() for cursor logs
- [ ] Add AGENT_BACKEND config option
- [ ] Write unit tests for parsing

### Phase 2: Enhanced (Week 2)
- [ ] Implement session resume
- [ ] Add tool call extraction
- [ ] Add thinking log capture
- [ ] Update registry schema for session_id
- [ ] Write integration tests

### Phase 3: Polish (Week 3)
- [ ] Add model selection support
- [ ] Implement permission management
- [ ] Add error recovery for failed sessions
- [ ] Performance benchmarking
- [ ] Documentation updates

### Phase 4: Production (Week 4)
- [ ] Full test suite passing
- [ ] Migration guide written
- [ ] Example configurations
- [ ] Release notes
- [ ] User feedback collection

---

## 12. Next Steps

1. **Immediate Actions:**
   - Review this plan with stakeholders
   - Set up test environment with cursor-agent
   - Create feature branch for development
   - Start Phase 1 implementation

2. **Questions to Resolve:**
   - Should cursor-agent be mandatory or optional?
   - What's the deprecation timeline for tmux backend?
   - Do we need to support both long-term?
   - What's the preferred default?

3. **Resources Needed:**
   - cursor-agent installation on CI/CD
   - Test accounts for cursor authentication
   - Sample projects for integration testing
   - Performance testing infrastructure

---

## Conclusion

Cursor CLI offers significant improvements over the current tmux+claude approach:
- **Better structure** in logs (NDJSON with event types)
- **Native session management** with resume support
- **Richer metadata** including thinking, tool calls, timing
- **Simpler deployment** with built-in non-interactive mode

The dual-mode approach provides a smooth migration path while maintaining backward compatibility. Implementation can be incremental, with Phase 1 providing immediate value and later phases adding advanced features.

**Recommendation:** Proceed with Phase 1 implementation, targeting dual-mode support with cursor-agent as an optional backend.

