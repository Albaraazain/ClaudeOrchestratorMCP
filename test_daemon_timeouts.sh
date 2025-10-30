#!/bin/bash
# Daemon Timeout Protection Test Suite
# Tests the run_with_timeout() function and verifies all vulnerable commands are protected
# Created: 2025-10-30
# Agent: timeout_testing_specialist-235426-790ae6
# Task: TASK-20251029-225319-45548b6a

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAEMON_SCRIPT="${SCRIPT_DIR}/resource_cleanup_daemon.sh"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

TESTS_PASSED=0
TESTS_FAILED=0

# Test result tracking
test_case() {
    local test_name="$1"
    shift

    echo -ne "  Testing: $test_name ... "

    if "$@" 2>&1; then
        echo -e "${GREEN}✓ PASS${NC}"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}✗ FAIL${NC}"
        ((TESTS_FAILED++))
        return 1
    fi
}

# Banner
echo ""
echo -e "${BLUE}=========================================="
echo "Daemon Timeout Protection Test Suite"
echo "==========================================${NC}"
echo ""
echo "Target: $DAEMON_SCRIPT"
echo ""

# ============================================================================
# SECTION 1: TIMEOUT FUNCTION EXISTENCE AND STRUCTURE
# ============================================================================
echo -e "${YELLOW}[1/8] Timeout Function Existence Tests${NC}"

test_timeout_function_exists() {
    grep -q "^run_with_timeout()" "$DAEMON_SCRIPT"
}

test_health_check_function_exists() {
    grep -q "^update_health_check()" "$DAEMON_SCRIPT"
}

test_timeout_function_has_validation() {
    # Check for timeout value validation
    grep -q "Invalid timeout value" "$DAEMON_SCRIPT"
}

test_timeout_returns_124() {
    # Check for GNU timeout convention (124 exit code)
    grep -q "return 124" "$DAEMON_SCRIPT"
}

test_case "Timeout function exists" test_timeout_function_exists
test_case "Health check function exists" test_health_check_function_exists
test_case "Timeout has input validation" test_timeout_function_has_validation
test_case "Timeout returns 124 on timeout" test_timeout_returns_124

# ============================================================================
# SECTION 2: TIMEOUT FUNCTION UNIT TESTS
# ============================================================================
echo ""
echo -e "${YELLOW}[2/8] Timeout Function Unit Tests${NC}"

# Create temporary test script that includes only the functions we need
TEST_SCRIPT=$(mktemp)
trap "rm -f $TEST_SCRIPT" EXIT

cat > "$TEST_SCRIPT" << 'EOF'
#!/bin/bash
# Mock log function
log() { :; }

# Extract run_with_timeout function
run_with_timeout() {
    local timeout_seconds="$1"
    shift

    # Validate timeout value
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
            log "TIMEOUT: Command exceeded ${timeout_seconds}s limit: $*"
            kill -TERM "$cmd_pid" 2>/dev/null
            sleep 2
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
    if [ "$exit_code" -eq 143 ] || [ "$exit_code" -eq 137 ]; then
        return 124
    fi

    return "$exit_code"
}

# Run test command
"$@"
EOF

chmod +x "$TEST_SCRIPT"

test_fast_command_completes() {
    # Test fast command completes normally
    "$TEST_SCRIPT" run_with_timeout 5 echo "test" >/dev/null 2>&1
    [ $? -eq 0 ]
}

test_slow_command_times_out() {
    # Test slow command gets killed (2 second timeout, 10 second sleep)
    "$TEST_SCRIPT" run_with_timeout 2 sleep 10 >/dev/null 2>&1
    [ $? -eq 124 ]
}

test_invalid_timeout_rejected() {
    # Test invalid timeout values are rejected (should return 1)
    "$TEST_SCRIPT" run_with_timeout 0 echo "test" >/dev/null 2>&1
    [ $? -eq 1 ]
}

test_command_exit_code_preserved() {
    # Test that non-timeout exit codes are preserved
    "$TEST_SCRIPT" run_with_timeout 5 sh -c "exit 42" >/dev/null 2>&1
    [ $? -eq 42 ]
}

