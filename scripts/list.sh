#!/bin/bash
# List all active tasks and agents across workspace

AGENT_BASE_DIR="${AGENT_BASE_DIR:-.agent-workspace}"

echo "═══════════════════════════════════════════════════════════"
echo "📋 GLOBAL ORCHESTRATOR STATUS"
echo "═══════════════════════════════════════════════════════════"

if [ ! -f "${AGENT_BASE_DIR}/registry/GLOBAL_REGISTRY.json" ]; then
    echo "❌ Global registry not found. Run install first."
    exit 1
fi

python3 -c "
import json
import os
from datetime import datetime

# Read global registry
with open('${AGENT_BASE_DIR}/registry/GLOBAL_REGISTRY.json', 'r') as f:
    global_reg = json.load(f)

print(f\"Total Tasks: {global_reg['total_tasks']}\")
print(f\"Active Tasks: {global_reg['active_tasks']}\")
print(f\"Total Agents Spawned: {global_reg['total_agents_spawned']}\")
print(f\"Currently Active Agents: {global_reg['active_agents']} / {global_reg['max_concurrent_agents']}\")
print()

# List tasks
if global_reg['tasks']:
    print('TASKS:')
    print('──────')
    for task_id, task_info in global_reg['tasks'].items():
        print(f\"  • {task_id}\")
        print(f\"    {task_info['description']}\")
        print(f\"    Status: {task_info['status']}\")
        
        # Check task-specific registry for details
        task_registry_path = '${AGENT_BASE_DIR}/' + task_id + '/AGENT_REGISTRY.json'
        if os.path.exists(task_registry_path):
            with open(task_registry_path, 'r') as f:
                task_data = json.load(f)
                active = task_data['active_count']
                total = task_data['total_spawned']
                print(f\"    Agents: {active} active / {total} total\")
        print()

# List active agents globally
if global_reg['agents']:
    print('ACTIVE AGENTS:')
    print('──────────────')
    for agent_id, agent_info in global_reg['agents'].items():
        print(f\"  • {agent_id}\")
        print(f\"    Task: {agent_info['task_id']}\")
        print(f\"    Type: {agent_info['type']}\")
        print(f\"    Parent: {agent_info['parent']}\")
        print(f\"    Depth: {agent_info['depth']}\")

# Warnings
print()
print('SYSTEM HEALTH:')
print('──────────────')
if global_reg['active_agents'] >= global_reg['max_concurrent_agents']:
    print('🚨 WARNING: At maximum concurrent agent limit!')
elif global_reg['active_agents'] >= global_reg['max_concurrent_agents'] * 0.8:
    print('⚠️ CAUTION: Approaching maximum concurrent agents')
else:
    print('✅ System operating normally')
"

echo "═══════════════════════════════════════════════════════════"