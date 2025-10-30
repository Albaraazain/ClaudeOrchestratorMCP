# Tmux Session Management Best Practices
## Resource Cleanup and Lifecycle Management

**Research Date:** October 29, 2025
**Research Agent:** tmux_best_practices_researcher-225454-a6c34f
**Task ID:** TASK-20251029-225319-45548b6a

---

## Executive Summary

Tmux sessions persist indefinitely until explicitly terminated or the server reboots. Without proper cleanup, sessions accumulate and consume system resources including RAM, CPU, file handles, and process slots. This document provides best practices for tmux session lifecycle management, cleanup strategies, and resource management.

---

## 1. Session Termination Methods

### 1.1 Graceful vs Forceful Termination

#### **Graceful Termination (RECOMMENDED)**

```bash
# Kill specific session (sends SIGHUP to all processes)
tmux kill-session -t session_name

# Kill all sessions except current (if inside tmux)
tmux kill-session -a

# Kill all sessions and server
tmux kill-server
```

**How it works:**
- `kill-session` sends **SIGHUP** signal to all processes in the session
- Most applications handle SIGHUP and shut down cleanly
- Applications can perform cleanup operations before exiting
- Allows processes to close file handles, flush buffers, and terminate gracefully

#### **Forceful Termination (LAST RESORT)**

```bash
# Force kill with SIGKILL (when session is frozen/unresponsive)
tmux kill-session -t session_name
# If above doesn't work, find and kill tmux server process
ps aux | grep tmux | grep session_name
kill -9 <PID>
```

**⚠️ Warning:** SIGKILL immediately terminates processes without cleanup operations. Use only for frozen/unresponsive sessions.

### 1.2 Avoid send-keys for Termination

**❌ DO NOT USE:**
```bash
tmux send-keys -t session_name "exit" Enter
```

**Problems with send-keys:**
- **Timing issues:** Command may not execute depending on session state
- **Unreliable:** Doesn't guarantee process termination
- **Simulates keystrokes:** Not designed for programmatic control
- **Shell-dependent:** Behavior varies by shell type

**✅ INSTEAD USE:**
```bash
tmux kill-session -t session_name  # Proper signal-based termination
```

---

## 2. Detecting Orphaned and Zombie Sessions

### 2.1 List All Sessions

```bash
# Basic listing
tmux list-sessions
tmux ls

# Formatted output for scripts
tmux ls -F "#{session_name}"

# Detailed format with activity time
tmux ls -F "#{session_name},#{session_created},#{session_activity}"
```

### 2.2 Identify Orphaned Sessions

**Signs of orphaned sessions:**
- Session shows in `tmux ls` but has no active clients
- Process tree shows `tmux: server` with question marks instead of pts numbers
- Sessions older than expected lifetime with no recent activity

```bash
# Check for detached sessions
tmux ls | grep -v attached

# List all tmux server processes
ps aux | grep "tmux: server"

# Check session activity time (requires formatting)
tmux ls -F "#{session_name}: Last activity #{t:session_activity}"
```

### 2.3 Zombie Sessions

Zombie sessions are different from dead sessions:
- **Zombie pane:** Created with `set-option -g remain-on-exit on`
- Pane stays visible after process exits (shows "[dead]" status)
- Session itself still exists and consumes resources
- Useful for debugging but should be cleaned up

```bash
# Kill zombie panes within a session
tmux kill-pane -t session_name:window.pane

# Or kill entire session
tmux kill-session -t session_name
```

---

## 3. Resource Management Best Practices

### 3.1 What Resources Do Sessions Consume?

Each tmux session consumes:
- **RAM:** Process memory for tmux server + child processes
- **File handles:** Open file descriptors (logs, pipes, sockets)
- **Process slots:** PIDs for tmux server and child processes
- **CPU:** Minimal when idle, significant during active processes

### 3.2 Regular Cleanup Strategies

#### **Strategy 1: Periodic Manual Cleanup**

```bash
# Weekly cleanup routine
# 1. List all sessions
tmux ls

# 2. Identify unused sessions
# 3. Kill individually or in batch
for session in $(tmux ls -F "#{session_name}"); do
    echo "Kill session: $session? (y/n)"
    read answer
    if [ "$answer" = "y" ]; then
        tmux kill-session -t "$session"
    fi
done
```

#### **Strategy 2: Automated Cleanup by Inactivity**

