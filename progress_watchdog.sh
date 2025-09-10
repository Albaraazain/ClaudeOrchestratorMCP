#!/bin/bash

# Progress Watchdog - Monitors agents and enforces progress updates
WORKSPACE_BASE=".agent-workspace"
SILENCE_THRESHOLD=120  # 2 minutes without progress update

echo "🐕 Starting Progress Watchdog..."

while true; do
    # Find all running agent sessions
    AGENT_SESSIONS=$(tmux list-sessions -F '#{session_name}' | grep '^agent_')
    
    for SESSION in $AGENT_SESSIONS; do
        AGENT_ID=$(echo $SESSION | sed 's/agent_//')
        
        # Find the agent's progress file
        PROGRESS_FILE=$(find "$WORKSPACE_BASE" -name "${AGENT_ID}_progress.jsonl" -type f | head -1)
        
        if [ -f "$PROGRESS_FILE" ]; then
            # Check last progress update time
            LAST_UPDATE=$(tail -1 "$PROGRESS_FILE" | jq -r '.timestamp' 2>/dev/null)
            
            if [ "$LAST_UPDATE" != "null" ] && [ -n "$LAST_UPDATE" ]; then
                LAST_EPOCH=$(date -d "$LAST_UPDATE" +%s 2>/dev/null)
                CURRENT_EPOCH=$(date +%s)
                SILENCE_DURATION=$((CURRENT_EPOCH - LAST_EPOCH))
                
                if [ $SILENCE_DURATION -gt $SILENCE_THRESHOLD ]; then
                    echo "⚠️  Agent $AGENT_ID silent for ${SILENCE_DURATION}s - injecting progress reminder"
                    
                    # Inject progress reminder directly into tmux session
                    REMINDER_CMD="echo '{\"timestamp\": \"$(date -Iseconds)\", \"agent_id\": \"$AGENT_ID\", \"action\": \"progress_reminder\", \"sub_task\": \"Continuing work\", \"sub_progress\": 50, \"overall_progress\": 50, \"status\": \"working\", \"context\": \"Watchdog reminder - please continue documenting your progress\", \"eta_subtask\": \"1m\", \"eta_overall\": \"5m\"}' >> $PROGRESS_FILE"
                    
                    tmux send-keys -t "$SESSION" "$REMINDER_CMD" Enter
                    
                    # Also send a gentle prompt to continue
                    CONTINUE_PROMPT="Please continue your work and update progress every 1-2 minutes using the JSONL format. What are you working on right now?"
                    tmux send-keys -t "$SESSION" "claude --dangerously-skip-permissions --print '$CONTINUE_PROMPT'" Enter
                fi
            fi
        fi
    done
    
    sleep 30  # Check every 30 seconds
done