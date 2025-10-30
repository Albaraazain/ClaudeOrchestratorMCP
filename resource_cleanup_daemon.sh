#!/bin/bash
# Resource Cleanup Daemon - Automated cleanup for completed agents
#
# Purpose: Detect completed/terminated agents and free computing resources
# - Kill orphaned tmux sessions
# - Archive/cleanup log files
# - Delete stale prompt files
# - Log all cleanup actions
#
# Created: 2025-10-29
# Agent: cleanup_daemon_builder-232300-9040a9
# Task: TASK-20251029-225319-45548b6a

set -euo pipefail

# Configuration
WORKSPACE_BASE=".agent-workspace"
CHECK_INTERVAL=60  # Check every 60 seconds
LOG_FILE="${WORKSPACE_BASE}/cleanup_daemon.log"
MAX_INACTIVITY_MINUTES=110  # Kill sessions inactive > 110 minutes

# Ensure log file exists
mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Run command with timeout protection (pure bash, portable across Linux/macOS)
# Usage: run_with_timeout <seconds> <command> [args...]
# Returns: command exit code, or 124 if timeout (matching GNU timeout convention)
# Exit codes: 124=timeout, 1=invalid timeout, other=command exit code
run_with_timeout() {
    local timeout_seconds="$1"
    shift

    # Validate timeout value
    if [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]] || [ "$timeout_seconds" -le 0 ]; then
        log "ERROR: Invalid timeout value: $timeout_seconds"
        return 1
    fi

    # Run command in background, capturing output
    "$@" &
    local cmd_pid=$!

    # Start timeout monitor in background
    (
        sleep "$timeout_seconds"
        # Check if process still running
        if kill -0 "$cmd_pid" 2>/dev/null; then
            log "⏱️  TIMEOUT: Command exceeded ${timeout_seconds}s limit: $*"
            # Graceful termination first
            kill -TERM "$cmd_pid" 2>/dev/null
            sleep 2
            # Force kill if still alive
            if kill -0 "$cmd_pid" 2>/dev/null; then
                kill -9 "$cmd_pid" 2>/dev/null
            fi
        fi
    ) &
    local monitor_pid=$!

    # Wait for command to complete
    wait "$cmd_pid" 2>/dev/null
    local exit_code=$?

    # Kill monitor if command finished before timeout
    kill "$monitor_pid" 2>/dev/null
    wait "$monitor_pid" 2>/dev/null

    # Check if process was terminated by our timeout
    # If exit code is 143 (128+15=SIGTERM) or 137 (128+9=SIGKILL), it was our timeout
    if [ "$exit_code" -eq 143 ] || [ "$exit_code" -eq 137 ]; then
        return 124  # Match GNU timeout convention
    fi

    return "$exit_code"
}

# Update health check file (for external monitoring)
# Usage: update_health_check
# Creates/updates timestamp file to prove daemon is alive
update_health_check() {
    local health_file="${WORKSPACE_BASE}/.daemon_health"
    echo "$(date +%s)" > "$health_file" 2>/dev/null || true
}

# Check if tmux session exists
check_session_exists() {
    local session_name="$1"
    run_with_timeout 10 tmux has-session -t "$session_name"
    return $?
}

# Get session last activity time (Unix timestamp)
get_session_activity() {
    local session_name="$1"
    run_with_timeout 10 bash -c "tmux list-sessions -F '#{session_name}:#{session_activity}' 2>/dev/null | grep '^${session_name}:' | cut -d: -f2"
}

# Archive log files for an agent
archive_agent_logs() {
    local workspace="$1"
    local agent_id="$2"
    local archive_dir="${workspace}/archive"

    mkdir -p "$archive_dir"

    local files_archived=0

    # Archive stream log
    if [ -f "${workspace}/logs/${agent_id}_stream.jsonl" ]; then
        mv "${workspace}/logs/${agent_id}_stream.jsonl" "${archive_dir}/" 2>/dev/null && \
            ((files_archived++))
    fi

    # Archive progress log
    if [ -f "${workspace}/progress/${agent_id}_progress.jsonl" ]; then
        mv "${workspace}/progress/${agent_id}_progress.jsonl" "${archive_dir}/" 2>/dev/null && \
            ((files_archived++))
    fi

    # Archive findings log
    if [ -f "${workspace}/findings/${agent_id}_findings.jsonl" ]; then
        mv "${workspace}/findings/${agent_id}_findings.jsonl" "${archive_dir}/" 2>/dev/null && \
            ((files_archived++))
    fi

    echo "$files_archived"
}

# Delete temporary prompt file
delete_prompt_file() {
    local workspace="$1"
    local agent_id="$2"

    if [ -f "${workspace}/agent_prompt_${agent_id}.txt" ]; then
        rm -f "${workspace}/agent_prompt_${agent_id}.txt" 2>/dev/null
        return 0
    fi
    return 1
}

