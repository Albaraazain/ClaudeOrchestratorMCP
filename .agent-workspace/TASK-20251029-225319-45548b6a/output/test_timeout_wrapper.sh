#!/bin/bash
# Test script for run_with_timeout() function
# Tests all timeout scenarios and edge cases

set -euo pipefail

# Source the functions from resource_cleanup_daemon.sh
WORKSPACE_BASE=".agent-workspace"
LOG_FILE="${WORKSPACE_BASE}/timeout_test.log"

mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Run command with timeout protection (pure bash, portable across Linux/macOS)
run_with_timeout() {
    local timeout_seconds="$1"
    shift

    if [[ ! "$timeout_seconds" =~ ^[0-9]+$ ]] || [ "$timeout_seconds" -le 0 ]; then
        log "ERROR: Invalid timeout value: $timeout_seconds"
        return 1
    fi

    "$@" &
    local cmd_pid=$!

    (
        sleep "$timeout_seconds"
        if kill -0 "$cmd_pid" 2>/dev/null; then
            log "⏱️  TIMEOUT: Command exceeded ${timeout_seconds}s limit: $*"
            kill -TERM "$cmd_pid" 2>/dev/null
            sleep 2
            if kill -0 "$cmd_pid" 2>/dev/null; then
                kill -9 "$cmd_pid" 2>/dev/null
            fi
        fi
    ) &
    local monitor_pid=$!

    wait "$cmd_pid" 2>/dev/null
    local exit_code=$?

    kill "$monitor_pid" 2>/dev/null
    wait "$monitor_pid" 2>/dev/null

    if [ "$exit_code" -eq 143 ] || [ "$exit_code" -eq 137 ]; then
        return 124
    fi

    return "$exit_code"
}

update_health_check() {
    local health_file="${WORKSPACE_BASE}/.daemon_health"
    echo "$(date +%s)" > "$health_file" 2>/dev/null || true
}

# Test Suite
echo "=========================================="
echo "Timeout Wrapper Test Suite"
echo "=========================================="
echo ""

# Test 1: Command completes before timeout
echo "Test 1: Normal completion (within timeout)"
if run_with_timeout 5 sleep 1; then
    echo "✅ PASS: Command completed successfully (exit code: 0)"
else
    echo "❌ FAIL: Command failed with exit code: $?"
fi
echo ""

# Test 2: Command exceeds timeout
echo "Test 2: Timeout scenario (command takes too long)"
if run_with_timeout 2 sleep 10; then
    echo "❌ FAIL: Should have timed out"
else
    exit_code=$?
    if [ "$exit_code" -eq 124 ]; then
        echo "✅ PASS: Command timed out correctly (exit code: 124)"
    else
        echo "❌ FAIL: Wrong exit code: $exit_code (expected 124)"
    fi
fi
echo ""

# Test 3: Invalid timeout value (negative)
echo "Test 3: Invalid timeout value (negative)"
if run_with_timeout -5 echo "test" 2>/dev/null; then
    echo "❌ FAIL: Should reject negative timeout"
else
    exit_code=$?
    if [ "$exit_code" -eq 1 ]; then
        echo "✅ PASS: Rejected invalid timeout (exit code: 1)"
    else
        echo "❌ FAIL: Wrong exit code: $exit_code (expected 1)"
    fi
fi
echo ""

# Test 4: Invalid timeout value (zero)
echo "Test 4: Invalid timeout value (zero)"
if run_with_timeout 0 echo "test" 2>/dev/null; then
    echo "❌ FAIL: Should reject zero timeout"
else
    exit_code=$?
    if [ "$exit_code" -eq 1 ]; then
        echo "✅ PASS: Rejected zero timeout (exit code: 1)"
    else
        echo "❌ FAIL: Wrong exit code: $exit_code (expected 1)"
    fi
fi
echo ""

# Test 5: Invalid timeout value (non-numeric)
echo "Test 5: Invalid timeout value (non-numeric)"
if run_with_timeout abc echo "test" 2>/dev/null; then
    echo "❌ FAIL: Should reject non-numeric timeout"
else
    exit_code=$?
    if [ "$exit_code" -eq 1 ]; then
        echo "✅ PASS: Rejected non-numeric timeout (exit code: 1)"
    else
        echo "❌ FAIL: Wrong exit code: $exit_code (expected 1)"
    fi
fi
echo ""

# Test 6: Command with exit code
echo "Test 6: Command with custom exit code"
if run_with_timeout 5 bash -c "exit 42"; then
    echo "❌ FAIL: Should propagate exit code 42"
else
    exit_code=$?
    if [ "$exit_code" -eq 42 ]; then
        echo "✅ PASS: Exit code propagated correctly (exit code: 42)"
    else
        echo "❌ FAIL: Wrong exit code: $exit_code (expected 42)"
    fi
fi
echo ""

# Test 7: Health check function
echo "Test 7: Health check file creation"
update_health_check
if [ -f "${WORKSPACE_BASE}/.daemon_health" ]; then
    timestamp=$(cat "${WORKSPACE_BASE}/.daemon_health")
    if [[ "$timestamp" =~ ^[0-9]+$ ]]; then
        echo "✅ PASS: Health check file created with valid timestamp: $timestamp"
    else
        echo "❌ FAIL: Health check file has invalid timestamp: $timestamp"
    fi
else
    echo "❌ FAIL: Health check file not created"
fi
echo ""

# Test 8: Command with arguments
echo "Test 8: Command with multiple arguments"
if run_with_timeout 5 echo "Hello" "World" > /dev/null; then
    echo "✅ PASS: Command with arguments executed successfully"
else
    echo "❌ FAIL: Command with arguments failed"
fi
echo ""

echo "=========================================="
echo "Test Suite Complete"
echo "=========================================="
echo ""
echo "Check log file for detailed output:"
echo "  ${LOG_FILE}"
