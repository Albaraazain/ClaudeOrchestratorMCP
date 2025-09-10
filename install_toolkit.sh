#!/bin/bash

echo "🚀 Installing Claude Orchestrator Toolkit..."
echo "═══════════════════════════════════════════"

# Create base directories
mkdir -p .agent-workspace/{scripts,templates,bin,registry,locks}

# Create the main control script
cat > .agent-workspace/bin/agent-ctl << 'MAIN_CMD'
#!/bin/bash
AGENT_BASE_DIR="${AGENT_BASE_DIR:-.agent-workspace}"
COMMAND=$1
shift

case $COMMAND in
    init|deploy|status|update|monitor|kill|review|report|list)
        $AGENT_BASE_DIR/scripts/${COMMAND}.sh "$@"
        ;;
    *)
        echo "Usage: agent-ctl {init|deploy|status|update|monitor|kill|review|report|list} [options]"
        echo ""
        echo "Commands:"
        echo "  init <description>     - Initialize new task workspace"
        echo "  deploy <type> <id>     - Deploy headless Claude agent"
        echo "  status <task_id>       - Check task/agent status"
        echo "  update <agent_id>      - Update agent progress"
        echo "  monitor <task_id>      - Monitor agents (anti-spiral)"
        echo "  kill <agent_id>        - Terminate agent safely"
        echo "  review <task_id>       - Generate task review"
        echo "  report <task_id>       - Generate detailed report"
        echo "  list                   - List all active tasks/agents"
        exit 1
        ;;
esac
MAIN_CMD

chmod +x .agent-workspace/bin/agent-ctl

# Create global registry file
cat > .agent-workspace/registry/GLOBAL_REGISTRY.json << 'EOF'
{
  "created_at": "$(date -Iseconds)",
  "total_tasks": 0,
  "active_tasks": 0,
  "total_agents_spawned": 0,
  "active_agents": 0,
  "max_concurrent_agents": 5,
  "max_depth": 3,
  "tasks": {},
  "agents": {}
}
EOF

# Create spawn rules configuration
cat > .agent-workspace/SPAWN_RULES.json << 'EOF'
{
  "orchestrator": ["investigator", "implementer", "reviewer", "fixer"],
  "investigator": ["analyzer"],
  "implementer": ["coder", "tester"],
  "reviewer": [],
  "fixer": ["debugger"],
  "analyzer": [],
  "coder": [],
  "tester": [],
  "debugger": []
}
EOF

echo "✅ Main control script created"
echo "📝 Creating individual scripts..."

# Create all script files
mkdir -p .agent-workspace/scripts

echo "✅ Installation complete!"
echo ""
echo "To use the toolkit:"
echo "  export PATH=\"$PWD/.agent-workspace/bin:\$PATH\""
echo ""
echo "Try it now:"
echo "  agent-ctl init \"Test task\""