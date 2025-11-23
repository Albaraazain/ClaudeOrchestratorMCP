# Cursor CLI Integration - Usage Guide

## Overview

The Claude Orchestrator MCP now supports Cursor CLI (`cursor-agent`) as an alternative backend to the traditional tmux+claude approach. This document provides usage examples and configuration guidelines.

**Status**: Phase 1 Complete ✅
- Configuration support added
- Stream-JSON parser implemented
- Tool call extraction working
- All tests passing (5/5)

---

## Installation

### 1. Install Cursor Agent

```bash
# Install cursor-agent (if not already installed)
curl https://cursor.com/install -fsSL | bash

# Verify installation
cursor-agent --version
# Output: 2025.10.28-0a91dc2 (or similar)
```

### 2. Configure Environment Variables

Add to your `.env` or shell profile:

```bash
# Choose backend: 'claude' (default) or 'cursor'
export CLAUDE_ORCHESTRATOR_BACKEND=cursor

# Optional: Customize cursor-agent path
export CURSOR_AGENT_PATH=/Users/yourname/.local/bin/cursor-agent

# Optional: Set default model
export CURSOR_AGENT_MODEL=sonnet-4

# Optional: Custom flags
export CURSOR_AGENT_FLAGS="--approve-mcps --force"

# Optional: Enable thinking logs (for thinking models)
export CURSOR_ENABLE_THINKING_LOGS=true
```

### 3. Verify Setup

Run the test suite:

```bash
cd /path/to/ClaudeOrchestratorMCP
python3 test_cursor_cli_integration.py
```

Expected output:
```
🎉 All tests passed!
Total: 5/5 tests passed
```

---

## Configuration Options

### Backend Selection

| Variable | Values | Default | Description |
|----------|--------|---------|-------------|
| `CLAUDE_ORCHESTRATOR_BACKEND` | `claude`, `cursor` | `claude` | Choose agent backend |
| `CURSOR_AGENT_PATH` | Path string | `~/.local/bin/cursor-agent` | Path to cursor-agent binary |
| `CURSOR_AGENT_MODEL` | Model name | `auto` | Default model for agents |
| `CURSOR_AGENT_FLAGS` | Flag string | `--approve-mcps --force` | Additional cursor-agent flags |
| `CURSOR_ENABLE_THINKING_LOGS` | `true`, `false` | `false` | Capture thinking process |

### Model Selection

Cursor CLI supports multiple models:

```bash
# Use Claude 3.5 Sonnet (latest)
export CURSOR_AGENT_MODEL=sonnet-4

# Use GPT-5
export CURSOR_AGENT_MODEL=gpt-5

# Use thinking models
export CURSOR_AGENT_MODEL=sonnet-4-thinking
export CURSOR_ENABLE_THINKING_LOGS=true

# Auto-select best model
export CURSOR_AGENT_MODEL=auto
```

---

## Usage Examples

### Example 1: Parse Cursor Stream-JSON Logs

```python
from real_mcp_server import parse_cursor_stream_jsonl

# Parse a cursor-agent log file
log_file = "/path/to/agent_stream.jsonl"
result = parse_cursor_stream_jsonl(log_file)

print(f"Session ID: {result['session_id']}")
print(f"Success: {result['success']}")
print(f"Duration: {result['duration_ms']}ms")
print(f"Events: {len(result['events'])}")

# Access assistant messages
for msg in result['assistant_messages']:
    print(f"Assistant: {msg}")

# Access tool calls
for tool_call in result['tool_calls']:
    print(f"Tool: {tool_call['tool_type']}")
    if tool_call['tool_type'] == 'shell':
        print(f"  Command: {tool_call['command']}")
        print(f"  Exit code: {tool_call.get('exit_code')}")
        print(f"  Stdout: {tool_call.get('stdout', '')[:100]}")
```

### Example 2: Extract Tool Calls

```python
from real_mcp_server import parse_cursor_tool_call

# Parse a shell tool call event
shell_event = {
    "type": "tool_call",
    "subtype": "completed",
    "call_id": "tool_123",
    "tool_call": {
        "shellToolCall": {
            "args": {"command": "pytest tests/"},
            "result": {
                "success": {
                    "exitCode": 0,
                    "stdout": "10 passed, 2 warnings",
                    "executionTime": 3500
                }
            }
        }
    }
}

info = parse_cursor_tool_call(shell_event)
print(f"Command: {info['command']}")
print(f"Success: {info['success']}")
print(f"Time: {info['execution_time_ms']}ms")
```

