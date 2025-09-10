#!/bin/bash

# Progress Template Generator - Creates scheduled progress checkpoints
# Usage: ./progress_template_generator.sh AGENT_ID WORKSPACE DURATION_MINUTES

AGENT_ID="$1"
WORKSPACE="$2"
DURATION="${3:-10}"  # Default 10 minutes

PROGRESS_FILE="$WORKSPACE/progress/${AGENT_ID}_progress.jsonl"
TEMPLATE_FILE="$WORKSPACE/progress/${AGENT_ID}_template.jsonl"

echo "📋 Generating progress template for $AGENT_ID"
echo "⏱️  Duration: ${DURATION} minutes with checkpoints every 2 minutes"

# Calculate checkpoint times
START_TIME=$(date +%s)
CHECKPOINTS=$((DURATION / 2))

# Create template with pre-scheduled checkpoints
> "$TEMPLATE_FILE"  # Clear template file

for i in $(seq 0 $CHECKPOINTS); do
    CHECKPOINT_TIME=$((START_TIME + i * 120))  # Every 2 minutes
    TIMESTAMP=$(date -d "@$CHECKPOINT_TIME" -Iseconds)
    PROGRESS=$((i * 100 / CHECKPOINTS))
    
    # Create template entry that agent MUST fill in
    TEMPLATE_ENTRY="{
  \"timestamp\": \"$TIMESTAMP\",
  \"agent_id\": \"$AGENT_ID\",
  \"action\": \"REQUIRED_UPDATE_${i}\",
  \"sub_task\": \"UPDATE_REQUIRED\",
  \"sub_progress\": 0,
  \"overall_progress\": $PROGRESS,
  \"status\": \"PENDING_AGENT_UPDATE\",
  \"context\": \"AGENT MUST UPDATE THIS ENTRY WITH ACTUAL WORK STATUS\",
  \"eta_subtask\": \"UPDATE_REQUIRED\",
  \"eta_overall\": \"UPDATE_REQUIRED\"
}"
    
    echo "$TEMPLATE_ENTRY" >> "$TEMPLATE_FILE"
done

# Create the initial progress file with first template
cp "$TEMPLATE_FILE" "$PROGRESS_FILE"

# Create monitoring script that checks if templates are being updated
cat > "$WORKSPACE/progress/${AGENT_ID}_monitor.sh" << 'EOF'
#!/bin/bash
AGENT_ID="$1"
WORKSPACE="$2"
PROGRESS_FILE="$WORKSPACE/progress/${AGENT_ID}_progress.jsonl"

while true; do
    # Check for pending updates
    PENDING=$(grep -c "PENDING_AGENT_UPDATE" "$PROGRESS_FILE" 2>/dev/null || echo "0")
    
    if [ $PENDING -gt 0 ]; then
        echo "⚠️  Agent $AGENT_ID has $PENDING pending progress updates!"
        
        # Find the agent's tmux session
        SESSION="agent_$AGENT_ID"
        if tmux has-session -t "$SESSION" 2>/dev/null; then
            # Send reminder
            REMINDER="URGENT: You have $PENDING pending progress updates in $PROGRESS_FILE. Please update them with your actual work status immediately!"
            tmux send-keys -t "$SESSION" "echo '$REMINDER'" Enter
        fi
    fi
    
    sleep 60  # Check every minute
done
EOF

chmod +x "$WORKSPACE/progress/${AGENT_ID}_monitor.sh"

echo "✅ Progress template created with $((CHECKPOINTS + 1)) mandatory checkpoints"
echo "🔍 Monitor script: $WORKSPACE/progress/${AGENT_ID}_monitor.sh"
echo ""
echo "📋 Template Preview:"
head -5 "$TEMPLATE_FILE"