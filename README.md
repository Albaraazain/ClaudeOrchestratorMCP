# 🤖 Claude Code Orchestrator

A powerful **Model Context Protocol (MCP) server** for orchestrating headless Claude agents with advanced **anti-spiral protection**. Deploy, monitor, and manage autonomous Claude agents safely through standardized MCP tools.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![MCP Protocol](https://img.shields.io/badge/MCP-Protocol-green.svg)](https://modelcontextprotocol.io/)

## ✨ Key Features

- 🚫 **Anti-Spiral Protection**: Prevents runaway agent spawning with configurable limits
- 🎯 **Headless Claude Agents**: Deploy real background Claude instances (no built-in Task tool)
- 🌳 **Hierarchical Management**: Parent-child agent relationships with depth limits
- 📊 **Real-time Monitoring**: Track agent progress, status, and violations
- 🔧 **MCP Integration**: Seamless integration with Claude Code via Model Context Protocol
- 📁 **Workspace Isolation**: Each task gets isolated workspace with progress tracking

## 🏗️ Architecture

```
Claude Code ←→ MCP Protocol ←→ Orchestrator MCP Server
                                      ↓
                           Headless Claude Agents
                              (Background Tasks)
                                      ↓
                              Workspace Tracking
                           (.agent-workspace/TASK-*)
```

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/your-org/claude-code-orchestrator.git
cd claude-code-orchestrator

# Install dependencies
chmod +x install_mcp.sh
./install_mcp.sh

# Add to Claude Code (local project)
claude mcp add --project claude-orchestrator "$(pwd)/real_mcp_server.py"

# Or add globally
claude mcp add --global claude-orchestrator python "$(pwd)/real_mcp_server.py"

# Verify connection
claude mcp list
```

### 2. Basic Usage in Claude Code

```python
# Create a task
task = create_real_task("Optimize database performance", "P1")

# Deploy headless agent
agent = deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="investigator", 
    prompt="Analyze slow queries and identify bottlenecks"
)

# Monitor progress
status = get_real_task_status(task["task_id"])

# Deploy follow-up agent
fixer = deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="fixer",
    prompt="Implement performance optimizations",
    parent=agent["agent_id"]  # Hierarchical spawning
)
```

## 🛠️ Available MCP Tools

### Core Agent Management

| Tool | Description | Parameters |
|------|-------------|------------|
| `create_real_task` | Create orchestration task | `description`, `priority` |
| `deploy_headless_agent` | Deploy background Claude agent | `task_id`, `agent_type`, `prompt`, `parent` |
| `get_real_task_status` | Get task and agent status | `task_id` |
| `kill_real_agent` | Terminate specific agent | `task_id`, `agent_id`, `reason` |

### Example Tool Usage

```python
# Create task
task = create_real_task(
    description="Debug production API issues",
    priority="P1"
)

# Deploy investigator
investigator = deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="investigator",
    prompt="Analyze API error logs and identify patterns"
)

# Check status
status = get_real_task_status(task["task_id"])
print(f"Active agents: {status['agents']['active']}")

# Deploy fixer based on investigation
fixer = deploy_headless_agent(
    task_id=task["task_id"], 
    agent_type="fixer",
    prompt="Fix the API issues found by investigator",
    parent=investigator["agent_id"]
)
```

## 📚 Available MCP Resources

| Resource | Description |
|----------|-------------|
| `tasks://list` | List all orchestration tasks |
| `task://{task_id}/status` | Get specific task details |

## 🛡️ Anti-Spiral Protection

The system prevents runaway agent spawning through multiple layers:

### Limits Configuration
```json
{
  "max_concurrent_agents": 5,    // Global concurrent limit
  "max_agents_per_task": 10,     // Per-task total limit
  "max_depth": 3,                // Hierarchy depth limit
  "stuck_threshold_seconds": 600  // Auto-terminate stuck agents
}
```

### Protection Features
- ✅ **Concurrent Limit**: Max 5 agents running simultaneously
- ✅ **Depth Limiting**: 3-level hierarchy (orchestrator → agent → sub-agent)
- ✅ **Spawn Rules**: Configurable parent-child permissions
- ✅ **Stuck Detection**: Auto-terminate unresponsive agents
- ✅ **Violation Tracking**: Monitor and log spiral attempts