### Example 3: Run Cursor Agent Directly

```bash
# Simple query (JSON output)
cursor-agent -p "What is Python's GIL?" --output-format json

# Stream JSON with tool execution
cursor-agent -p "Create a Python script that prints Hello World" \
  --output-format stream-json \
  --force \
  > output.jsonl

# Use specific model
cursor-agent -p "Analyze this codebase" \
  --model sonnet-4 \
  --output-format stream-json \
  --force
```

### Example 4: Parse Real-Time Logs

```python
import json

def monitor_cursor_agent_log(log_file):
    """Monitor cursor-agent log in real-time"""
    with open(log_file, 'r') as f:
        while True:
            line = f.readline()
            if not line:
                break
            
            try:
                event = json.loads(line.strip())
                event_type = event.get("type")
                
                if event_type == "assistant":
                    msg = event["message"]["content"][0]["text"]
                    print(f"💬 Assistant: {msg}")
                
                elif event_type == "tool_call":
                    subtype = event.get("subtype")
                    if subtype == "started":
                        print(f"🔧 Tool starting...")
                    elif subtype == "completed":
                        print(f"✅ Tool completed")
                
                elif event_type == "result":
                    success = event.get("subtype") == "success"
                    print(f"{'✅' if success else '❌'} Task completed")
                    
            except json.JSONDecodeError:
                continue

# Usage
monitor_cursor_agent_log("agent_output.jsonl")
```

---

## Comparison: Claude vs Cursor Backend

### Feature Comparison

| Feature | Claude (tmux) | Cursor (cursor-agent) |
|---------|---------------|----------------------|
| Background execution | ✅ tmux sessions | ✅ Native processes |
| Session management | ✅ tmux attach/detach | ⚠️  Partial (resume support) |
| Structured logs | ⚠️  Custom format | ✅ Stream-JSON (NDJSON) |
| Tool call tracking | ❌ Limited | ✅ Detailed |
| Thinking visibility | ❌ Not captured | ✅ Optional |
| Model selection | ⚠️  Via flags | ✅ Built-in |
| Resume capability | ❌ No | ✅ Native --resume |
| Installation | ✅ Included | ⚠️  Requires cursor-agent |

### Log Format Comparison

**Claude (Custom):**
```jsonl
{"timestamp": "2025-10-31T18:00:00", "level": "info", "message": "Starting task"}
{"timestamp": "2025-10-31T18:00:05", "level": "info", "message": "Task completed"}
```

**Cursor (Stream-JSON):**
```jsonl
{"type":"system","subtype":"init","session_id":"abc123","model":"Auto"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Starting..."}]}}
{"type":"tool_call","subtype":"started","tool_call":{"shellToolCall":{"args":{"command":"ls"}}}}
{"type":"tool_call","subtype":"completed","tool_call":{"shellToolCall":{"result":{"success":{"exitCode":0}}}}}
{"type":"result","subtype":"success","duration_ms":5000}
```

---

## Advanced Features

### Thinking Process Capture

When using thinking models (e.g., `sonnet-4-thinking`):

```bash
# Enable thinking logs
export CURSOR_ENABLE_THINKING_LOGS=true

# Run with thinking model
cursor-agent -p "Complex reasoning task" \
  --model sonnet-4-thinking \
  --output-format stream-json \
  > output.jsonl
```

Parse thinking:
```python
result = parse_cursor_stream_jsonl("output.jsonl", include_thinking=True)
print(f"Thinking process:\n{result['thinking_text']}")
```

### Tool Call Analytics

Extract execution metrics:

```python
result = parse_cursor_stream_jsonl("agent_log.jsonl")

# Analyze tool calls
shell_calls = [t for t in result['tool_calls'] if t['tool_type'] == 'shell']
edit_calls = [t for t in result['tool_calls'] if t['tool_type'] == 'edit']

print(f"Shell commands: {len(shell_calls)}")
print(f"File edits: {len(edit_calls)}")

# Calculate total execution time
total_time = sum(t.get('execution_time_ms', 0) for t in shell_calls)
print(f"Total shell time: {total_time}ms")

# Success rate
successful = sum(1 for t in shell_calls if t.get('success'))
print(f"Success rate: {successful}/{len(shell_calls)}")
```