```bash
#!/bin/bash
# cleanup_inactive_tmux.sh
# Based on research from linkarzu.com

THRESHOLD_MINUTES=110  # Kill sessions inactive for > 110 minutes

for session in $(tmux ls -F "#{session_name}:#{session_activity}"); do
    session_name=$(echo "$session" | cut -d: -f1)
    last_activity=$(echo "$session" | cut -d: -f2)
    current_time=$(date +%s)
    inactive_minutes=$(( (current_time - last_activity) / 60 ))

    if [ $inactive_minutes -gt $THRESHOLD_MINUTES ]; then
        echo "Killing inactive session: $session_name (inactive for $inactive_minutes minutes)"
        tmux kill-session -t "$session_name"
    fi
done
```

#### **Strategy 3: Session Lifecycle Configuration**

```bash
# In ~/.tmux.conf
# Automatically kill detached sessions after 1 hour of inactivity
set-option -g destroy-unattached 3600
```

### 3.3 File Handle Management

**⚠️ CRITICAL:** File handles opened by processes in tmux sessions remain open even after process termination if not explicitly closed.

```bash
# Check open file handles for a tmux session
# 1. Find tmux server PID
ps aux | grep "tmux: server"

# 2. List open files for that PID
lsof -p <tmux_server_pid>

# 3. Check for leaked file handles
lsof -p <tmux_server_pid> | grep -E '(log|jsonl|txt)'
```

