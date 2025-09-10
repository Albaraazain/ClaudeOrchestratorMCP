#!/bin/bash
# Initialize new task workspace with anti-spiral registry

AGENT_BASE_DIR="${AGENT_BASE_DIR:-.agent-workspace}"
TASK_DESC="${1:-No description provided}"
PRIORITY="${2:-P2}"

# Generate unique task ID
TASK_ID="TASK-$(date +%Y%m%d-%H%M%S)-$(head -c 4 /dev/urandom | xxd -p)"
WORKSPACE="${AGENT_BASE_DIR}/${TASK_ID}"

echo "📂 Initializing workspace: ${TASK_ID}"

# Create directory structure
mkdir -p "${WORKSPACE}"/{context,progress,findings,escalations,logs,rollbacks}

# Create task-specific registry with anti-spiral tracking
cat > "${WORKSPACE}/AGENT_REGISTRY.json" << EOF
{
  "task_id": "${TASK_ID}",
  "task_description": "${TASK_DESC}",
  "created_at": "$(date -Iseconds)",
  "workspace": "${WORKSPACE}",
  "status": "INITIALIZED",
  "priority": "${PRIORITY}",
  "agents": [],
  "agent_hierarchy": {},
  "max_agents": 10,
  "max_depth": 3,
  "max_concurrent": 5,
  "total_spawned": 0,
  "active_count": 0,
  "completed_count": 0,
  "spiral_checks": {
    "enabled": true,
    "last_check": "$(date -Iseconds)",
    "violations": 0
  }
}
EOF

# Update global registry
if [ -f "${AGENT_BASE_DIR}/registry/GLOBAL_REGISTRY.json" ]; then
    python3 -c "
import json
with open('${AGENT_BASE_DIR}/registry/GLOBAL_REGISTRY.json', 'r') as f:
    global_reg = json.load(f)
global_reg['total_tasks'] += 1
global_reg['active_tasks'] += 1
global_reg['tasks']['${TASK_ID}'] = {
    'description': '${TASK_DESC}',
    'created_at': '$(date -Iseconds)',
    'status': 'INITIALIZED'
}
with open('${AGENT_BASE_DIR}/registry/GLOBAL_REGISTRY.json', 'w') as f:
    json.dump(global_reg, f, indent=2)
"
fi

echo "✅ Task initialized: ${TASK_ID}"
echo "   Workspace: ${WORKSPACE}"
echo ""
echo "TASK_ID=${TASK_ID}"