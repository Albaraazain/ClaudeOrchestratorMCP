#!/bin/bash
# Safe cleanup script for leaked Claude agent processes and zombie registry entries
# Generated: 2025-10-29 23:32

set -e

echo "======================================================================"
echo "Claude Orchestrator - Resource Cleanup Script"
echo "======================================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Safety check: confirm with user
echo -e "${YELLOW}WARNING: This script will:${NC}"
echo "  1. Kill ALL Claude processes not associated with active tmux sessions"
echo "  2. Remove ghost entries from registries (agents without tmux sessions)"
echo "  3. Update registry counts to reflect reality"
echo ""
echo -e "${YELLOW}Current state:${NC}"
CLAUDE_COUNT=$(ps aux | grep -E "claude|Claude" | grep -v grep | wc -l | xargs)
TMUX_COUNT=$(tmux ls 2>/dev/null | wc -l | xargs)
echo "  - Claude processes running: $CLAUDE_COUNT"
echo "  - Tmux sessions active: $TMUX_COUNT"
echo ""

read -p "Do you want to proceed? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo -e "${RED}Aborted.${NC}"
    exit 1
fi

echo ""
echo "======================================================================"
echo "Step 1: Identifying active tmux sessions"
echo "======================================================================"

# Get list of active tmux sessions (agent sessions only)
ACTIVE_SESSIONS=$(tmux ls 2>/dev/null | grep "agent_" | cut -d: -f1 || true)
echo "Active agent sessions:"
if [ -z "$ACTIVE_SESSIONS" ]; then
    echo "  - None found"
else
    echo "$ACTIVE_SESSIONS" | sed 's/^/  - /'
fi

echo ""
echo "======================================================================"
echo "Step 2: Identifying Claude processes to preserve"
echo "======================================================================"

# For each active tmux session, get the Claude PIDs
PRESERVE_PIDS=""
for SESSION in $ACTIVE_SESSIONS; do
    # Get the pane PID for this session
    PANE_PID=$(tmux list-panes -t "$SESSION" -F "#{pane_pid}" 2>/dev/null || true)
    if [ -n "$PANE_PID" ]; then
        # Get all child processes of this pane
        CHILD_PIDS=$(pgrep -P "$PANE_PID" 2>/dev/null || true)
        if [ -n "$CHILD_PIDS" ]; then
            PRESERVE_PIDS="$PRESERVE_PIDS $CHILD_PIDS"
        fi
    fi
done

echo "PIDs to preserve: $PRESERVE_PIDS"

echo ""
echo "======================================================================"
echo "Step 3: Killing leaked Claude processes"
echo "======================================================================"

# Get all Claude process PIDs
ALL_CLAUDE_PIDS=$(ps aux | grep -E "[Cc]laude" | grep -v grep | awk '{print $2}')

KILLED_COUNT=0
for PID in $ALL_CLAUDE_PIDS; do
    # Check if this PID should be preserved
    SHOULD_PRESERVE=0
    for PRESERVE_PID in $PRESERVE_PIDS; do
        if [ "$PID" = "$PRESERVE_PID" ]; then
            SHOULD_PRESERVE=1
            break
        fi
    done

    if [ $SHOULD_PRESERVE -eq 0 ]; then
        # Check if it's actually a Claude process
        PROCESS_CMD=$(ps -p $PID -o command= 2>/dev/null || true)
        if echo "$PROCESS_CMD" | grep -q -i claude; then
            echo -e "${YELLOW}Killing leaked process:${NC} PID $PID - $PROCESS_CMD"
            kill -9 $PID 2>/dev/null || true
            KILLED_COUNT=$((KILLED_COUNT + 1))
        fi
    fi
done

echo -e "${GREEN}Killed $KILLED_COUNT leaked Claude processes${NC}"

echo ""
echo "======================================================================"
echo "Step 4: Cleaning up zombie tmux sessions (if any)"
echo "======================================================================"

# Kill any tmux sessions that don't have a running Claude process
ZOMBIE_SESSIONS=0
for SESSION in $(tmux ls 2>/dev/null | grep "agent_" | cut -d: -f1 || true); do
    PANE_PID=$(tmux list-panes -t "$SESSION" -F "#{pane_pid}" 2>/dev/null || true)
    if [ -z "$PANE_PID" ]; then
        echo -e "${YELLOW}Killing zombie tmux session:${NC} $SESSION"
        tmux kill-session -t "$SESSION" 2>/dev/null || true
        ZOMBIE_SESSIONS=$((ZOMBIE_SESSIONS + 1))
    fi
done

echo -e "${GREEN}Killed $ZOMBIE_SESSIONS zombie tmux sessions${NC}"

echo ""
echo "======================================================================"
echo "Step 5: Cleaning up ghost registry entries"
echo "======================================================================"

# This step requires Python to manipulate JSON safely
python3 - <<'PYTHON_SCRIPT'
import json
import os
import subprocess
from pathlib import Path

# Get active tmux sessions
result = subprocess.run(['tmux', 'ls'], capture_output=True, text=True, stderr=subprocess.DEVNULL)
active_sessions = set()
if result.returncode == 0:
    for line in result.stdout.strip().split('\n'):
        if line:
            session_name = line.split(':')[0]
            active_sessions.add(session_name)

print(f"Active tmux sessions: {len(active_sessions)}")

# Load global registry
global_registry_path = Path("/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/.agent-workspace/registry/GLOBAL_REGISTRY.json")
with open(global_registry_path, 'r') as f:
    global_registry = json.load(f)

print(f"Registry agents before cleanup: {len(global_registry['agents'])}")

# Remove agents that don't have active tmux sessions
agents_to_remove = []
for agent_id, agent_data in global_registry['agents'].items():
    tmux_session = agent_data.get('tmux_session', '')
    if tmux_session not in active_sessions:
        agents_to_remove.append(agent_id)

print(f"Ghost agents to remove: {len(agents_to_remove)}")

for agent_id in agents_to_remove:
    del global_registry['agents'][agent_id]

# Update counts
global_registry['total_agents_spawned'] = len(global_registry['agents'])
global_registry['active_agents'] = sum(1 for a in global_registry['agents'].values()
                                        if a.get('status') not in ['completed', 'terminated'])

# Save updated registry
with open(global_registry_path, 'w') as f:
    json.dump(global_registry, f, indent=2)

print(f"Registry agents after cleanup: {len(global_registry['agents'])}")
print(f"Active agents count: {global_registry['active_agents']}")
PYTHON_SCRIPT

echo ""
echo "======================================================================"
echo "Cleanup Complete!"
echo "======================================================================"
echo ""
echo -e "${GREEN}Summary:${NC}"
FINAL_CLAUDE_COUNT=$(ps aux | grep -E "claude|Claude" | grep -v grep | wc -l | xargs)
FINAL_TMUX_COUNT=$(tmux ls 2>/dev/null | wc -l | xargs)
echo "  - Claude processes killed: $KILLED_COUNT"
echo "  - Tmux sessions killed: $ZOMBIE_SESSIONS"
echo "  - Claude processes remaining: $FINAL_CLAUDE_COUNT"
echo "  - Tmux sessions remaining: $FINAL_TMUX_COUNT"
echo ""
echo "Run ./verify_cleanup.sh to verify the cleanup was successful."