### Example Protection in Action
```python
# This will succeed (within limits)
for i in range(5):
    deploy_headless_agent(task_id, f"agent_{i}", "Work on subtask")

# This will fail with anti-spiral protection
result = deploy_headless_agent(task_id, "agent_6", "This exceeds limit")
# Returns: {"success": false, "error": "Too many active agents (5/5)"}
```

## 📁 Project Structure

```
claude-code-orchestrator/
├── 📄 README.md                    # This documentation
├── 🐍 real_mcp_server.py          # Main MCP server
├── ⚙️ .mcp.json                   # Local MCP configuration
├── 📦 pyproject.toml              # Python package configuration
├── 📋 requirements.txt            # Python dependencies
├── 📜 LICENSE                     # MIT License
├── 📝 CHANGELOG.md               # Version history
├── 🔧 install_mcp.sh              # Installation script
├── 🔧 install_toolkit.sh          # Toolkit installer
├── scripts/                       # Management scripts
│   ├── deploy.sh                  # Deploy agents
│   ├── init.sh                    # Initialize workspace
│   ├── status.sh                  # Check status
│   ├── monitor.sh                 # Live monitoring
│   ├── list.sh                    # List agents
│   └── update.sh                  # Update system
├── examples/
│   └── demo.sh                    # Usage examples
├── docs/
│   └── MCP_TOOLS.md              # MCP tools documentation
├── progress_template_generator.sh # Progress template generator
├── progress_watchdog.sh          # Progress monitoring
├── enhanced_progress_schema.md   # Progress schema docs
└── .agent-workspace/              # Agent workspaces (auto-created)
    ├── registry/                  # Global agent registry
    └── TASK-*/                    # Individual task workspaces
        ├── AGENT_REGISTRY.json   # Task-specific tracking
        ├── progress/              # Agent progress updates
        ├── findings/              # Agent discoveries
        └── logs/                  # Deployment logs
```

## 🎯 Real-World Usage Examples

### 1. Database Performance Investigation
```python
# Create high-priority task
task = create_real_task("Production DB slowdown investigation", "P1")

# Deploy specialist agents in sequence
investigator = deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="db_investigator", 
    prompt="Analyze slow query logs, identify N+1 queries and bottlenecks"
)

# Wait for investigation, then deploy optimizer
optimizer = deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="db_optimizer",
    prompt="Optimize queries and indexes based on investigation findings",
    parent=investigator["agent_id"]
)

# Deploy tester to verify improvements  
tester = deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="performance_tester",
    prompt="Test DB performance improvements and benchmark results",
    parent=optimizer["agent_id"] 
)
```

### 2. Parallel Code Analysis
```python
# Create analysis task
task = create_real_task("Comprehensive codebase analysis", "P2")

# Deploy multiple specialists in parallel
aspects = ["security", "performance", "maintainability", "testing"]
agents = []

for aspect in aspects:
    agent = deploy_headless_agent(
        task_id=task["task_id"],
        agent_type=f"{aspect}_analyzer",
        prompt=f"Analyze codebase for {aspect} issues and recommendations"
    )
    agents.append(agent)

# Deploy synthesizer to combine findings
synthesizer = deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="synthesizer", 
    prompt="Combine all analysis findings into actionable recommendations"
)
```

## 🔧 Configuration

### Environment Variables

Configure the orchestrator using environment variables:

```bash
# Workspace location (default: .agent-workspace)
export CLAUDE_ORCHESTRATOR_WORKSPACE="/path/to/workspace"

# Maximum concurrent agents (default: 8)
export CLAUDE_ORCHESTRATOR_MAX_CONCURRENT=10

# Maximum agents per task (default: 25)
export CLAUDE_ORCHESTRATOR_MAX_AGENTS=50

# Maximum hierarchy depth (default: 5)
export CLAUDE_ORCHESTRATOR_MAX_DEPTH=4

# Claude executable path (default: claude)
export CLAUDE_EXECUTABLE="/path/to/claude"

# Claude command flags (customize as needed)
export CLAUDE_FLAGS="--print --output-format stream-json --verbose --dangerously-skip-permissions --model glm-4.5"
```

