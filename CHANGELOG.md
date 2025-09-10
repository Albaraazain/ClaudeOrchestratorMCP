# Changelog

All notable changes to the Claude Headless Orchestrator project will be documented in this file.

## [1.0.0] - 2025-09-08

### Added
- **MCP Server Implementation**: Complete Model Context Protocol server for Claude Code integration
- **Anti-Spiral Protection**: Robust protection against runaway agent spawning
  - Concurrent agent limits (max 5 simultaneously)
  - Per-task agent limits (max 10 total)
  - Hierarchical depth limits (max 3 levels)
  - Spawn rule enforcement
- **Headless Claude Deployment**: Real background Claude agent deployment via `claude --dangerously-skip-permissions --run-in-background`
- **Agent Registry System**: Comprehensive tracking of all agents and tasks
- **Workspace Isolation**: Each task gets isolated workspace with progress tracking
- **Real-time Monitoring**: Live agent status and progress monitoring

### MCP Tools
- `create_real_task`: Create orchestration tasks with workspace setup
- `deploy_headless_agent`: Deploy background Claude agents with anti-spiral checks
- `get_real_task_status`: Comprehensive task and agent status reporting
- `kill_real_agent`: Safe agent termination with cleanup

### MCP Resources  
- `tasks://list`: List all orchestration tasks
- `task://{task_id}/status`: Get specific task details and status

### Core Features
- **Hierarchical Agent Management**: Parent-child agent relationships with depth tracking
- **Progress Tracking**: Agents report progress via JSON files in workspace
- **Violation Tracking**: Monitor and log anti-spiral violations
- **Configurable Limits**: Adjustable limits for agents, depth, and concurrency
- **Workspace Structure**: Organized workspaces with progress, findings, and logs

### Project Structure
- Organized codebase with proper separation of concerns
- Main MCP server (`real_mcp_server.py`)
- Core orchestration logic (`orchestrator.py`)  
- Comprehensive test suite
- Documentation and examples
- CLI tools for standalone operation

### Safety Features
- Automatic termination of excess agents
- Spawn cooldowns when spiraling detected
- Stuck agent detection and handling
- Resource usage monitoring
- Configuration validation

### Documentation
- Complete README with installation and usage instructions
- MCP tools documentation with examples
- Real-world usage patterns
- Troubleshooting guide
- API reference

## [0.1.0] - 2025-09-08 (Pre-MCP Version)

### Added
- Initial CLI-based orchestrator
- Basic agent deployment scripts
- Simple anti-spiral protection
- Task workspace creation
- Agent registry tracking

### Deprecated
- CLI-only interface (replaced with MCP server)
- Direct shell command orchestration (replaced with MCP tools)