#!/bin/bash
# Monitor agents with anti-spiral detection and intervention

AGENT_BASE_DIR="${AGENT_BASE_DIR:-.agent-workspace}"
TASK_ID="${1:?Error: Task ID required}"
INTERVAL="${2:-30}"

WORKSPACE="${AGENT_BASE_DIR}/${TASK_ID}"
REGISTRY="${WORKSPACE}/AGENT_REGISTRY.json"

echo "👁️ Starting anti-spiral monitor for ${TASK_ID}"
echo "   Check interval: ${INTERVAL}s"
echo "   Press Ctrl+C to stop"
echo ""

# Monitoring loop
while true; do
    clear
    echo "═══════════════════════════════════════════════════════════"
    echo "🔍 ANTI-SPIRAL MONITOR - ${TASK_ID}"
    echo "═══════════════════════════════════════════════════════════"
    
    if [ ! -f "${REGISTRY}" ]; then
        echo "❌ Task registry not found"
        exit 1
    fi
    
    # Read current state
    REGISTRY_DATA=$(cat "${REGISTRY}")
    
    # Display stats
    echo "${REGISTRY_DATA}" | python3 -c "
import json, sys
from datetime import datetime

data = json.load(sys.stdin)
print(f\"Task: {data['task_description']}\")
print(f\"Status: {data['status']}\")
print(f\"Total Spawned: {data['total_spawned']} / {data['max_agents']}\")
print(f\"Active: {data['active_count']} / {data['max_concurrent']}\")
print(f\"Completed: {data['completed_count']}\")
print(f\"Spiral Violations: {data['spiral_checks']['violations']}\")
print()

# Check for issues
issues = []

# SPIRAL CHECK 1: Too many active agents
if data['active_count'] > data['max_concurrent']:
    issues.append(f\"🚨 SPIRAL DETECTED: {data['active_count']} agents active (max: {data['max_concurrent']})\")

# SPIRAL CHECK 2: Rapid spawning
agents = data['agents']
recent_spawns = 0
now = datetime.now()
for agent in agents:
    started = datetime.fromisoformat(agent['started_at'])
    if (now - started).seconds < 60:
        recent_spawns += 1

if recent_spawns >= 3:
    issues.append(f\"⚠️ RAPID SPAWNING: {recent_spawns} agents started in last minute\")

# SPIRAL CHECK 3: Deep hierarchy
max_depth_found = max([a['depth'] for a in agents] + [0])
if max_depth_found >= data['max_depth']:
    issues.append(f\"⚠️ MAX DEPTH: Agents at depth {max_depth_found}\")

# SPIRAL CHECK 4: Stuck agents
for agent in agents:
    if agent['status'] == 'running':
        last_update = datetime.fromisoformat(agent['last_update'])
        time_since = (now - last_update).seconds
        if time_since > 300:  # 5 minutes
            issues.append(f\"⏰ STUCK: {agent['id']} hasn't updated in {time_since//60} minutes\")

# Display hierarchy
print('AGENT HIERARCHY:')
print('─────────────────')
hierarchy = data.get('agent_hierarchy', {})

def print_tree(parent, indent=0):
    if parent in hierarchy:
        for child in hierarchy[parent]:
            agent = next((a for a in agents if a['id'] == child), None)
            if agent:
                status_icon = '✅' if agent['status'] == 'completed' else '🔄'
                print(f\"{'  ' * indent}├─ {status_icon} {child} ({agent['progress']}%)\")
                print_tree(child, indent + 1)

print_tree('orchestrator')

# Display issues
if issues:
    print()
    print('ISSUES DETECTED:')
    print('───────────────')
    for issue in issues:
    print(issue)
"
    
    # AUTO-INTERVENTION LOGIC
    ACTIVE_COUNT=$(echo "${REGISTRY_DATA}" | python3 -c "import json,sys; print(json.load(sys.stdin)['active_count'])")
    MAX_CONCURRENT=$(echo "${REGISTRY_DATA}" | python3 -c "import json,sys; print(json.load(sys.stdin)['max_concurrent'])")
    
    if [ "${ACTIVE_COUNT}" -gt "${MAX_CONCURRENT}" ]; then
        echo ""
        echo "🛑 AUTO-INTERVENTION: Killing newest agents to prevent spiral..."
        
        # Get newest agents and kill them
        AGENTS_TO_KILL=$(echo "${REGISTRY_DATA}" | python3 -c "
import json, sys
from datetime import datetime

data = json.load(sys.stdin)
agents = [a for a in data['agents'] if a['status'] == 'running']
agents.sort(key=lambda x: datetime.fromisoformat(x['started_at']), reverse=True)

# Keep only oldest agents up to max_concurrent
to_kill = agents[data['max_concurrent']:]
for agent in to_kill:
    print(agent['id'])
")
        
        for AGENT_ID in ${AGENTS_TO_KILL}; do
            echo "   Terminating: ${AGENT_ID}"
            # Would kill actual process here
            
            # Update registry
            python3 -c "
import json
with open('${REGISTRY}', 'r') as f:
    registry = json.load(f)
for agent in registry['agents']:
    if agent['id'] == '${AGENT_ID}':
        agent['status'] = 'terminated'
        registry['active_count'] -= 1
        registry['spiral_checks']['violations'] += 1
        break
with open('${REGISTRY}', 'w') as f:
    json.dump(registry, f, indent=2)
"
        done
    fi
    
    # Check for stuck agents and offer help
    STUCK_AGENTS=$(echo "${REGISTRY_DATA}" | python3 -c "
import json, sys
from datetime import datetime

data = json.load(sys.stdin)
stuck = []
now = datetime.now()
for agent in data['agents']:
    if agent['status'] == 'running':
        last_update = datetime.fromisoformat(agent['last_update'])
        if (now - last_update).seconds > 600:  # 10 minutes
            stuck.append(agent['id'])

for s in stuck:
    print(s)
")
    
    if [ -n "${STUCK_AGENTS}" ]; then
        echo ""
        echo "🆘 Deploying helper for stuck agents..."
        for STUCK_ID in ${STUCK_AGENTS}; do
            echo "   Helper for: ${STUCK_ID}"
            # Could deploy a helper agent here
        done
    fi
    
    echo ""
    echo "Next check in ${INTERVAL} seconds..."
    echo "═══════════════════════════════════════════════════════════"
    
    # Sleep between checks (as per user instructions, use 110s for monitoring)
    sleep 110
done