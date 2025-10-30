# Python Process and Resource Management Research

## Executive Summary

This document presents comprehensive research on Python subprocess management, resource cleanup, and best practices for ensuring proper computing resource lifecycle in the Claude Orchestrator MCP system. Based on current web research (2024-2025) and analysis of the existing codebase, this report identifies gaps and provides actionable recommendations.

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Subprocess Lifecycle Management](#subprocess-lifecycle-management)
3. [Resource Cleanup Patterns](#resource-cleanup-patterns)
4. [Signal Handling for Graceful Shutdown](#signal-handling-for-graceful-shutdown)
5. [Tmux Session Management](#tmux-session-management)
6. [Zombie Process Prevention](#zombie-process-prevention)
7. [Best Practices Summary](#best-practices-summary)
8. [Identified Gaps in Current Implementation](#identified-gaps-in-current-implementation)
9. [Recommended Implementation Plan](#recommended-implementation-plan)

---

## Current State Analysis

### Existing Implementation (real_mcp_server.py)

**What's Working:**
- `kill_tmux_session()` at line 251: Basic tmux session termination
- `kill_real_agent()` at line 3829: Agent termination with registry updates
- Uses `subprocess.run()` for command execution (lines 182, 197, 231, 244, 254)

**Critical Gaps Identified:**
1. **No atexit handlers** - No cleanup on normal program exit
2. **No signal handlers** - No SIGTERM/SIGINT/SIGKILL handling
3. **No subprocess tracking** - No registry of spawned child processes
4. **No resource context managers** - File handles may leak
5. **Fire-and-forget tmux sessions** - No automated cleanup of orphaned sessions
6. **No graceful shutdown mechanism** - Abrupt termination only

---

## Subprocess Lifecycle Management

### Best Practices for Subprocess Creation

#### 1. Use `subprocess.run()` for Simple Cases (Already Implemented ✓)

The current implementation correctly uses `subprocess.run()` for synchronous command execution:

```python
result = subprocess.run(['tmux', '-V'], capture_output=True, text=True, timeout=5)
```

**Advantages:**
- Automatic resource cleanup
- Built-in timeout support
- Simplified error handling

#### 2. Use `subprocess.Popen` with Context Manager for Complex Cases

For long-running processes that need monitoring:

```python
import subprocess
from contextlib import contextmanager

@contextmanager
def managed_subprocess(*args, **kwargs):
    """Context manager for subprocess lifecycle management"""
    process = subprocess.Popen(*args, **kwargs)
    try:
        yield process
    finally:
        # Graceful termination
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        # Close pipes to free resources
        if process.stdin:
            process.stdin.close()
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
```

**Usage:**
```python
with managed_subprocess(['tmux', 'new-session', '-d', '-s', session_name]) as proc:
    # Work with process
    pass
# Automatic cleanup guaranteed
```

#### 3. Timeout Handling Pattern

When a timeout expires, proper cleanup requires:

```python
try:
    result = subprocess.run(cmd, timeout=30, capture_output=True)
except subprocess.TimeoutExpired:
    # Process still running after timeout
    proc.kill()
    proc.communicate()  # Read remaining output and wait
```

---

## Resource Cleanup Patterns

### Context Managers for Resource Management

Context managers provide automatic setup and cleanup, ensuring resources are properly released even when errors occur.

#### File Handle Management

**Problem:** Open file handles consume system resources and can prevent file operations.

**Solution:**
```python
# BAD - No guaranteed cleanup
f = open('file.txt', 'r')
data = f.read()
f.close()  # May not execute if error occurs

# GOOD - Automatic cleanup
with open('file.txt', 'r') as f:
    data = f.read()
# File handle automatically closed, even on exception
```

#### Custom Context Manager for Process Registry

```python
import fcntl
import json
from contextlib import contextmanager

@contextmanager
def registry_lock(registry_path):
    """Locked file access for registry updates"""
    with open(registry_path, 'r+') as f:
        # Acquire exclusive lock
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            registry = json.load(f)
            yield registry
            # Save changes
            f.seek(0)
            f.truncate()
            json.dump(registry, f, indent=2)
        finally:
            # Release lock automatically
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
```

**Usage:**
```python
with registry_lock(registry_path) as registry:
    registry['agents'].append(new_agent)
# Automatic save and lock release
```

### Process Tracking Registry

**Recommendation:** Maintain a runtime registry of all spawned subprocesses for cleanup.

```python
import weakref
from typing import Set

class ProcessTracker:
    """Track all spawned subprocesses for cleanup"""

    def __init__(self):
        # Use weakref.WeakSet to automatically remove terminated processes
        self._processes: Set[subprocess.Popen] = weakref.WeakSet()

    def register(self, process: subprocess.Popen) -> None:
        """Register a subprocess for tracking"""
        self._processes.add(process)

    def cleanup_all(self, timeout: int = 5) -> None:
        """Terminate all tracked processes gracefully"""
        for proc in list(self._processes):
            if proc.poll() is None:  # Still running
                proc.terminate()

        # Wait for graceful termination
        deadline = time.time() + timeout
        for proc in list(self._processes):
            remaining = deadline - time.time()
            if remaining > 0:
                try:
                    proc.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

# Global tracker instance
process_tracker = ProcessTracker()
```

---

## Signal Handling for Graceful Shutdown

### The Problem

**Current Issue:** The MCP server has no signal handlers. When terminated (Ctrl+C, SIGTERM, system shutdown), it cannot:
- Clean up tmux sessions
- Terminate agent processes
- Save state
- Close file handles

### Signal Types

- **SIGTERM**: Polite termination request (allows cleanup)
- **SIGINT**: Interrupt signal (Ctrl+C)
- **SIGKILL**: Immediate termination (cannot be caught)

### Implementation Pattern 1: Simple Flag-Based Handler

```python
import signal
import sys

class GracefulShutdown:
    """Handle shutdown signals gracefully"""

    def __init__(self):
        self.shutdown_requested = False
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        """Signal handler callback"""
        signal_name = signal.Signals(signum).name
        logger.info(f"Received {signal_name}, initiating graceful shutdown")
        self.shutdown_requested = True

    def cleanup(self):
        """Perform cleanup operations"""
        logger.info("Starting cleanup process")

        # 1. Terminate all agent tmux sessions
        self._cleanup_tmux_sessions()

        # 2. Terminate tracked subprocesses
        process_tracker.cleanup_all(timeout=5)

        # 3. Save state to disk
        self._save_shutdown_state()

        logger.info("Cleanup completed")

    def _cleanup_tmux_sessions(self):
        """Kill all orchestrator-managed tmux sessions"""
        try:
            result = subprocess.run(
                ['tmux', 'list-sessions', '-F', '#{session_name}'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                sessions = result.stdout.strip().split('\n')
                for session in sessions:
                    # Only kill orchestrator sessions
                    if session.startswith('claude-agent-'):
                        kill_tmux_session(session)
                        logger.info(f"Killed tmux session: {session}")
        except Exception as e:
            logger.error(f"Error cleaning up tmux sessions: {e}")

    def _save_shutdown_state(self):
        """Save current state for recovery"""
        try:
            state = {
                'shutdown_time': datetime.now().isoformat(),
                'active_tasks': self._get_active_tasks(),
                'reason': 'graceful_shutdown'
            }

            state_file = os.path.join(WORKSPACE_BASE, 'shutdown_state.json')
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving shutdown state: {e}")

# Initialize at module level
shutdown_handler = GracefulShutdown()
```

### Implementation Pattern 2: Threading Event-Based Handler

More sophisticated approach for multi-threaded applications:

```python
import signal
import threading

class ShutdownCoordinator:
    """Coordinate shutdown across threads"""

    def __init__(self):
        self.shutdown_event = threading.Event()
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        """Set shutdown event for all threads"""
        logger.info(f"Shutdown signal received: {signal.Signals(signum).name}")
        self.shutdown_event.set()

    def should_shutdown(self) -> bool:
        """Check if shutdown has been requested"""
        return self.shutdown_event.is_set()

    def wait_for_shutdown(self, timeout: Optional[float] = None) -> bool:
        """Block until shutdown requested or timeout"""
        return self.shutdown_event.wait(timeout)
```

**Usage in main loop:**
```python
coordinator = ShutdownCoordinator()

while not coordinator.should_shutdown():
    # Process work
    process_agents()
    time.sleep(1)

# Shutdown requested
coordinator.cleanup()
```

### atexit Module for Normal Exits

**Use Case:** Clean shutdown when program exits normally (not via signal).

```python
import atexit

def register_exit_handlers():
    """Register cleanup functions for normal program exit"""

    def cleanup_on_exit():
        """Called on normal program termination"""
        logger.info("Program exiting, running cleanup handlers")

        # Cleanup tmux sessions
        shutdown_handler.cleanup()

    atexit.register(cleanup_on_exit)
```

**Important Limitation:** `atexit` handlers are **NOT** called for:
- Unhandled exceptions
- Fatal signals (SIGKILL)
- os._exit() calls
- System crashes

**Therefore:** Use both `atexit` AND signal handlers for comprehensive coverage.

---

## Tmux Session Management

### Automated Cleanup Strategies

#### 1. Session Naming Convention (Already Implemented ✓)

Current pattern: `claude-agent-{task_id}-{agent_id}`

This enables programmatic identification and cleanup.

#### 2. Python Libraries for Tmux Automation

**libtmux** - Typed Python wrapper for tmux:

```python
import libtmux

class TmuxSessionManager:
    """High-level tmux session management"""

    def __init__(self):
        self.server = libtmux.Server()

    def create_agent_session(self, session_name: str, command: str) -> libtmux.Session:
        """Create new tmux session for agent"""
        session = self.server.new_session(
            session_name=session_name,
            window_name='agent',
            start_directory=os.getcwd(),
            attach=False  # Run in background
        )

        # Send command to session
        window = session.attached_window
        pane = window.attached_pane
        pane.send_keys(command)

        return session

    def list_orchestrator_sessions(self) -> List[libtmux.Session]:
        """Get all orchestrator-managed sessions"""
        return [
            s for s in self.server.sessions
            if s.name.startswith('claude-agent-')
        ]

    def cleanup_orphaned_sessions(self) -> int:
        """Remove sessions without active agents"""
        cleaned = 0

        for session in self.list_orchestrator_sessions():
            # Check if agent still exists in registry
            if not self._is_agent_active(session.name):
                session.kill()
                cleaned += 1

        return cleaned

    def _is_agent_active(self, session_name: str) -> bool:
        """Check if session corresponds to active agent"""
        # Parse session name: claude-agent-{task_id}-{agent_id}
        parts = session_name.split('-')
        if len(parts) >= 4:
            task_id = parts[2]
            agent_id = '-'.join(parts[3:])

            # Check registry
            workspace = find_task_workspace(task_id)
            if workspace:
                registry_path = f"{workspace}/AGENT_REGISTRY.json"
                if os.path.exists(registry_path):
                    with open(registry_path, 'r') as f:
                        registry = json.load(f)

                    for agent in registry['agents']:
                        if agent['id'] == agent_id and agent['status'] not in ['terminated', 'completed', 'error']:
                            return True

        return False
```

#### 3. Periodic Cleanup Task

```python
import threading
import time

class PeriodicCleanup:
    """Background thread for periodic resource cleanup"""

    def __init__(self, interval: int = 300):  # 5 minutes
        self.interval = interval
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.tmux_manager = TmuxSessionManager()

    def start(self):
        """Start cleanup thread"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.thread.start()
        logger.info("Periodic cleanup thread started")

    def stop(self):
        """Stop cleanup thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)

    def _cleanup_loop(self):
        """Main cleanup loop"""
        while self.running:
            try:
                self._perform_cleanup()
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

            # Wait for next interval
            time.sleep(self.interval)

    def _perform_cleanup(self):
        """Execute cleanup tasks"""
        logger.debug("Running periodic cleanup")

        # 1. Clean orphaned tmux sessions
        cleaned = self.tmux_manager.cleanup_orphaned_sessions()
        if cleaned > 0:
            logger.info(f"Cleaned {cleaned} orphaned tmux sessions")

        # 2. Check for zombie processes
        self._check_zombie_processes()

        # 3. Clean old workspace files
        self._cleanup_old_workspaces()

    def _check_zombie_processes(self):
        """Detect and clean zombie processes"""
        try:
            result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True,
                text=True,
                timeout=5
            )

            # Look for defunct processes
            lines = result.stdout.split('\n')
            zombies = [line for line in lines if '<defunct>' in line]

            if zombies:
                logger.warning(f"Detected {len(zombies)} zombie processes")
                # Log details for investigation
                for zombie in zombies:
                    logger.warning(f"Zombie: {zombie}")
        except Exception as e:
            logger.error(f"Error checking for zombies: {e}")

    def _cleanup_old_workspaces(self):
        """Remove workspaces older than 7 days"""
        try:
            cutoff = time.time() - (7 * 24 * 60 * 60)  # 7 days

            for task_dir in os.listdir(WORKSPACE_BASE):
                task_path = os.path.join(WORKSPACE_BASE, task_dir)
                if os.path.isdir(task_path):
                    # Check registry for completion status
                    registry_path = os.path.join(task_path, 'AGENT_REGISTRY.json')
                    if os.path.exists(registry_path):
                        mtime = os.path.getmtime(registry_path)
                        if mtime < cutoff:
                            with open(registry_path, 'r') as f:
                                registry = json.load(f)

                            # Only delete completed tasks
                            if registry.get('status') in ['completed', 'terminated']:
                                shutil.rmtree(task_path)
                                logger.info(f"Cleaned old workspace: {task_dir}")
        except Exception as e:
            logger.error(f"Error cleaning old workspaces: {e}")

# Global cleanup scheduler
cleanup_scheduler = PeriodicCleanup(interval=300)
```

---

## Zombie Process Prevention

### What Are Zombie Processes?

A **zombie process** is a process that has finished execution but still has an entry in the process table because its parent hasn't read its exit status.

**Symptoms:**
- Shows as `<defunct>` in process list
- Consumes PID space
- Can prevent new process creation if PIDs exhausted

### Prevention Methods

#### 1. Ignore SIGCHLD Signal (Simplest)

When you don't need child exit status:

```python
import signal

# Automatically reap child processes
signal.signal(signal.SIGCHLD, signal.SIG_IGN)
```

**Effect:** When a child process exits, OS immediately removes it from process table without waiting for parent to call `wait()`.

**Use Case:** Background processes where exit status doesn't matter.

#### 2. Use wait() or poll() with subprocess

**Problem:** subprocess.Popen creates child that becomes zombie if not reaped.

**Solution:**
```python
# Create subprocess
process = subprocess.Popen(['command'])

# Wait for completion (blocks until done)
returncode = process.wait()

# OR poll periodically (non-blocking)
while process.poll() is None:
    time.sleep(1)
    # Process still running

# Process has exited, zombie reaped
```

#### 3. Use communicate() After Termination

**Critical Pattern:**
```python
# Terminate process
process.terminate()

# Wait AND read remaining output
try:
    stdout, stderr = process.communicate(timeout=5)
except subprocess.TimeoutExpired:
    # Still running after timeout
    process.kill()
    stdout, stderr = process.communicate()  # Reap zombie

# Now properly cleaned up
```

#### 4. Use multiprocessing.active_children()

For multiprocessing module:

```python
import multiprocessing

# Automatically cleans up zombie children
multiprocessing.active_children()
```

**Effect:** Joins any finished child processes, preventing zombies.

**Best Practice:** Call periodically in long-running parent process.

#### 5. Track Child PIDs for Cleanup

```python
class ChildProcessManager:
    """Track and clean up child processes"""

    def __init__(self):
        self.children: List[subprocess.Popen] = []

    def spawn(self, *args, **kwargs) -> subprocess.Popen:
        """Spawn and track child process"""
        proc = subprocess.Popen(*args, **kwargs)
        self.children.append(proc)
        return proc

    def reap_zombies(self):
        """Clean up finished children"""
        alive = []
        for proc in self.children:
            if proc.poll() is not None:
                # Process finished, reap zombie
                proc.wait()  # Already done, but ensures cleanup
            else:
                alive.append(proc)

        self.children = alive

    def cleanup_all(self):
        """Terminate all children"""
        for proc in self.children:
            if proc.poll() is None:
                proc.terminate()

        # Wait with timeout
        deadline = time.time() + 5
        for proc in self.children:
            remaining = max(0, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

        self.children.clear()
```

---

## Best Practices Summary

### Subprocess Management Checklist

- ✅ Use `subprocess.run()` for simple, synchronous commands
- ✅ Use `subprocess.Popen` with context managers for long-running processes
- ✅ Always set timeouts for external commands
- ✅ Call `wait()` or `communicate()` after termination to reap zombies
- ✅ Close stdin/stdout/stderr pipes explicitly
- ✅ Track all spawned subprocesses in a registry
- ✅ Use `subprocess.PIPE` sparingly (can deadlock on large output)

### Resource Management Checklist

- ✅ Use context managers (`with` statement) for all resources
- ✅ Implement custom context managers for complex resources
- ✅ Use `fcntl.flock()` for file locking on shared resources
- ✅ Close file handles explicitly in finally blocks if not using context managers
- ✅ Set resource limits using `resource` module
- ✅ Monitor resource usage with `psutil` library

### Signal Handling Checklist

- ✅ Register handlers for SIGTERM and SIGINT
- ✅ Use threading.Event for coordinating shutdown across threads
- ✅ Implement graceful shutdown with timeout
- ✅ Force kill with SIGKILL if graceful shutdown times out
- ✅ Register cleanup functions with `atexit` for normal exits
- ✅ Save state before shutdown for recovery
- ✅ Log all shutdown events for debugging

### Tmux Session Management Checklist

- ✅ Use consistent naming convention for programmatic management
- ✅ Track session names in registry
- ✅ Implement periodic cleanup of orphaned sessions
- ✅ Use `libtmux` library for robust session management
- ✅ Verify session exists before attempting operations
- ✅ Handle tmux server not running gracefully
- ✅ Log all session operations for audit trail

### Zombie Process Prevention Checklist

- ✅ Ignore SIGCHLD if exit status not needed
- ✅ Call `wait()` on all child processes
- ✅ Use `communicate()` after termination
- ✅ Periodically call `multiprocessing.active_children()`
- ✅ Monitor for zombies with `ps aux | grep defunct`
- ✅ Implement automatic cleanup in signal handlers
- ✅ Test cleanup under various failure scenarios

---

## Identified Gaps in Current Implementation

### Critical Issues

1. **No Graceful Shutdown Mechanism**
   - **Location:** real_mcp_server.py
   - **Issue:** No SIGTERM/SIGINT handlers
   - **Impact:** Orphaned tmux sessions, resource leaks on server termination
   - **Risk Level:** HIGH

2. **No Subprocess Tracking**
   - **Location:** Throughout real_mcp_server.py
   - **Issue:** subprocess.run() calls are fire-and-forget
   - **Impact:** Cannot clean up on shutdown, potential zombie processes
   - **Risk Level:** MEDIUM

3. **No atexit Handlers**
   - **Location:** real_mcp_server.py
   - **Issue:** No cleanup on normal program exit
   - **Impact:** Resources not freed on clean shutdown
   - **Risk Level:** MEDIUM

4. **Manual Session Management**
   - **Location:** kill_tmux_session() at line 251
   - **Issue:** Basic subprocess.run() with no error recovery
   - **Impact:** Silent failures, no logging
   - **Risk Level:** MEDIUM

5. **No Periodic Cleanup**
   - **Location:** N/A (missing feature)
   - **Issue:** Orphaned tmux sessions accumulate
   - **Impact:** Resource exhaustion over time
   - **Risk Level:** MEDIUM

6. **No Zombie Process Monitoring**
   - **Location:** N/A (missing feature)
   - **Issue:** No detection or cleanup of zombie processes
   - **Impact:** PID exhaustion possible
   - **Risk Level:** LOW

### Medium Priority Issues

1. **File Handle Management**
   - **Location:** Registry file operations throughout
   - **Issue:** Some operations don't use context managers
   - **Impact:** Potential file handle leaks
   - **Risk Level:** LOW-MEDIUM

2. **No Resource Limits**
   - **Location:** N/A (missing feature)
   - **Issue:** No caps on CPU/memory/processes
   - **Impact:** Resource exhaustion possible
   - **Risk Level:** LOW

---

## Recommended Implementation Plan

### Phase 1: Critical Fixes (Priority: IMMEDIATE)

#### 1.1 Implement Signal Handlers

**File:** real_mcp_server.py

**Add at module level:**
```python
import signal
import threading

class OrchestratorShutdown:
    """Graceful shutdown coordinator"""

    def __init__(self):
        self.shutdown_event = threading.Event()
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        logger.info("Signal handlers registered")

    def _handle_signal(self, signum, frame):
        signal_name = signal.Signals(signum).name
        logger.warning(f"Received {signal_name}, initiating graceful shutdown")
        self.shutdown_event.set()
        self.cleanup()
        sys.exit(0)

    def cleanup(self):
        """Cleanup all resources"""
        logger.info("Starting shutdown cleanup")

        try:
            # 1. Kill all orchestrator tmux sessions
            result = subprocess.run(
                ['tmux', 'list-sessions', '-F', '#{session_name}'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                sessions = result.stdout.strip().split('\n')
                for session in sessions:
                    if session.startswith('claude-agent-'):
                        if kill_tmux_session(session):
                            logger.info(f"Cleaned up session: {session}")

            # 2. Save shutdown state
            self._save_state()

            logger.info("Shutdown cleanup completed")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def _save_state(self):
        """Save shutdown state"""
        try:
            state_file = os.path.join(WORKSPACE_BASE, 'shutdown_state.json')
            state = {
                'timestamp': datetime.now().isoformat(),
                'reason': 'graceful_shutdown'
            }
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

# Initialize at module level (after mcp initialization)
shutdown_coordinator = OrchestratorShutdown()
```

#### 1.2 Add atexit Handler

**Add after shutdown coordinator:**
```python
import atexit

def register_exit_handlers():
    """Register cleanup for normal exit"""
    def exit_cleanup():
        logger.info("Normal program exit, running cleanup")
        shutdown_coordinator.cleanup()

    atexit.register(exit_cleanup)

# Register immediately
register_exit_handlers()
```

### Phase 2: Enhanced Resource Management (Priority: HIGH)

#### 2.1 Implement Process Tracker

**Add new class:**
```python
import weakref

class ProcessRegistry:
    """Track all spawned subprocesses"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._processes = weakref.WeakSet()
        self._lock = threading.Lock()
        self._initialized = True

    def register(self, process: subprocess.Popen):
        """Track subprocess"""
        with self._lock:
            self._processes.add(process)
        logger.debug(f"Registered process PID: {process.pid}")

    def cleanup_all(self, timeout: int = 5):
        """Terminate all tracked processes"""
        processes = list(self._processes)
        logger.info(f"Cleaning up {len(processes)} tracked processes")

        # Terminate
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()

        # Wait with timeout
        deadline = time.time() + timeout
        for proc in processes:
            remaining = max(0.1, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                logger.warning(f"Process {proc.pid} didn't terminate, killing")
                proc.kill()
                proc.wait()

# Global singleton
process_registry = ProcessRegistry()

# Add to shutdown cleanup
# In OrchestratorShutdown.cleanup(), add:
#     process_registry.cleanup_all()
```

#### 2.2 Enhanced Tmux Session Management

**Replace basic kill_tmux_session():**
```python
def kill_tmux_session(session_name: str) -> bool:
    """Kill tmux session with enhanced error handling"""
    try:
        # Check if session exists first
        check_result = subprocess.run(
            ['tmux', 'has-session', '-t', session_name],
            capture_output=True,
            timeout=5
        )

        if check_result.returncode != 0:
            logger.debug(f"Session {session_name} doesn't exist")
            return True  # Already gone

        # Kill session
        kill_result = subprocess.run(
            ['tmux', 'kill-session', '-t', session_name],
            capture_output=True,
            text=True,
            timeout=5
        )

        success = kill_result.returncode == 0
        if success:
            logger.info(f"Killed tmux session: {session_name}")
        else:
            logger.error(f"Failed to kill session {session_name}: {kill_result.stderr}")

        return success

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout killing session {session_name}")
        return False
    except Exception as e:
        logger.error(f"Error killing session {session_name}: {e}")
        return False
```

### Phase 3: Automated Cleanup (Priority: MEDIUM)

#### 3.1 Periodic Cleanup Task

**Add background cleanup thread:**
```python
class PeriodicCleanup:
    """Background cleanup of orphaned resources"""

    def __init__(self, interval: int = 300):
        self.interval = interval
        self.running = False
        self.thread = None

    def start(self):
        """Start cleanup thread"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.thread.start()
        logger.info(f"Periodic cleanup started (interval: {self.interval}s)")

    def stop(self):
        """Stop cleanup thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)

    def _cleanup_loop(self):
        """Main cleanup loop"""
        while self.running:
            try:
                self._run_cleanup()
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

            # Sleep in small chunks to allow quick shutdown
            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)

    def _run_cleanup(self):
        """Execute cleanup tasks"""
        logger.debug("Running periodic cleanup")

        # 1. Clean orphaned tmux sessions
        cleaned = self._cleanup_orphaned_sessions()
        if cleaned > 0:
            logger.info(f"Cleaned {cleaned} orphaned tmux sessions")

        # 2. Reap zombie processes
        process_registry.cleanup_all(timeout=1)

    def _cleanup_orphaned_sessions(self) -> int:
        """Remove tmux sessions without active agents"""
        try:
            result = subprocess.run(
                ['tmux', 'list-sessions', '-F', '#{session_name}'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                return 0

            sessions = [s for s in result.stdout.strip().split('\n') if s]
            cleaned = 0

            for session in sessions:
                if not session.startswith('claude-agent-'):
                    continue

                # Parse: claude-agent-{task_id}-{agent_id}
                parts = session.split('-', 3)
                if len(parts) < 4:
                    continue

                task_id = parts[2]
                agent_id = parts[3]

                # Check if agent still active
                if not self._is_agent_active(task_id, agent_id):
                    if kill_tmux_session(session):
                        cleaned += 1

            return cleaned

        except Exception as e:
            logger.error(f"Error cleaning orphaned sessions: {e}")
            return 0

    def _is_agent_active(self, task_id: str, agent_id: str) -> bool:
        """Check if agent is still active"""
        workspace = find_task_workspace(task_id)
        if not workspace:
            return False

        registry_path = f"{workspace}/AGENT_REGISTRY.json"
        if not os.path.exists(registry_path):
            return False

        try:
            with open(registry_path, 'r') as f:
                registry = json.load(f)

            for agent in registry.get('agents', []):
                if agent['id'] == agent_id:
                    status = agent.get('status')
                    return status not in ['terminated', 'completed', 'error', 'failed']

            return False

        except Exception as e:
            logger.error(f"Error checking agent status: {e}")
            return False

# Initialize and start
cleanup_scheduler = PeriodicCleanup(interval=300)
cleanup_scheduler.start()

# Add to shutdown cleanup
# In OrchestratorShutdown.cleanup(), add:
#     cleanup_scheduler.stop()
```

### Phase 4: Monitoring and Diagnostics (Priority: LOW)

#### 4.1 Resource Usage Monitoring

**Add monitoring endpoint:**
```python
@mcp.tool
def get_resource_status() -> Dict[str, Any]:
    """Get current resource usage"""
    try:
        # Count tmux sessions
        result = subprocess.run(
            ['tmux', 'list-sessions'],
            capture_output=True,
            text=True
        )
        tmux_count = len(result.stdout.strip().split('\n')) if result.returncode == 0 else 0

        # Count active agents
        active_agents = 0
        try:
            global_reg_path = get_global_registry_path(WORKSPACE_BASE)
            if os.path.exists(global_reg_path):
                with open(global_reg_path, 'r') as f:
                    global_reg = json.load(f)
                active_agents = global_reg.get('active_agents', 0)
        except Exception:
            pass

        # Check for zombie processes
        ps_result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True
        )
        zombie_count = ps_result.stdout.count('<defunct>')

        return {
            "tmux_sessions": tmux_count,
            "active_agents": active_agents,
            "zombie_processes": zombie_count,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        return {
            "error": str(e)
        }
```

---

## Code Examples Summary

### Complete Minimal Implementation

Here's a minimal but complete implementation for immediate deployment:

```python
# Add to real_mcp_server.py after imports

import signal
import atexit
import threading

# ============================================================================
# GRACEFUL SHUTDOWN SYSTEM
# ============================================================================

class OrchestratorShutdown:
    """Handles graceful shutdown on SIGTERM/SIGINT"""

    def __init__(self):
        self.shutdown_event = threading.Event()
        # Register signal handlers
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        logger.info("Shutdown handlers registered (SIGTERM, SIGINT)")

    def _handle_signal(self, signum, frame):
        """Handle termination signals"""
        signal_name = signal.Signals(signum).name
        logger.warning(f"Received {signal_name} - initiating graceful shutdown")
        self.shutdown_event.set()
        self.cleanup()
        sys.exit(0)

    def cleanup(self):
        """Clean up all orchestrator resources"""
        if hasattr(self, '_cleanup_done') and self._cleanup_done:
            return  # Prevent duplicate cleanup

        logger.info("=" * 60)
        logger.info("STARTING ORCHESTRATOR CLEANUP")
        logger.info("=" * 60)

        try:
            # 1. Kill all agent tmux sessions
            self._cleanup_tmux_sessions()

            # 2. Save shutdown state
            self._save_shutdown_state()

            logger.info("Orchestrator cleanup completed successfully")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

        self._cleanup_done = True

    def _cleanup_tmux_sessions(self):
        """Terminate all orchestrator-managed tmux sessions"""
        try:
            # List all sessions
            result = subprocess.run(
                ['tmux', 'list-sessions', '-F', '#{session_name}'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode != 0:
                logger.info("No tmux sessions to clean up")
                return

            sessions = [s for s in result.stdout.strip().split('\n') if s]
            agent_sessions = [s for s in sessions if s.startswith('claude-agent-')]

            if not agent_sessions:
                logger.info("No agent tmux sessions found")
                return

            logger.info(f"Cleaning up {len(agent_sessions)} agent tmux sessions")

            for session in agent_sessions:
                try:
                    if kill_tmux_session(session):
                        logger.info(f"  ✓ Killed session: {session}")
                    else:
                        logger.warning(f"  ✗ Failed to kill session: {session}")
                except Exception as e:
                    logger.error(f"  ✗ Error killing {session}: {e}")

        except subprocess.TimeoutExpired:
            logger.error("Timeout while listing tmux sessions")
        except Exception as e:
            logger.error(f"Error cleaning tmux sessions: {e}")

    def _save_shutdown_state(self):
        """Save shutdown state for recovery"""
        try:
            os.makedirs(WORKSPACE_BASE, exist_ok=True)
            state_file = os.path.join(WORKSPACE_BASE, 'shutdown_state.json')

            state = {
                'shutdown_time': datetime.now().isoformat(),
                'reason': 'graceful_shutdown',
                'signal_received': True
            }

            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)

            logger.info(f"Saved shutdown state to: {state_file}")

        except Exception as e:
            logger.error(f"Failed to save shutdown state: {e}")

# Initialize shutdown handler
shutdown_coordinator = OrchestratorShutdown()

# Register atexit handler for normal exits
def exit_cleanup():
    """Cleanup on normal program exit"""
    logger.info("Program exiting normally - running cleanup")
    shutdown_coordinator.cleanup()

atexit.register(exit_cleanup)

logger.info("Resource cleanup system initialized")
```

**Installation Instructions:**

1. Add the above code block after the imports section in `real_mcp_server.py`
2. Ensure it's placed before any MCP tool definitions
3. No additional dependencies required (uses stdlib only)
4. Test by running server and sending SIGTERM: `kill -TERM <pid>`

---

## Testing Procedures

### Test 1: Normal Shutdown

```bash
# Start server
python real_mcp_server.py

# In another terminal, find PID
ps aux | grep real_mcp_server

# Send SIGTERM
kill -TERM <pid>

# Verify cleanup in logs
# Expected: "STARTING ORCHESTRATOR CLEANUP"
# Expected: No orphaned tmux sessions
```

### Test 2: SIGINT (Ctrl+C)

```bash
# Start server
python real_mcp_server.py

# Press Ctrl+C

# Verify cleanup in logs
# Expected: "Received SIGINT"
# Expected: Graceful shutdown
```

### Test 3: Orphaned Session Cleanup

```bash
# Create test tmux session
tmux new-session -d -s claude-agent-test-task-123

# Start server (with periodic cleanup implemented)

# Wait 5+ minutes

# Check sessions
tmux list-sessions

# Expected: claude-agent-test-task-123 removed
```

### Test 4: Resource Leak Test

```bash
# Monitor file descriptors
lsof -p <server_pid> | wc -l

# Deploy multiple agents
# Let them complete

# Check file descriptors again
lsof -p <server_pid> | wc -l

# Expected: Count should return to baseline
```

---

## Conclusion

This research document provides comprehensive guidance for implementing robust resource management in the Claude Orchestrator MCP system. The identified gaps are addressable through systematic implementation of:

1. **Signal handlers** for graceful shutdown
2. **Process tracking** for subprocess management
3. **Periodic cleanup** for long-running resource hygiene
4. **Context managers** for guaranteed resource cleanup
5. **Monitoring** for visibility into resource usage

**Immediate Next Steps:**

1. Implement Phase 1 (signal handlers + atexit)
2. Test shutdown scenarios thoroughly
3. Deploy to production
4. Monitor for orphaned sessions
5. Proceed with Phase 2 when stable

**Success Metrics:**

- Zero orphaned tmux sessions after 24 hours
- No zombie processes in `ps aux` output
- Clean shutdown logs on SIGTERM
- File descriptor count remains stable

---

## References

### Web Research Sources

1. **Python Subprocess Documentation**: https://docs.python.org/3/library/subprocess.html
2. **Context Managers**: https://docs.python.org/3/library/contextlib.html
3. **Signal Handling**: https://docs.python.org/3/library/signal.html
4. **atexit Module**: https://docs.python.org/3/library/atexit.html
5. **libtmux Library**: https://github.com/tmux-python/libtmux

### Stack Overflow References

- Subprocess cleanup: https://stackoverflow.com/questions/16341047/
- Zombie processes: https://stackoverflow.com/questions/2760652/
- Signal handling: https://stackoverflow.com/questions/18499497/
- Graceful shutdown: https://github.com/wbenny/python-graceful-shutdown

### Current Implementation

- **File**: real_mcp_server.py
- **Key Functions**:
  - `kill_tmux_session()` at line 251
  - `kill_real_agent()` at line 3829
  - No signal handlers (identified gap)
  - No atexit handlers (identified gap)

---

*Research completed: 2025-10-29*
*Agent: process_management_researcher-225532-d5e7f5*
*Task: TASK-20251029-225319-45548b6a*
