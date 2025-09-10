#!/bin/bash

echo "═══════════════════════════════════════════════════════════"
echo "🎭 CLAUDE ORCHESTRATOR DEMO - Anti-Spiral Protection"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Set PATH
export PATH="$PWD/.agent-workspace/bin:$PATH"

echo "📌 Step 1: Create a task"
echo "───────────────────────────"
TASK_ID=$(agent-ctl init "Optimize database performance" | grep "TASK_ID=" | cut -d= -f2)
echo "Created: $TASK_ID"
echo ""

echo "📌 Step 2: Check initial status"
echo "───────────────────────────────"
agent-ctl status "$TASK_ID"
echo ""

echo "📌 Step 3: Simulate agent deployment"
echo "────────────────────────────────────"
echo "Would deploy: agent-ctl deploy investigator '$TASK_ID' 'Investigate performance issues'"
echo ""

echo "📌 Step 4: Check spiral safety"
echo "───────────────────────────────"
WORKSPACE=".agent-workspace/$TASK_ID" check-spiral
echo ""

echo "📌 Step 5: Global view"
echo "──────────────────────"
agent-ctl list
echo ""

echo "📌 Step 6: Python orchestrator patterns"
echo "────────────────────────────────────────"
cat << 'PYTHON_EXAMPLE'
# Example Python usage:
from orchestrator import HeadlessOrchestrator

orch = HeadlessOrchestrator()

# Pattern 1: Investigation → Fix → Review
task = orch.pattern_investigate_fix("Database slow on user queries")

# Pattern 2: Parallel analysis (limited for safety)
task = orch.pattern_parallel_analysis(
    "Optimize app performance",
    ["database", "api", "frontend"]
)

# The system will:
# - Deploy headless Claude agents
# - Monitor for spiraling
# - Automatically intervene if needed
# - Track everything in registries
PYTHON_EXAMPLE

echo ""
echo "✅ Demo complete! System ready for use."
echo ""
echo "Key features demonstrated:"
echo "  • Task creation and tracking"
echo "  • Anti-spiral checking"
echo "  • Global registry management"
echo "  • Hierarchical agent tracking"
echo ""
echo "Remember: This system NEVER uses the Task tool"
echo "          Only headless Claude instances!"