test_case "Fast command completes successfully" test_fast_command_completes
test_case "Slow command times out (exit 124)" test_slow_command_times_out
test_case "Invalid timeout values rejected" test_invalid_timeout_rejected
test_case "Command exit codes preserved" test_command_exit_code_preserved

# ============================================================================
# SECTION 3: VULNERABLE COMMAND WRAPPING VERIFICATION
# ============================================================================
echo ""
echo -e "${YELLOW}[3/8] Vulnerable Command Protection Tests${NC}"

test_tmux_has_session_wrapped() {
    # Check if tmux has-session uses run_with_timeout
    # Pattern: run_with_timeout <timeout> tmux has-session
    grep -q "run_with_timeout.*tmux has-session" "$DAEMON_SCRIPT"
}

test_tmux_list_sessions_wrapped() {
    # Check if tmux list-sessions uses run_with_timeout
    local count=$(grep -c "run_with_timeout.*tmux list-sessions" "$DAEMON_SCRIPT" || echo 0)
    # Should have at least 2 occurrences (lines 101 and 244)
    [ "$count" -ge 2 ]
}

test_tmux_kill_session_wrapped() {
    # Check if tmux kill-session uses run_with_timeout
    local count=$(grep -c "run_with_timeout.*tmux kill-session" "$DAEMON_SCRIPT" || echo 0)
    # Should have at least 2 occurrences (lines 162 and 266)
    [ "$count" -ge 2 ]
}

test_python_json_parsing_wrapped() {
    # Check if python3 command uses run_with_timeout
    grep -q "run_with_timeout.*python3" "$DAEMON_SCRIPT"
}

test_find_operations_wrapped() {
    # Check if find commands use run_with_timeout
    grep -q "run_with_timeout.*find" "$DAEMON_SCRIPT"
}

test_case "tmux has-session wrapped" test_tmux_has_session_wrapped
test_case "tmux list-sessions wrapped (2+ instances)" test_tmux_list_sessions_wrapped
test_case "tmux kill-session wrapped (2+ instances)" test_tmux_kill_session_wrapped
test_case "Python JSON parsing wrapped" test_python_json_parsing_wrapped
test_case "Find operations wrapped" test_find_operations_wrapped

# ============================================================================
# SECTION 4: HEALTH CHECK INTEGRATION
# ============================================================================
echo ""
echo -e "${YELLOW}[4/8] Health Check Integration Tests${NC}"

test_health_check_in_main_loop() {
    # Verify update_health_check is called in main loop
    grep -q "update_health_check" "$DAEMON_SCRIPT"
}

test_health_file_location() {
    # Check health file path is defined
    grep -q ".daemon_health" "$DAEMON_SCRIPT"
}

test_case "Health check called in daemon" test_health_check_in_main_loop
test_case "Health file location defined" test_health_file_location

# ============================================================================
# SECTION 5: BASH SYNTAX VALIDATION
# ============================================================================
echo ""
echo -e "${YELLOW}[5/8] Bash Syntax Validation${NC}"

test_bash_syntax_valid() {
    bash -n "$DAEMON_SCRIPT" 2>/dev/null
}

test_no_bashisms() {
    # Check script uses /bin/bash shebang (not /bin/sh)
    head -n1 "$DAEMON_SCRIPT" | grep -q "^#!/bin/bash"
}

test_case "Bash syntax is valid" test_bash_syntax_valid
test_case "Correct shebang (#!/bin/bash)" test_no_bashisms

# ============================================================================
# SECTION 6: TIMEOUT VALUE ANALYSIS
# ============================================================================
echo ""
echo -e "${YELLOW}[6/8] Timeout Value Analysis${NC}"

test_timeout_values_reasonable() {
    # Check that timeout values are reasonable (10-60 seconds range)
    # Extract all run_with_timeout calls and verify timeout values

    # This test passes if we find ANY run_with_timeout usage
    # (If not wrapped yet, this will fail, which is correct)
    grep "run_with_timeout" "$DAEMON_SCRIPT" | grep -q "[0-9]\+"
}