# Clean up a single agent
cleanup_agent() {
    local workspace="$1"
    local agent_id="$2"
    local session_name="$3"
    local reason="$4"

    log "🧹 Cleaning up agent: $agent_id (session: $session_name, reason: $reason)"

    # Statistics
    local actions_performed=0

    # 1. Kill tmux session if still running
    if check_session_exists "$session_name"; then
        run_with_timeout 10 tmux kill-session -t "$session_name" && {
            log "  ✓ Killed tmux session: $session_name"
            ((actions_performed++))
        } || {
            log "  ✗ Failed to kill tmux session: $session_name"
        }
    else
        log "  - Tmux session already terminated: $session_name"
    fi

    # 2. Archive log files
    local files_archived
    files_archived=$(archive_agent_logs "$workspace" "$agent_id")
    if [ "$files_archived" -gt 0 ]; then
        log "  ✓ Archived $files_archived log file(s)"
        ((actions_performed++))
    fi

    # 3. Delete prompt file
    if delete_prompt_file "$workspace" "$agent_id"; then
        log "  ✓ Deleted prompt file"
        ((actions_performed++))
    fi

    # 4. Verify no zombie processes
    local zombie_count
    zombie_count=$(ps aux | grep "$agent_id" | grep -v grep | wc -l || echo 0)
    if [ "$zombie_count" -eq 0 ]; then
        log "  ✓ No zombie processes detected"
    else
        log "  ⚠️  Warning: Found $zombie_count potential zombie process(es)"
    fi

    log "✅ Cleanup completed for $agent_id ($actions_performed actions performed)"
}

# Process completed agents from a registry
process_registry() {
    local registry_path="$1"
    local workspace
    workspace=$(dirname "$registry_path")

    # Check if registry exists and is readable
    if [ ! -f "$registry_path" ] || [ ! -r "$registry_path" ]; then
        return
    fi

    # Use Python to parse JSON (more reliable than jq)
    run_with_timeout 30 python3 - "$registry_path" "$workspace" <<'PYTHON'
import sys
import json

registry_path = sys.argv[1]
workspace = sys.argv[2]

try:
    with open(registry_path, 'r') as f:
        data = json.load(f)

    agents = data.get('agents', [])

    for agent in agents:
        agent_id = agent.get('id')
        status = agent.get('status')
        session_name = agent.get('tmux_session')

        # Only process completed or terminated agents
        if status in ['completed', 'terminated', 'error'] and agent_id and session_name:
            print(f"{agent_id}|{session_name}|{status}")

except Exception as e:
    sys.stderr.write(f"Error processing registry: {e}\n")
    sys.exit(1)
PYTHON
}

# Clean up inactive sessions (safety net for orphaned sessions)
cleanup_inactive_sessions() {
    local current_time
    current_time=$(date +%s)

    # Get all agent sessions
    run_with_timeout 10 bash -c "tmux list-sessions -F '#{session_name}:#{session_activity}' 2>/dev/null | grep '^agent_'" | \
        while IFS=: read -r session_name last_activity; do

        # Calculate inactivity
        local inactive_seconds=$((current_time - last_activity))
        local inactive_minutes=$((inactive_seconds / 60))

        if [ "$inactive_minutes" -gt "$MAX_INACTIVITY_MINUTES" ]; then
            log "⏰ Found inactive session: $session_name (inactive for $inactive_minutes minutes)"

            # Extract agent_id from session_name (format: agent_<agent_id>)
            local agent_id="${session_name#agent_}"

            # Try to find workspace for this agent
            local workspace
            workspace=$(run_with_timeout 60 bash -c "find \"$WORKSPACE_BASE\" -name \"AGENT_REGISTRY.json\" -type f -exec grep -l \"$agent_id\" {} \\; | head -n1 | xargs dirname 2>/dev/null")

            if [ -n "$workspace" ]; then
                cleanup_agent "$workspace" "$agent_id" "$session_name" "inactivity timeout"
            else
                # Just kill the session if we can't find workspace
                log "  ⚠️  Workspace not found, killing session only"
                run_with_timeout 10 tmux kill-session -t "$session_name" && \
                    log "  ✓ Killed inactive session: $session_name"
            fi
        fi
    done
}

# Main daemon loop
main() {
    log "=========================================="
    log "Resource Cleanup Daemon Started"
    log "Workspace base: $WORKSPACE_BASE"
    log "Check interval: ${CHECK_INTERVAL}s"
    log "Max inactivity: ${MAX_INACTIVITY_MINUTES} minutes"
    log "=========================================="

    local iteration=0

    while true; do
        ((iteration++))
        log ""
        log "--- Cleanup Iteration #$iteration ---"

        local agents_cleaned=0

        # Find all AGENT_REGISTRY.json files
        while IFS= read -r registry_path; do
            log "Processing registry: $registry_path"

            # Process each completed agent from this registry
            while IFS='|' read -r agent_id session_name status; do
                # Check if session still exists
                if check_session_exists "$session_name"; then
                    local workspace
                    workspace=$(dirname "$registry_path")
                    cleanup_agent "$workspace" "$agent_id" "$session_name" "status: $status"
                    ((agents_cleaned++))
                else
                    log "  - Agent $agent_id session already cleaned: $session_name"
                fi
            done < <(process_registry "$registry_path")

        done < <(run_with_timeout 60 find "$WORKSPACE_BASE" -name "AGENT_REGISTRY.json" -type f)

        # Clean up inactive sessions (safety net)
        log "Checking for inactive sessions..."
        cleanup_inactive_sessions

        if [ "$agents_cleaned" -eq 0 ]; then
            log "No agents required cleanup"
        else
            log "Summary: Cleaned up $agents_cleaned agent(s)"
        fi

        # Update health check file to indicate daemon is alive
        update_health_check

        log "Next check in ${CHECK_INTERVAL}s"
        sleep "$CHECK_INTERVAL"
    done
}

# Handle signals for graceful shutdown
trap 'log "Received shutdown signal, exiting..."; exit 0' SIGINT SIGTERM

# Start daemon
main
