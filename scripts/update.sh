#!/bin/bash
# Update agent progress - called BY agents to report status

AGENT_BASE_DIR="${AGENT_BASE_DIR:-.agent-workspace}"
AGENT_ID="${1:?Error: Agent ID required}"
PROGRESS="${2:?Error: Progress percentage required}"
MESSAGE="${3:-No message}"

# Find workspace containing this agent
WORKSPACE=$(find "${AGENT_BASE_DIR}" -name "AGENT_REGISTRY.json" -exec grep -l "${AGENT_ID}" {} \; 2>/dev/null | head -1 | xargs dirname)

if [ -z "${WORKSPACE}" ] || [ ! -d "${WORKSPACE}" ]; then
    echo "❌ Cannot find workspace for agent ${AGENT_ID}"
    exit 1
fi

# Create progress update
PROGRESS_FILE="${WORKSPACE}/progress/${AGENT_ID}_$(date +%s).json"
mkdir -p "${WORKSPACE}/progress"

cat > "${PROGRESS_FILE}" << EOF
{
  "agent_id": "${AGENT_ID}",
  "timestamp": "$(date -Iseconds)",
  "progress": ${PROGRESS},
  "message": "${MESSAGE}"
}
EOF

# Update registry
REGISTRY="${WORKSPACE}/AGENT_REGISTRY.json"
python3 -c "
import json
from datetime import datetime

with open('${REGISTRY}', 'r') as f:
    registry = json.load(f)

for agent in registry['agents']:
    if agent['id'] == '${AGENT_ID}':
        agent['progress'] = ${PROGRESS}
        agent['last_update'] = datetime.now().isoformat()
        
        if ${PROGRESS} >= 100:
            agent['status'] = 'completed'
            registry['active_count'] = max(0, registry['active_count'] - 1)
            registry['completed_count'] = registry.get('completed_count', 0) + 1
        break

with open('${REGISTRY}', 'w') as f:
    json.dump(registry, f, indent=2)

# Update global registry
global_reg_path = '${AGENT_BASE_DIR}/registry/GLOBAL_REGISTRY.json'
if ${PROGRESS} >= 100:
    with open(global_reg_path, 'r') as f:
        global_reg = json.load(f)
    
    if '${AGENT_ID}' in global_reg.get('agents', {}):
        del global_reg['agents']['${AGENT_ID}']
        global_reg['active_agents'] = max(0, global_reg['active_agents'] - 1)
    
    with open(global_reg_path, 'w') as f:
        json.dump(global_reg, f, indent=2)
"

echo "✅ Progress updated: ${PROGRESS}% - ${MESSAGE}"

if [ "${PROGRESS}" -ge 100 ]; then
    echo "🎉 Agent ${AGENT_ID} completed!"
fi