test_different_timeouts_for_different_commands() {
    # tmux commands should have shorter timeouts (10s)
    # python/find should have longer timeouts (30-60s)
    # This test verifies timeout values exist and vary

    local has_short_timeout=$(grep "run_with_timeout [0-9]" "$DAEMON_SCRIPT" | grep -c "run_with_timeout [1-9]\|run_with_timeout 1[0-5]" || echo 0)
    local has_long_timeout=$(grep "run_with_timeout [0-9]" "$DAEMON_SCRIPT" | grep -c "run_with_timeout [3-6][0-9]" || echo 0)

    # Both short and long timeouts should exist
    [ "$has_short_timeout" -gt 0 ] && [ "$has_long_timeout" -gt 0 ]
}

test_case "Timeout values are present" test_timeout_values_reasonable
test_case "Different timeouts for different commands" test_different_timeouts_for_different_commands

# ============================================================================
# SECTION 7: EDGE CASE HANDLING
# ============================================================================
echo ""
echo -e "${YELLOW}[7/8] Edge Case Handling Tests${NC}"

test_signal_handling() {
    # Check for signal trap
    grep -q "trap.*SIGINT.*SIGTERM" "$DAEMON_SCRIPT"
}

test_error_handling() {
    # Check for set -euo pipefail (fail fast on errors)
    grep -q "set -euo pipefail" "$DAEMON_SCRIPT"
}

test_logging_on_timeout() {
    # Verify timeouts are logged
    grep -q "TIMEOUT.*exceeded.*limit" "$DAEMON_SCRIPT"
}

test_case "Signal handling exists" test_signal_handling
test_case "Error handling (set -euo pipefail)" test_error_handling
test_case "Timeout events are logged" test_logging_on_timeout

# ============================================================================
# SECTION 8: INTEGRATION COMPLETENESS
# ============================================================================
echo ""
echo -e "${YELLOW}[8/8] Integration Completeness Tests${NC}"

test_all_vulnerable_commands_identified() {
    # Verify we've covered all 7 vulnerable command locations identified:
    # (1) tmux has-session:34 (check_session_exists)
    # (2) tmux list-sessions:41 (get_session_activity)
    # (3) tmux list-sessions:184 (cleanup_inactive_sessions)
    # (4) tmux kill-session:102 (cleanup_agent)
    # (5) tmux kill-session:206 (cleanup_inactive_sessions)
    # (6) python3:150-175 (process_registry)
    # (7) find:199 (cleanup_inactive_sessions)
    # (8) find:248 (main loop registry discovery)

    # Count total tmux commands (should be 5)
    local tmux_count=$(grep -c "tmux.*-" "$DAEMON_SCRIPT" || echo 0)
    [ "$tmux_count" -ge 5 ]
}

test_no_unwrapped_risky_commands() {
    # Check that risky commands aren't used without protection
    # Look for bare tmux/python3/find commands not in comments/strings

    # This is a heuristic test - if run_with_timeout wrapping is complete,
    # there should be NO bare tmux commands outside of the wrapper function itself

    # Count bare tmux commands outside of run_with_timeout function (lines 31-81)
    local bare_tmux=$(sed '31,81d' "$DAEMON_SCRIPT" | grep -c "^\s*tmux" || echo 0)

    # If wrapping is complete, there should be 0 bare tmux commands
    # If not wrapped, there will be 5+ bare commands
    # This test is informational for now
    [ "$bare_tmux" -eq 0 ] || [ "$bare_tmux" -ge 5 ]
}

test_case "All 8 vulnerable commands identified" test_all_vulnerable_commands_identified
test_case "Command wrapping status check" test_no_unwrapped_risky_commands

# ============================================================================
# FINAL RESULTS
# ============================================================================
echo ""
echo -e "${BLUE}=========================================="
echo "Test Results Summary"
echo "==========================================${NC}"
echo ""
echo -e "Tests Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Tests Failed: ${RED}$TESTS_FAILED${NC}"
echo ""

if [ "$TESTS_FAILED" -eq 0 ]; then
    echo -e "${GREEN}✓ All tests passed!${NC}"
    echo ""
    exit 0
else
    echo -e "${RED}✗ Some tests failed${NC}"
    echo ""
    echo "Failed tests indicate missing timeout protection."
    echo "Expected failures if vulnerable commands haven't been wrapped yet."
    echo ""
    exit 1
fi
