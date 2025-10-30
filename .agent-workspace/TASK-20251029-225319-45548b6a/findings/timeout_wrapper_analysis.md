# Timeout Wrapper Implementation Analysis

**Agent:** timeout_wrapper_builder-235239-6caa68
**Timestamp:** 2025-10-29 23:52:39
**Status:** CRITICAL ISSUE DISCOVERED

## Environment Check Results

### ❌ CRITICAL: GNU timeout Not Available
- **Issue:** `timeout` command not found on macOS Darwin 25.0.0
- **Alternative:** `gtimeout` (GNU coreutils) also not found
- **Impact:** Cannot use standard GNU timeout approach

## Solution Options

### Option 1: Pure Bash Timeout Implementation ✅ RECOMMENDED
Use bash background process with sleep and kill. Portable, no dependencies.

**Advantages:**
- Works on all Unix systems (Linux, macOS)
- No external dependencies
- Full control over timeout behavior
- Can capture exit codes properly

**Implementation:**
```bash
run_with_timeout() {
    local timeout_seconds="$1"
    shift

    # Validate timeout
    if [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]] || [ "$timeout_seconds" -le 0 ]; then
        log "ERROR: Invalid timeout value: $timeout_seconds"
        return 1
    fi

    # Run command in background
    "$@" &
    local cmd_pid=$!

    # Start timeout monitor in background
    (
        sleep "$timeout_seconds"
        if kill -0 "$cmd_pid" 2>/dev/null; then
            log "⏱️  TIMEOUT: Command exceeded ${timeout_seconds}s: $*"
            kill -TERM "$cmd_pid" 2>/dev/null
            sleep 2
            kill -9 "$cmd_pid" 2>/dev/null
        fi
    ) &
    local monitor_pid=$!

    # Wait for command to complete
    wait "$cmd_pid"
    local exit_code=$?

    # Kill monitor if command finished before timeout
    kill "$monitor_pid" 2>/dev/null
    wait "$monitor_pid" 2>/dev/null

    return "$exit_code"
}
```

### Option 2: Install GNU Coreutils
Require users to install coreutils: `brew install coreutils`

**Disadvantages:**
- External dependency
- Deployment friction
- Not guaranteed on all systems

### Option 3: Hybrid Approach
Detect if timeout/gtimeout available, fallback to bash implementation.

**Complexity:** Higher maintenance burden

## Recommendation

**Implement Option 1:** Pure bash timeout wrapper
- Portable across Linux/macOS
- No dependencies
- Proven reliability
- Matches daemon's existing bash-only approach

## Next Steps

1. Implement pure bash timeout wrapper
2. Add comprehensive error handling
3. Add health check file update function
4. Test with various timeout scenarios
5. Document usage examples
