#!/bin/bash
# Verification script to confirm cleanup was successful
# Generated: 2025-10-29 23:33

set -e

echo "======================================================================"
echo "Claude Orchestrator - Cleanup Verification"
echo "======================================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Count processes
CLAUDE_PROCESSES=$(ps aux | grep -E "[Cc]laude" | grep -v grep | wc -l | xargs)
TMUX_SESSIONS=$(tmux ls 2>/dev/null | wc -l | xargs)
AGENT_TMUX_SESSIONS=$(tmux ls 2>/dev/null | grep "agent_" | wc -l | xargs || echo "0")

echo -e "${BLUE}Current System State:${NC}"
echo "  - Claude processes running: $CLAUDE_PROCESSES"
echo "  - Total tmux sessions: $TMUX_SESSIONS"
echo "  - Agent tmux sessions: $AGENT_TMUX_SESSIONS"
echo ""

# Check registry
echo -e "${BLUE}Registry State:${NC}"
python3 - <<'PYTHON_SCRIPT'
import json
from pathlib import Path

global_registry_path = Path("/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/.agent-workspace/registry/GLOBAL_REGISTRY.json")
with open(global_registry_path, 'r') as f:
    registry = json.load(f)

total_agents = len(registry['agents'])
active_agents = sum(1 for a in registry['agents'].values()
                    if a.get('status') not in ['completed', 'terminated'])
completed_agents = sum(1 for a in registry['agents'].values()
                       if a.get('status') == 'completed')
terminated_agents = sum(1 for a in registry['agents'].values()
                        if a.get('status') == 'terminated')
working_agents = sum(1 for a in registry['agents'].values()
                     if a.get('status') == 'working')

print(f"  - Total agents in registry: {total_agents}")
print(f"  - Active agents: {active_agents}")
print(f"  - Working agents: {working_agents}")
print(f"  - Completed agents: {completed_agents}")
print(f"  - Terminated agents: {terminated_agents}")
print(f"  - Registry metadata total_agents_spawned: {registry.get('total_agents_spawned', 'N/A')}")
print(f"  - Registry metadata active_agents: {registry.get('active_agents', 'N/A')}")

# List active agent sessions
print("")
print("Active agents:")
import subprocess
result = subprocess.run(['tmux', 'ls'], capture_output=True, text=True, stderr=subprocess.DEVNULL)
active_sessions = set()
if result.returncode == 0:
    for line in result.stdout.strip().split('\n'):
        if line and 'agent_' in line:
            session_name = line.split(':')[0]
            active_sessions.add(session_name)

for agent_id, agent_data in registry['agents'].items():
    tmux_session = agent_data.get('tmux_session', '')
    if tmux_session in active_sessions:
        status = agent_data.get('status', 'unknown')
        agent_type = agent_data.get('type', 'unknown')
        task_id = agent_data.get('task_id', 'unknown')
        print(f"  - {agent_id} ({agent_type}) - Status: {status} - Task: {task_id}")

PYTHON_SCRIPT

echo ""
echo -e "${BLUE}Consistency Check:${NC}"

# Check if the number of agent tmux sessions matches registry active agents
python3 - <<'PYTHON_SCRIPT'
import json
import subprocess
from pathlib import Path

# Get active tmux sessions
result = subprocess.run(['tmux', 'ls'], capture_output=True, text=True, stderr=subprocess.DEVNULL)
active_sessions = set()
if result.returncode == 0:
    for line in result.stdout.strip().split('\n'):
        if line and 'agent_' in line:
            session_name = line.split(':')[0]
            active_sessions.add(session_name)

# Load registry
global_registry_path = Path("/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/.agent-workspace/registry/GLOBAL_REGISTRY.json")
with open(global_registry_path, 'r') as f:
    registry = json.load(f)

# Count agents with active tmux sessions
agents_with_sessions = 0
agents_without_sessions = []
for agent_id, agent_data in registry['agents'].items():
    tmux_session = agent_data.get('tmux_session', '')
    if tmux_session in active_sessions:
        agents_with_sessions += 1
    else:
        agents_without_sessions.append((agent_id, agent_data.get('status', 'unknown')))

print(f"  - Agents in registry with active tmux sessions: {agents_with_sessions}")
print(f"  - Agents in registry without tmux sessions: {len(agents_without_sessions)}")
print(f"  - Actual agent tmux sessions: {len(active_sessions)}")

if agents_with_sessions == len(active_sessions):
    print("\n  ✓ PASS: Registry and tmux sessions are synchronized!")
else:
    print(f"\n  ✗ FAIL: Mismatch detected ({agents_with_sessions} in registry vs {len(active_sessions)} in tmux)")

if len(agents_without_sessions) > 0:
    print(f"\n  ⚠ WARNING: {len(agents_without_sessions)} ghost agents still in registry:")
    for agent_id, status in agents_without_sessions[:5]:  # Show first 5
        print(f"    - {agent_id} (status: {status})")
    if len(agents_without_sessions) > 5:
        print(f"    ... and {len(agents_without_sessions) - 5} more")

PYTHON_SCRIPT

echo ""
echo "======================================================================"
echo "Verification Complete"
echo "======================================================================"