**Best Practices:**
- Always close log files explicitly in code (don't rely on process termination)
- Use context managers in Python: `with open(file) as f:`
- For long-running tee commands, ensure they terminate when session ends
- Monitor file handle count: `lsof | wc -l`

---

## 4. Python Integration

### 4.1 Using libtmux Library (RECOMMENDED)

**libtmux** provides a Pythonic API for tmux session management.

```python
import libtmux

# Connect to tmux server
server = libtmux.Server()

# List all sessions
sessions = server.list_sessions()
for session in sessions:
    print(f"Session: {session.name}, Windows: {len(session.windows)}")

# Create new session
session = server.new_session(session_name="my_session", start_directory="/tmp")

# Kill session gracefully
session.kill_session()

# Kill all sessions
for session in server.list_sessions():
    session.kill_session()
```

**Installation:**
```bash
pip install libtmux
```

### 4.2 Using subprocess (Alternative)

```python
import subprocess
import json
from datetime import datetime

def list_tmux_sessions():
    """List all tmux sessions with metadata."""
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name},#{session_created},#{session_activity}"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return []

    sessions = []
    for line in result.stdout.strip().split("\n"):
        if line:
            name, created, activity = line.split(",")
            sessions.append({
                "name": name,
                "created": int(created),
                "last_activity": int(activity)
            })
    return sessions

def kill_tmux_session(session_name):
    """Kill a specific tmux session gracefully."""
    result = subprocess.run(
        ["tmux", "kill-session", "-t", session_name],
        capture_output=True,
        text=True
    )
    return result.returncode == 0

def create_tmux_session(session_name, command=None):
    """Create detached tmux session."""
    cmd = ["tmux", "new-session", "-d", "-s", session_name]
    if command:
        cmd.extend(["-c", command])

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

def cleanup_inactive_sessions(threshold_seconds=3600):
    """Kill sessions inactive for longer than threshold."""
    current_time = datetime.now().timestamp()
    sessions = list_tmux_sessions()

    killed = []
    for session in sessions:
        inactive_time = current_time - session["last_activity"]
        if inactive_time > threshold_seconds:
            if kill_tmux_session(session["name"]):
                killed.append(session["name"])

    return killed
```

### 4.3 Monitoring Session Health

```python
import subprocess
import time

def check_session_exists(session_name):
    """Check if tmux session exists."""
    result = subprocess.run(
        ["tmux", "has-session", "-t", session_name],
        capture_output=True
    )
    return result.returncode == 0

def wait_for_session_completion(session_name, poll_interval=5, timeout=3600):
    """
    Wait for session to complete or timeout.
    Returns True if session ended naturally, False if timeout.
    """
    start_time = time.time()

    while check_session_exists(session_name):
        elapsed = time.time() - start_time
        if elapsed > timeout:
            return False
        time.sleep(poll_interval)

    return True

def get_session_pane_pids(session_name):
    """Get all process PIDs running in session panes."""
    result = subprocess.run(
        ["tmux", "list-panes", "-s", "-t", session_name, "-F", "#{pane_pid}"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return []

    return [int(pid) for pid in result.stdout.strip().split("\n") if pid]
```

---

## 5. Recommended Cleanup Patterns

### 5.1 For Headless Agent Systems (like Claude Orchestrator)

```python
class TmuxSessionManager:
    """Manages tmux sessions with proper cleanup."""

    def __init__(self):
        self.active_sessions = {}  # session_name -> metadata
        self.log_files = {}  # session_name -> open file handle

    def create_agent_session(self, agent_id, command):
        """Create session and track resources."""
        session_name = f"agent_{agent_id}"

        # Create detached session
        subprocess.run([
            "tmux", "new-session", "-d", "-s", session_name,
            "bash", "-c", command
        ])

        # Track session
        self.active_sessions[session_name] = {
            "agent_id": agent_id,
            "created_at": time.time(),
            "command": command
        }

        return session_name

    def cleanup_session(self, session_name):
        """Properly cleanup session and all resources."""
        # 1. Close any open log files
        if session_name in self.log_files:
            self.log_files[session_name].close()
            del self.log_files[session_name]

        # 2. Kill tmux session (sends SIGHUP to processes)
        subprocess.run(["tmux", "kill-session", "-t", session_name])

        # 3. Remove from tracking
        if session_name in self.active_sessions:
            del self.active_sessions[session_name]

        # 4. Cleanup associated files (logs, temp files, etc.)
        # This is application-specific

    def cleanup_all(self):
        """Cleanup all managed sessions."""
        for session_name in list(self.active_sessions.keys()):
            self.cleanup_session(session_name)

    def cleanup_completed_sessions(self):
        """Find and cleanup sessions that have finished."""
        for session_name in list(self.active_sessions.keys()):
            # Check if session still exists
            result = subprocess.run(
                ["tmux", "has-session", "-t", session_name],
                capture_output=True
            )

            # Session doesn't exist anymore - cleanup tracking
            if result.returncode != 0:
                self.cleanup_session(session_name)
```

### 5.2 Wrapper Script Pattern

```bash
#!/bin/bash
# agent_runner.sh - Wrapper with cleanup

SESSION_NAME="$1"
COMMAND="$2"
LOG_FILE="$3"

# Cleanup function
cleanup() {
    echo "Cleaning up session: $SESSION_NAME"

    # Close log file if open (application-specific)
    if [ -f "$LOG_FILE.pid" ]; then
        kill $(cat "$LOG_FILE.pid") 2>/dev/null
        rm "$LOG_FILE.pid"
    fi

    # Kill session
    tmux kill-session -t "$SESSION_NAME" 2>/dev/null
}

# Trap signals for cleanup
trap cleanup EXIT INT TERM

# Create and run tmux session
tmux new-session -d -s "$SESSION_NAME" "$COMMAND"

# Wait for session to complete
while tmux has-session -t "$SESSION_NAME" 2>/dev/null; do
    sleep 5
done

# Cleanup will run automatically via trap
```

### 5.3 Integration with System Monitoring

```python
import psutil
import subprocess

def get_tmux_resource_usage():
    """Get resource usage for all tmux sessions."""
    tmux_processes = []

    for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
        try:
            if 'tmux' in proc.info['name']:
                tmux_processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'memory_mb': proc.info['memory_info'].rss / 1024 / 1024,
                    'cpu_percent': proc.info['cpu_percent']
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    return tmux_processes

def check_resource_leaks():
    """Check for potential resource leaks in tmux sessions."""
    # Check for excessive file handles
    for proc in psutil.process_iter(['pid', 'name', 'num_fds']):
        try:
            if 'tmux' in proc.info['name']:
                if proc.info['num_fds'] > 1000:  # Threshold
                    print(f"⚠️  Potential file handle leak: PID {proc.info['pid']} has {proc.info['num_fds']} open files")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
```

---

## 6. Key Commands Reference

### Session Lifecycle

```bash
# Create
tmux new-session -d -s session_name "command"

# Check existence
tmux has-session -t session_name
echo $?  # 0 = exists, 1 = doesn't exist

# List all
tmux list-sessions
tmux ls

# Get session info
tmux display-message -p -t session_name "#{session_name},#{session_created}"

# Kill specific
tmux kill-session -t session_name

# Kill all except current
tmux kill-session -a

# Kill all
tmux kill-server
```

### Process Management

```bash
# List processes in session
tmux list-panes -s -t session_name -F "#{pane_pid} #{pane_current_command}"

# Send signal to all processes
tmux list-panes -s -t session_name -F "#{pane_pid}" | xargs kill -SIGTERM

# Force kill all processes (LAST RESORT)
tmux list-panes -s -t session_name -F "#{pane_pid}" | xargs kill -9
```

### Monitoring

```bash
# Session activity time
tmux list-sessions -F "#{session_name}: #{session_activity}"

# Check if session is attached
tmux list-sessions -F "#{session_name},#{session_attached}"

# Count windows in session
tmux list-windows -t session_name | wc -l
```

---

## 7. Common Pitfalls and Solutions

### 7.1 File Handles Not Closing

**Problem:** Log files opened by `tee` or redirection remain open even after session ends.

**Solution:**
```python
# ❌ BAD: File handle leaks
subprocess.run(f"command 2>&1 | tee {log_file}", shell=True)

# ✅ GOOD: Explicit file handle management
with open(log_file, 'w') as f:
    proc = subprocess.Popen(command, stdout=f, stderr=subprocess.STDOUT)
    proc.wait()
# File automatically closed when exiting context
```

### 7.2 Orphaned Background Processes

**Problem:** Processes started in tmux session continue running after session is killed.

**Solution:**
```bash
# Ensure processes are in same process group
tmux new-session -d -s session_name "setsid command"

# Or explicitly kill process tree
session_pids=$(tmux list-panes -s -t session_name -F "#{pane_pid}")
for pid in $session_pids; do
    pkill -P $pid  # Kill children
    kill $pid      # Kill parent
done
tmux kill-session -t session_name
```

### 7.3 Race Conditions in Cleanup

**Problem:** Multiple cleanup operations on same session cause errors.

**Solution:**
```python
import threading

class SessionCleanupManager:
    def __init__(self):
        self._cleanup_locks = {}
        self._lock = threading.Lock()

    def cleanup_session(self, session_name):
        # Get or create lock for this session
        with self._lock:
            if session_name not in self._cleanup_locks:
                self._cleanup_locks[session_name] = threading.Lock()
            session_lock = self._cleanup_locks[session_name]

        # Only one thread can cleanup this session at a time
        with session_lock:
            # Perform cleanup
            subprocess.run(["tmux", "kill-session", "-t", session_name])

            # Remove lock
            with self._lock:
                del self._cleanup_locks[session_name]
```

---

## 8. Recommendations for Claude Orchestrator MCP

Based on research and coordination with other investigating agents, here are specific recommendations:

### 8.1 Critical Issues Identified by Other Agents

From coordination data:
- **Resource Leak #1:** JSONL log files opened but never closed (real_mcp_server.py:2375)
- **Partial Cleanup:** `kill_real_agent` only kills tmux session, doesn't close file handles (real_mcp_server.py:3872)
- **No Auto-Cleanup:** progress_watchdog.sh monitors but doesn't trigger cleanup

### 8.2 Recommended Implementation

```python
class AgentSessionManager:
    """Proper resource management for Claude Orchestrator agents."""

    def __init__(self):
        self.sessions = {}  # agent_id -> session_info
        self.cleanup_lock = threading.Lock()

    def deploy_agent(self, agent_id, command, logs_dir):
        """Deploy agent with proper resource tracking."""
        session_name = f"agent_{agent_id}"
        log_file = f"{logs_dir}/{agent_id}_stream.jsonl"

        # Open log file with context manager or explicit handle
        log_handle = open(log_file, 'w', buffering=1)  # Line buffering

        # Create tmux session
        subprocess.run([
            "tmux", "new-session", "-d", "-s", session_name,
            "bash", "-c", command
        ])

        # Track resources
        self.sessions[agent_id] = {
            "session_name": session_name,
            "log_handle": log_handle,
            "log_file": log_file,
            "created_at": time.time(),
            "status": "running"
        }

        return session_name

    def cleanup_agent(self, agent_id):
        """Cleanup all resources for an agent."""
        with self.cleanup_lock:
            if agent_id not in self.sessions:
                return

            session_info = self.sessions[agent_id]

            # 1. Close log file handle
            if session_info["log_handle"]:
                try:
                    session_info["log_handle"].flush()
                    session_info["log_handle"].close()
                except Exception as e:
                    print(f"Error closing log file: {e}")

            # 2. Kill tmux session (sends SIGHUP)
            subprocess.run([
                "tmux", "kill-session", "-t", session_info["session_name"]
            ], stderr=subprocess.DEVNULL)

            # 3. Cleanup temporary files
            # - progress/*.jsonl
            # - findings/*.jsonl
            # - agent_prompt_*.txt

            # 4. Update status
            session_info["status"] = "cleaned"

            # 5. Remove from tracking after grace period
            del self.sessions[agent_id]

    def cleanup_completed_agents(self):
        """Find and cleanup agents that have completed."""
        for agent_id, session_info in list(self.sessions.items()):
            # Check if session still exists
            result = subprocess.run(
                ["tmux", "has-session", "-t", session_info["session_name"]],
                capture_output=True
            )

            if result.returncode != 0:
                # Session ended - cleanup resources
                self.cleanup_agent(agent_id)

    def periodic_cleanup(self, max_age_seconds=7200):
        """Cleanup sessions older than threshold."""
        current_time = time.time()

        for agent_id, session_info in list(self.sessions.items()):
            age = current_time - session_info["created_at"]
            if age > max_age_seconds:
                print(f"Cleaning up aged session: {agent_id} (age: {age}s)")
                self.cleanup_agent(agent_id)
```

### 8.3 Integration Points

**In `real_mcp_server.py`:**

1. **Line ~2375** (deploy_headless_agent): Track log file handle
2. **Line ~3872** (kill_real_agent): Call comprehensive cleanup
3. **New function:** `cleanup_completed_agents()` - periodic cleanup
4. **New function:** `check_resource_leaks()` - monitoring

**Monitoring script:**
```bash
#!/bin/bash
# agent_resource_monitor.sh

while true; do
    # Check for completed agents
    python3 -c "from real_mcp_server import cleanup_completed_agents; cleanup_completed_agents.fn()"

    # Check for resource leaks
    python3 -c "from real_mcp_server import check_resource_leaks; check_resource_leaks.fn()"

    sleep 60
done
```

---

## 9. Testing and Verification

### 9.1 Test Resource Cleanup

```bash
# Create test session
tmux new-session -d -s test_session "sleep 3600"

# Check it exists
tmux has-session -t test_session
echo "Session exists: $?"

# Check file handles
lsof | grep test_session | wc -l

# Kill session
tmux kill-session -t test_session

# Verify cleanup
tmux has-session -t test_session
echo "Session cleaned: $?"

# Verify file handles freed
lsof | grep test_session | wc -l
```

### 9.2 Test Automated Cleanup

```python
def test_automated_cleanup():
    manager = AgentSessionManager()

    # Create test agent
    agent_id = "test_agent_123"
    manager.deploy_agent(agent_id, "echo 'test' && sleep 5", "/tmp/logs")

    # Verify session exists
    assert agent_id in manager.sessions

    # Wait for completion
    time.sleep(10)

    # Run cleanup
    manager.cleanup_completed_agents()

    # Verify cleaned up
    assert agent_id not in manager.sessions

    # Verify tmux session gone
    result = subprocess.run(
        ["tmux", "has-session", "-t", f"agent_{agent_id}"],
        capture_output=True
    )
    assert result.returncode != 0

    print("✅ Automated cleanup test passed")
```

---

## 10. Summary and Action Items

### Key Takeaways

1. **Always use `kill-session`** for graceful termination (not send-keys)
2. **Track all resources** - file handles, processes, temp files
3. **Implement comprehensive cleanup** - not just tmux session
4. **Use libtmux for Python** - cleaner API than subprocess
5. **Monitor regularly** - detect leaks and orphaned sessions
6. **Test cleanup** - verify resources actually freed

### Immediate Action Items for Claude Orchestrator

1. ✅ **Fix JSONL log file handle leaks** (real_mcp_server.py:2375)
   - Use context managers or explicit close operations
   - Track handles in session manager

2. ✅ **Enhance kill_real_agent function** (real_mcp_server.py:3872)
   - Close log file handles
   - Cleanup progress/*.jsonl files
   - Cleanup findings/*.jsonl files
   - Remove temporary prompt files

3. ✅ **Implement periodic cleanup**
   - Background task to cleanup completed agents
   - Resource leak monitoring
   - Age-based cleanup for stuck agents

4. ✅ **Add resource monitoring**
   - Track file handle count per agent
   - Monitor tmux process resource usage
   - Alert on resource leaks

5. ✅ **Update progress_watchdog.sh**
   - Add cleanup trigger for completed agents
   - Remove stale session files

---

## References

### Web Resources
- [Tmux Session Cleanup Script - linkarzu.com](https://linkarzu.com/posts/terminals/tmux-cleanup/)
- [How to Kill Tmux Sessions - IT'S FOSS](https://itsfoss.gitlab.io/post/how-to-kill-tmux-session-4-best-methods/)
- [libtmux Documentation](https://libtmux.git-pull.com/)
- [Tmux Manual Page](https://man7.org/linux/man-pages/man1/tmux.1.html)
- [Stack Overflow: Tmux Session Management](https://stackoverflow.com/questions/tagged/tmux)

### Related Files
- `real_mcp_server.py:2375` - deploy_headless_agent function
- `real_mcp_server.py:3872` - kill_real_agent function
- `progress_watchdog.sh` - Current monitoring script

---

**Document Version:** 1.0
**Last Updated:** 2025-10-29T23:00:00Z
**Researcher:** tmux_best_practices_researcher-225454-a6c34f
