# MCP Tools Documentation

## Overview
The Claude Orchestrator MCP server provides tools for managing headless Claude agents through the Model Context Protocol.

## Available Tools

### create_real_task
Creates a new orchestration task with workspace and tracking.

**Parameters:**
- `description` (string): Task description
- `priority` (string, optional): Priority level (P1, P2, P3, P4), default: "P2"

**Returns:**
```json
{
  "success": true,
  "task_id": "TASK-20250908-123456-abc123",
  "description": "Database optimization task",
  "priority": "P1",
  "workspace": ".agent-workspace/TASK-20250908-123456-abc123",
  "status": "INITIALIZED"
}
```

**Example:**
```python
task = create_real_task(
    description="Optimize database queries for better performance",
    priority="P1"
)
```

### deploy_headless_agent
Deploys a headless Claude agent to work on a specific task.

**Parameters:**
- `task_id` (string): ID of the task to work on
- `agent_type` (string): Type/role of the agent (e.g., "investigator", "fixer")
- `prompt` (string): Detailed instructions for the agent
- `parent` (string, optional): Parent agent ID, default: "orchestrator"

**Returns:**
```json
{
  "success": true,
  "agent_id": "investigator-123456-abc123",
  "bash_id": "bash_investigator_xyz789",
  "type": "investigator",
  "parent": "orchestrator",
  "task_id": "TASK-20250908-123456",
  "status": "deployed",
  "workspace": ".agent-workspace/TASK-20250908-123456",
  "deployment_command": "claude --dangerously-skip-permissions --run-in-background [PROMPT]"
}
```

**Example:**
```python
agent = deploy_headless_agent(
    task_id="TASK-20250908-123456-abc123",
    agent_type="database_investigator",
    prompt="Analyze slow queries in the production database. Identify N+1 queries, missing indexes, and performance bottlenecks. Document findings in the workspace.",
    parent="orchestrator"
)
```

### get_real_task_status
Retrieves comprehensive status information about a task and its agents.

**Parameters:**
- `task_id` (string): ID of the task to check

**Returns:**
```json
{
  "success": true,
  "task_id": "TASK-20250908-123456",
  "description": "Database optimization task",
  "status": "INITIALIZED",
  "workspace": ".agent-workspace/TASK-20250908-123456",
  "agents": {
    "total_spawned": 3,
    "active": 2,
    "completed": 1,
    "agents_list": [
      {
        "id": "investigator-123456",
        "type": "investigator",
        "bash_id": "bash_investigator_xyz",
        "parent": "orchestrator",
        "depth": 1,
        "status": "running",
        "started_at": "2025-09-08T14:30:00",
        "progress": 75,
        "last_update": "2025-09-08T14:35:00",
        "prompt": "Analyze database performance..."
      }
    ]
  },
  "hierarchy": {
    "orchestrator": ["investigator-123456"],
    "investigator-123456": ["optimizer-789012"]
  },
  "recent_progress": [
    {
      "agent_id": "investigator-123456",
      "timestamp": "2025-09-08T14:35:00",
      "progress": 75,
      "message": "Found 3 slow queries, analyzing patterns"
    }
  ],
  "spiral_status": {
    "enabled": true,
    "last_check": "2025-09-08T14:30:00",
    "violations": 0
  },
  "limits": {
    "max_agents": 10,
    "max_concurrent": 5,
    "max_depth": 3
  }
}
```

**Example:**
```python
status = get_real_task_status("TASK-20250908-123456-abc123")
print(f"Active agents: {status['agents']['active']}")
print(f"Task progress: {len(status['agents']['agents_list'])} agents deployed")
```

### kill_real_agent
Terminates a specific running agent.

**Parameters:**
- `task_id` (string): Task containing the agent
- `agent_id` (string): ID of the agent to terminate
- `reason` (string, optional): Reason for termination, default: "Manual termination"

**Returns:**
```json
{
  "success": true,
  "agent_id": "investigator-123456",
  "bash_id": "bash_investigator_xyz",
  "reason": "Task completed",
  "status": "terminated"
}
```

**Example:**
```python
result = kill_real_agent(
    task_id="TASK-20250908-123456-abc123",
    agent_id="investigator-123456",
    reason="Investigation complete"
)
```

## Anti-Spiral Protection

All agent deployment tools include built-in anti-spiral protection:

### Protection Mechanisms
1. **Concurrent Limit**: Maximum 5 agents running simultaneously
2. **Per-Task Limit**: Maximum 10 agents per task total
3. **Depth Limit**: Maximum 3 levels of agent hierarchy
4. **Spawn Rules**: Only allowed parent-child relationships

### Error Responses
When limits are exceeded, tools return error responses:

```json
{
  "success": false,
  "error": "Too many active agents (5/5)"
}
```

```json
{
  "success": false,
  "error": "Max agents reached (10/10)"
}
```

## Workflow Examples

### Sequential Agent Pattern
```python
# 1. Create task
task = create_real_task("API performance investigation", "P1")

# 2. Deploy investigator
investigator = deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="api_investigator",
    prompt="Analyze API response times and identify bottlenecks"
)

# 3. Wait for investigation, then deploy fixer
fixer = deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="api_optimizer",
    prompt="Implement optimizations based on investigation findings",
    parent=investigator["agent_id"]
)

# 4. Deploy tester
tester = deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="api_tester",
    prompt="Test API performance improvements and validate changes",
    parent=fixer["agent_id"]
)
```

### Parallel Agent Pattern
```python
# 1. Create task
task = create_real_task("System health analysis", "P2")

# 2. Deploy multiple specialists simultaneously
components = ["database", "api", "frontend", "cache"]
agents = []

for component in components:
    agent = deploy_headless_agent(
        task_id=task["task_id"],
        agent_type=f"{component}_analyzer",
        prompt=f"Analyze {component} performance and health metrics"
    )
    agents.append(agent)

# 3. Deploy synthesizer to combine results
synthesizer = deploy_headless_agent(
    task_id=task["task_id"],
    agent_type="health_synthesizer",
    prompt="Combine all component analyses into overall system health report"
)
```

## Best Practices

### Agent Naming
- Use descriptive agent types: `database_investigator` vs `agent1`
- Include role in name: `performance_tester`, `security_scanner`
- Use consistent naming patterns

### Prompt Design
- Be specific about expected outputs
- Include workspace usage instructions
- Specify completion criteria
- Reference parent agent work when applicable

### Error Handling
- Always check `success` field in responses
- Handle anti-spiral limit errors gracefully
- Implement retry logic with delays for temporary failures

### Monitoring
- Check task status regularly during long operations
- Monitor agent progress through status updates
- Watch for stuck agents (no progress updates)