### Session Resume (Future)

```python
# Future API (Phase 2)
from real_mcp_server import resume_cursor_session

session_id = "abc123-session-id"
result = resume_cursor_session(
    session_id=session_id,
    additional_prompt="Continue with next steps"
)
```

---

## Troubleshooting

### cursor-agent Not Found

```bash
# Check if installed
which cursor-agent

# If not found, install
curl https://cursor.com/install -fsSL | bash

# Add to PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Permission Errors

```bash
# Make cursor-agent executable
chmod +x ~/.local/bin/cursor-agent

# Test execution
cursor-agent --version
```

### Parsing Errors

```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Parse with error handling
result = parse_cursor_stream_jsonl("log.jsonl")
if not result.get('success'):
    print(f"Error: {result.get('error')}")
```

### Model Not Available

```bash
# Check available models
cursor-agent --help | grep -A 5 "model"

# Use auto-select
cursor-agent -p "task" --model auto --output-format json
```

---

## Testing

### Run Full Test Suite

```bash
python3 test_cursor_cli_integration.py
```

### Individual Tests

```bash
# Test detection only
python3 -c "from test_cursor_cli_integration import test_cursor_agent_detection; test_cursor_agent_detection()"

# Test parsing only
python3 -c "from test_cursor_cli_integration import test_stream_json_parsing; test_stream_json_parsing()"

# Test real execution
python3 -c "from test_cursor_cli_integration import test_real_cursor_agent; test_real_cursor_agent()"
```

---

## Next Steps (Future Phases)

### Phase 2: Session Management
- Implement `deploy_cursor_agent()` function
- Add session resume support
- Integrate with orchestrator registry

### Phase 3: Enhanced Features
- Model selection per agent
- Permission management
- Browser automation support

### Phase 4: Production Ready
- Full test coverage
- Documentation
- Migration guide

---

## API Reference

### Functions

#### `check_cursor_agent_available() -> bool`
Check if cursor-agent is installed and accessible.

**Returns:** `True` if available, `False` otherwise

**Example:**
```python
if check_cursor_agent_available():
    print("cursor-agent ready!")
```

#### `parse_cursor_stream_jsonl(log_file: str, include_thinking: bool = None) -> Dict[str, Any]`
Parse cursor-agent stream-json output.

**Parameters:**
- `log_file`: Path to JSONL log file
- `include_thinking`: Include thinking deltas (default: from env)

**Returns:** Dictionary with:
- `session_id`: Cursor session ID
- `events`: List of parsed events
- `tool_calls`: List of tool executions
- `assistant_messages`: List of assistant responses
- `thinking_text`: Captured thinking (if enabled)
- `final_result`: Completion status
- `duration_ms`: Total duration
- `success`: True if successful

**Example:**
```python
result = parse_cursor_stream_jsonl("agent.jsonl")
print(f"Completed in {result['duration_ms']}ms")
```

#### `parse_cursor_tool_call(event: Dict[str, Any]) -> Optional[Dict[str, Any]]`
Parse individual tool call event.

**Parameters:**
- `event`: Tool call event from stream-json

**Returns:** Dictionary with tool info or `None`

**Example:**
```python
tool_info = parse_cursor_tool_call(event)
if tool_info['tool_type'] == 'shell':
    print(f"Ran: {tool_info['command']}")
```

---

## Support

### Issues

If you encounter issues:

1. Check cursor-agent version: `cursor-agent --version`
2. Run test suite: `python3 test_cursor_cli_integration.py`
3. Check logs in workspace: `tail -f logs/*_stream.jsonl`
4. Enable debug logging: `export CLAUDE_ORCHESTRATOR_LOG_LEVEL=DEBUG`

### Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for development guidelines.

---

## Changelog

### 2025-10-31 - Phase 1 Complete
- ✅ Configuration support added
- ✅ Stream-JSON parser implemented
- ✅ Tool call extraction working
- ✅ All tests passing (5/5)
- ✅ Documentation complete

### Future Releases
- 🔜 Phase 2: Session management
- 🔜 Phase 3: Enhanced features
- 🔜 Phase 4: Production ready

---

## License

MIT License - See [LICENSE](../LICENSE) for details

