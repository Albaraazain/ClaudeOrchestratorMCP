#!/bin/bash
# Check status of task and all agents

AGENT_BASE_DIR="${AGENT_BASE_DIR:-.agent-workspace}"
TASK_ID="${1:?Error: Task ID required}"
DETAILED="${2:-false}"

WORKSPACE="${AGENT_BASE_DIR}/${TASK_ID}"
REGISTRY="${WORKSPACE}/AGENT_REGISTRY.json"

if [ ! -f "${REGISTRY}" ]; then
    echo "❌ Task ${TASK_ID} not found"
    exit 1
fi

echo "═══════════════════════════════════════════════════════════"
echo "📊 TASK STATUS: ${TASK_ID}"
echo "═══════════════════════════════════════════════════════════"

python3 -c "
import json
from datetime import datetime

with open('${REGISTRY}', 'r') as f:
    data = json.load(f)

print(f\"Description: {data['task_description']}\")
print(f\"Priority: {data['priority']}\")
print(f\"Created: {data['created_at']}\")
print(f\"Status: {data['status']}\")
print()

print('AGENT STATISTICS:')
print(f\"  Total Spawned: {data['total_spawned']} / {data['max_agents']}\")
print(f\"  Currently Active: {data['active_count']} / {data['max_concurrent']}\")
print(f\"  Completed: {data['completed_count']}\")
print(f\"  Max Depth Used: {max([a['depth'] for a in data['agents']] + [0])} / {data['max_depth']}\")
print(f\"  Spiral Violations: {data['spiral_checks']['violations']}\")
print()

# Show running agents
running = [a for a in data['agents'] if a['status'] == 'running']
if running:
    print('RUNNING AGENTS:')
    for agent in running:
        last_update = datetime.fromisoformat(agent['last_update'])
        mins_ago = (datetime.now() - last_update).seconds // 60
        print(f\"  • {agent['id']}\")
        print(f\"    Type: {agent['type']} | Progress: {agent['progress']}%\")
        print(f\"    Parent: {agent['parent']} | Depth: {agent['depth']}\")
        print(f\"    Last Update: {mins_ago} mins ago\")

# Show completed agents
completed = [a for a in data['agents'] if a['status'] == 'completed']
if completed:
    print()
    print('COMPLETED AGENTS:')
    for agent in completed[:5]:  # Show last 5
        print(f\"  ✅ {agent['id']} ({agent['type']}) - 100%\")

# Show hierarchy
print()
print('AGENT HIERARCHY:')
hierarchy = data.get('agent_hierarchy', {})

def print_tree(parent, agents_list, hierarchy_dict, indent=0):
    if parent in hierarchy_dict:
        for child in hierarchy_dict[parent]:
            agent = next((a for a in agents_list if a['id'] == child), None)
            if agent:
                status = '✅' if agent['status'] == 'completed' else '🔄' if agent['status'] == 'running' else '❌'
                print(f\"{'  ' * indent}├─ {status} {child} ({agent['progress']}%)\")
                print_tree(child, agents_list, hierarchy_dict, indent + 1)

print_tree('orchestrator', data['agents'], hierarchy)
"

if [ "${DETAILED}" = "true" ]; then
    echo ""
    echo "RECENT PROGRESS UPDATES:"
    echo "─────────────────────────────────────"
    ls -t "${WORKSPACE}"/progress/*.json 2>/dev/null | head -5 | while read -r file; do
        python3 -c "
import json
with open('$file', 'r') as f:
    d = json.load(f)
    print(f\"  • [{d.get('timestamp', 'N/A')}] {d['agent_id']}: {d['progress']}% - {d.get('message', '')}\")
"
    done
    
    if [ -d "${WORKSPACE}/findings" ] && [ "$(ls -A ${WORKSPACE}/findings)" ]; then
        echo ""
        echo "FINDINGS:"
        echo "─────────────────────────────────────"
        for file in "${WORKSPACE}"/findings/*.json; do
            [ -f "$file" ] && python3 -c "
import json
with open('$file', 'r') as f:
    d = json.load(f)
    print(f\"  • {d.get('key', 'unknown')}: {d.get('value', 'N/A')}\")
"
        done
    fi
fi

echo "═══════════════════════════════════════════════════════════"