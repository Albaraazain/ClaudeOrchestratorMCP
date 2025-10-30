# Timeout Wrapper Quick Reference Card

## Basic Usage

```bash
run_with_timeout <seconds> <command> [args...]
```

## Common Patterns

### 1. Wrap tmux operations
```bash
run_with_timeout 10 tmux kill-session -t "agent-123"
run_with_timeout 5 tmux has-session -t "agent-123"
run_with_timeout 15 tmux capture-pane -t "agent-123" -p
```

### 2. File operations
```bash
run_with_timeout 30 tar -czf archive.tar.gz logs/
run_with_timeout 10 rm -rf /path/to/large/directory
run_with_timeout 5 cp large_file.db backup/
```

### 3. Database/API calls
```bash
run_with_timeout 5 curl -s https://api.example.com/status
run_with_timeout 10 psql -c "SELECT * FROM agents WHERE status='stale';"
run_with_timeout 3 redis-cli GET agent_status
```

### 4. Python scripts
```bash
run_with_timeout 30 python3 update_registry.py "$task_id"
run_with_timeout 60 python3 cleanup_workspaces.py
```

## Exit Code Handling

```bash
run_with_timeout 10 some_command
exit_code=$?

case $exit_code in
    0)
        echo "Success"
        ;;
    124)
        echo "Timeout - command exceeded 10 seconds"
        ;;
    1)
        echo "Invalid timeout value"
        ;;
    *)
        echo "Command failed with exit code: $exit_code"
        ;;
esac
```

## Quick Check Pattern

```bash
if run_with_timeout 10 risky_command; then
    log "Command succeeded"
else
    [ $? -eq 124 ] && log "TIMEOUT" || log "FAILED"
fi
```

## Health Check Usage

```bash
# In main daemon loop
while true; do
    update_health_check  # Updates .agent-workspace/.daemon_health

    # Do cleanup work
    cleanup_agents

    sleep "$CHECK_INTERVAL"
done
```

## External Health Monitoring

```bash
#!/bin/bash
# monitor_daemon.sh - External monitoring script

HEALTH_FILE=".agent-workspace/.daemon_health"
STALE_THRESHOLD=300  # 5 minutes

if [ ! -f "$HEALTH_FILE" ]; then
    echo "ERROR: Daemon not running (no health file)"
    exit 1
fi

LAST_UPDATE=$(cat "$HEALTH_FILE")
NOW=$(date +%s)
AGE=$((NOW - LAST_UPDATE))

if [ "$AGE" -gt "$STALE_THRESHOLD" ]; then
    echo "WARNING: Daemon appears dead (health check ${AGE}s old)"
    exit 1
else
    echo "OK: Daemon healthy (last update ${AGE}s ago)"
    exit 0
fi
```

## Exit Codes Reference

| Code | Meaning |
|------|---------|
| 0 | Command succeeded |
| 1 | Invalid timeout value |
| 124 | Timeout occurred |
| 143 | Terminated by SIGTERM |
| 137 | Terminated by SIGKILL |
| Other | Command's actual exit code |

## Timeout Value Guidelines

| Operation | Recommended Timeout | Reason |
|-----------|-------------------|---------|
| `tmux has-session` | 5-10s | Should be instant |
| `tmux kill-session` | 10-15s | May need cleanup |
| `tar archive` | 30-60s | Depends on size |
| `curl API` | 3-10s | Network timeout |
| `database query` | 5-15s | Prevent deadlocks |
| `python script` | 30-300s | Script complexity |

## Testing Your Timeout

```bash
# Test normal completion
run_with_timeout 5 sleep 1
echo "Exit: $?"  # Should be 0

# Test timeout
run_with_timeout 2 sleep 10
echo "Exit: $?"  # Should be 124

# Test invalid timeout
run_with_timeout -1 echo test 2>/dev/null
echo "Exit: $?"  # Should be 1
```

## Common Mistakes to Avoid

❌ **Wrong:** Timeout = 0
```bash
run_with_timeout 0 command  # ERROR: Invalid timeout
```

✅ **Right:** Timeout >= 1
```bash
run_with_timeout 1 command  # OK: Minimum 1 second
```

❌ **Wrong:** Non-numeric timeout
```bash
run_with_timeout "5s" command  # ERROR: Must be integer
```

✅ **Right:** Integer seconds
```bash
run_with_timeout 5 command  # OK: Integer seconds
```

❌ **Wrong:** Command in quotes
```bash
run_with_timeout 10 "ls -la"  # ERROR: Treats as single command
```

✅ **Right:** Command and args separate
```bash
run_with_timeout 10 ls -la  # OK: Command + args
```

## Log Messages

When timeout occurs, you'll see:
```
[2025-10-29 23:04:15] ⏱️  TIMEOUT: Command exceeded 10s limit: tmux kill-session -t agent-123
```

When invalid timeout:
```
[2025-10-29 23:04:15] ERROR: Invalid timeout value: -5
```

## Files Created

```
.agent-workspace/.daemon_health  ← Health check timestamp (updated by update_health_check)
```

## Source Code Location

```
resource_cleanup_daemon.sh:31-81   ← run_with_timeout() function
resource_cleanup_daemon.sh:83-89   ← update_health_check() function
```

## Need Help?

See full documentation:
- `.agent-workspace/TASK-20251029-225319-45548b6a/output/TIMEOUT_WRAPPER_IMPLEMENTATION.md`

Run test suite:
- `.agent-workspace/TASK-20251029-225319-45548b6a/output/test_timeout_wrapper.sh`
