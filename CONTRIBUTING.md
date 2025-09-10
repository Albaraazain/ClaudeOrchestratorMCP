# Contributing to Claude Code Orchestrator

Thank you for your interest in contributing to Claude Code Orchestrator! This document provides guidelines and information for contributors.

## 🚀 Getting Started

### Prerequisites

- Python 3.8 or higher
- Claude Code CLI
- tmux (for background agent execution)
- Git

### Development Setup

1. **Fork and Clone**
   ```bash
   git clone https://github.com/your-username/claude-code-orchestrator.git
   cd claude-code-orchestrator
   ```

2. **Set up Environment**
   ```bash
   # Install dependencies
   ./install_mcp.sh
   
   # Or manually:
   pip install -r requirements.txt
   ```

3. **Test Your Setup**
   ```bash
   # Test MCP server
   python3 real_mcp_server.py
   
   # Add to Claude Code for testing
   claude mcp add --project test-orchestrator "$(pwd)/real_mcp_server.py"
   ```

## 🔧 Development Guidelines

### Code Style

- **Python**: Follow PEP 8 style guide
- **Docstrings**: Use Google-style docstrings for all functions
- **Type Hints**: Include type hints for function parameters and returns
- **Error Handling**: Use proper exception handling with logging

Example:
```python
def create_agent(task_id: str, agent_type: str) -> Dict[str, Any]:
    """Create a new agent for the specified task.
    
    Args:
        task_id: The ID of the task to create the agent for
        agent_type: The type of agent to create
        
    Returns:
        Dictionary containing agent creation result
        
    Raises:
        ValueError: If task_id is invalid
        RuntimeError: If agent creation fails
    """
    logger.info(f"Creating {agent_type} agent for task {task_id}")
    # Implementation here
```

### Testing

- Add tests for new functionality
- Ensure existing tests pass
- Test MCP integration manually with Claude Code

### Documentation

- Update README.md for new features
- Add docstrings to all new functions
- Update MCP_TOOLS.md for new MCP tools

## 📝 Contribution Process

### 1. Issue First

For significant changes, please create an issue first to discuss:
- New features
- Breaking changes  
- Major refactoring

### 2. Branch Naming

Use descriptive branch names:
- `feature/agent-templates`
- `fix/tmux-session-cleanup`
- `docs/mcp-tools-update`

### 3. Commit Messages

Use clear, descriptive commit messages:
```
feat: add agent template system for common tasks

- Add template loader for pre-configured agents
- Include templates for common development tasks
- Update documentation with template usage

Closes #123
```

### 4. Pull Request Process

1. **Create PR** with clear title and description
2. **Link Issues** using "Closes #123" in description  
3. **Add Tests** for new functionality
4. **Update Docs** as needed
5. **Request Review** from maintainers

## 🧪 Testing Guidelines

### Manual Testing

```bash
# Test basic MCP functionality
claude mcp list | grep orchestrator

# Test agent creation
python3 -c "
from real_mcp_server import create_real_task, deploy_headless_agent
task = create_real_task('Test task', 'P2')
print('Task:', task)
"
```

### Integration Testing

Test with actual Claude Code usage:
```python
# In Claude Code
task = create_real_task("Test integration", "P2")
agent = deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="tester",
    prompt="Test the integration works correctly"
)
status = get_real_task_status(task["task_id"])
```

## 🏗️ Architecture Guidelines

### MCP Tools

When adding new MCP tools:
1. Use `@mcp.tool` decorator
2. Include comprehensive docstrings
3. Return standardized response format
4. Add proper error handling
5. Update MCP_TOOLS.md

### Agent Management

For agent-related changes:
- Respect anti-spiral protection limits
- Use proper tmux session management
- Include progress tracking
- Handle cleanup on failures

### Workspace Management

- Use `WORKSPACE_BASE` for all workspace operations
- Create proper directory structures
- Include cleanup mechanisms
- Handle permissions properly

## 🐛 Bug Reports

When reporting bugs, please include:

1. **Environment**:
   - Python version
   - Claude Code version
   - OS and version

2. **Steps to reproduce**
3. **Expected vs actual behavior**
4. **Relevant logs/output**
5. **MCP server logs** if applicable

## 💡 Feature Requests

For new features, please provide:

1. **Use case**: Why is this needed?
2. **Proposed solution**: How should it work?
3. **Alternatives considered**: Other approaches?
4. **Implementation notes**: Technical considerations?

## 🚫 What NOT to Contribute

Please avoid:
- Changes that bypass anti-spiral protection
- Features that could cause resource exhaustion
- Breaking changes without discussion
- Code without proper error handling
- Features that compromise security

## 📞 Getting Help

- **Issues**: Use GitHub Issues for questions
- **Discussions**: Use GitHub Discussions for general chat
- **Documentation**: Check README.md and docs/ folder

## 🏆 Recognition

Contributors will be:
- Listed in CONTRIBUTORS.md
- Mentioned in release notes for significant contributions
- Given appropriate credit in documentation

## 📜 Code of Conduct

- Be respectful and inclusive
- Focus on constructive feedback
- Help others learn and grow
- Follow the golden rule

Thank you for contributing to Claude Code Orchestrator! 🚀