### MCP Server Configuration

The server automatically configures itself using environment variables. No code editing required!

### Spawn Rules Configuration
Edit `.agent-workspace/SPAWN_RULES.json`:
```json
{
  "orchestrator": ["investigator", "fixer", "analyzer"],
  "investigator": ["specialist"],
  "fixer": ["tester"],
  "analyzer": [],
  "specialist": [],
  "tester": []
}
```

## 📊 Monitoring and Debugging

### Real-time Status Monitoring
```python
# Check overall task status
status = get_real_task_status("TASK-20250908-123456")

print(f"Task: {status['description']}")
print(f"Active agents: {status['agents']['active']}")
print(f"Completed: {status['agents']['completed']}")
print(f"Agent hierarchy: {status['hierarchy']}")

# Check for spiral violations
if status['spiral_status']['violations'] > 0:
    print("⚠️ Anti-spiral violations detected!")
```

### Agent Workspace Inspection
```bash
# Check task workspace
ls -la .agent-workspace/TASK-20250908-123456/

# View agent progress
cat .agent-workspace/TASK-20250908-123456/progress/*.json

# Check deployment logs  
cat .agent-workspace/TASK-20250908-123456/logs/*.json
```

## 🚨 Troubleshooting

### Common Issues

**MCP Server Not Connecting**
```bash
# Check server status
claude mcp list

# Re-add server (project-level)
claude mcp remove --project claude-orchestrator
claude mcp add --project claude-orchestrator "$(pwd)/real_mcp_server.py"

# Or globally
claude mcp remove --global claude-orchestrator
claude mcp add --global claude-orchestrator python "$(pwd)/real_mcp_server.py"
```

**Agents Not Deploying**
- Check anti-spiral limits in status response
- Verify task exists with `get_real_task_status`  
- Check spawn rules in `.agent-workspace/SPAWN_RULES.json`

**Workspace Issues**
```bash
# Reset workspace
rm -rf .agent-workspace
# Recreate on next agent deployment
```

## 🧪 Testing

Test the MCP server functionality:

```bash
# Test MCP server connection
claude mcp list | grep claude-orchestrator

# Test basic functionality in Claude Code
claude --print --model glm-4.5 "Create a test task using the orchestrator MCP"

# Manual testing
python3 -c "
import sys, os
sys.path.append(os.getcwd())
from real_mcp_server import create_real_task
task = create_real_task('Test deployment', 'P2')
print('Task created:', task)
"
```

## 👥 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Development Setup

```bash
# Clone the repository
git clone https://github.com/your-org/claude-code-orchestrator.git
cd claude-code-orchestrator

# Install in development mode
./install_mcp.sh

# Make your changes and test
python3 real_mcp_server.py
```

### Contribution Guidelines

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-feature`)
3. **Commit** your changes (`git commit -m 'Add amazing feature'`)
4. **Push** to the branch (`git push origin feature/amazing-feature`)
5. **Open** a Pull Request

### Code Style

- Follow PEP 8 for Python code
- Add docstrings for new functions
- Update tests for new features
- Keep the README updated

## 📋 Development Roadmap

- [ ] **Enhanced Monitoring**: Real-time agent health checks
- [ ] **Agent Templates**: Pre-configured agent types for common tasks
- [ ] **Progress Streaming**: Live progress updates via SSE
- [ ] **Rollback System**: Checkpoint and restore agent states
- [ ] **Metrics Dashboard**: Visual monitoring interface
- [ ] **Agent Communication**: Inter-agent messaging system

## ⚠️ Important Notes

- **Headless Agents**: Uses tmux sessions with `claude --dangerously-skip-permissions`
- **Resource Usage**: Each agent consumes system resources - monitor carefully
- **Anti-Spiral Critical**: Always respect the limits to prevent system overload
- **Prerequisites**: Requires Claude Code CLI and tmux installed

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [Anthropic](https://www.anthropic.com/) for Claude
- [Model Context Protocol](https://modelcontextprotocol.io/) for the MCP standard
- All contributors who help improve this project

---

**Built with ❤️ for safe, scalable Claude agent orchestration via MCP**