# Test Coverage Review for Resource Cleanup Implementation

**Review Date:** 2025-10-29
**Reviewer:** test_coverage_reviewer-233831-80774f
**Task:** TASK-20251029-225319-45548b6a

---

## Executive Summary

**CRITICAL FINDING:** The resource cleanup implementation has **ZERO automated test coverage**. While the implementation is comprehensive and well-documented, there are no tests to verify:
- `cleanup_agent_resources()` function behavior
- `kill_real_agent` cleanup integration
- File tracking system
- Daemon script functionality
- Edge cases and error handling

**Severity:** CRITICAL - Production deployment without tests creates high risk of regressions and undetected bugs.

**Recommendation:** Immediate creation of comprehensive test suite before production deployment.

---

## Current Test Coverage Status

### Existing Test Infrastructure

The project has a `tests/` directory with these test files:
- `tests/test_project_context.py` - Project context detection
- `tests/test_core_functions.py` - Core MCP functions
- `tests/test_mcp_tools.py` - MCP tool interfaces
- `tests/test_smart_truncation.py` - Output truncation logic
- `tests/test_coordination_truncation.py` - Coordination data truncation

**Testing Framework:** pytest (inferred from test file naming)

### Coverage Gaps

| Component | Coverage Status | Priority |
|-----------|----------------|----------|
| `cleanup_agent_resources()` | **0%** - No tests exist | CRITICAL |
| `kill_real_agent` cleanup integration | **0%** - No tests exist | CRITICAL |
| File tracking system | **0%** - No tests exist | CRITICAL |
| `resource_cleanup_daemon.sh` | **0%** - No tests exist | HIGH |
| Edge cases (crashes, zombies) | **0%** - No tests exist | HIGH |
| Integration with `update_agent_progress` | **N/A** - Not yet implemented | PENDING |

---

## Required Test Coverage

### 1. cleanup_agent_resources() Unit Tests

**Location to test:** `real_mcp_server.py:3940-4124`

**Test Cases Required:**

#### TC1.1: Successful Complete Cleanup
```python
def test_cleanup_agent_resources_success():
    """
    Verify all resources cleaned up successfully when agent completes normally.

    Given: Agent with all files present and tmux session running
    When: cleanup_agent_resources() called with keep_logs=True
    Then:
      - Tmux session killed
      - Prompt file deleted
      - 3 log files archived to workspace/archive/
      - No zombie processes detected
      - success=True returned
    """
```

**Coverage:** Lines 3940-4124 (all code paths)

#### TC1.2: Cleanup with Deletion (keep_logs=False)
```python
def test_cleanup_agent_resources_delete_logs():
    """
    Verify logs are deleted when keep_logs=False.

    Given: Agent with all files present
    When: cleanup_agent_resources() called with keep_logs=False
    Then:
      - All JSONL files deleted (not archived)
      - No archive directory created
      - success=True returned
    """
```

**Coverage:** Lines 4059-4071 (delete branch)

#### TC1.3: Partial File Existence
```python
def test_cleanup_agent_resources_missing_files():
    """
    Verify cleanup succeeds even when some files don't exist.

    Given: Agent with only prompt file and stream log (no progress/findings)
    When: cleanup_agent_resources() called
    Then:
      - Existing files cleaned up
      - Missing files skipped without error
      - success=True returned
    """
```

**Coverage:** Lines 4006-4016 (file existence checks), 4042-4055 (archive loop)

#### TC1.4: Tmux Session Already Gone
```python
def test_cleanup_agent_resources_session_terminated():
    """
    Verify cleanup succeeds when tmux session already terminated.

    Given: Agent with files but no tmux session
    When: cleanup_agent_resources() called
    Then:
      - tmux_session_killed=True (already gone)
      - Files still cleaned up
      - success=True returned
    """
```

**Coverage:** Lines 3988-4001 (session existence check)

#### TC1.5: Zombie Process Detection
```python
def test_cleanup_agent_resources_zombie_detection():
    """
    Verify zombie processes are detected and reported.

    Given: Agent with lingering Claude processes after tmux kill
    When: cleanup_agent_resources() called
    Then:
      - Zombie processes detected and counted
      - zombie_processes count in results
      - zombie_process_details contains process info
      - warning logged
      - Overall cleanup still succeeds (critical ops done)
    """
```

**Coverage:** Lines 4073-4110 (zombie verification)

#### TC1.6: Archive Directory Creation Failure
```python
def test_cleanup_agent_resources_archive_fail_fallback():
    """
    Verify fallback to deletion when archive directory can't be created.

    Given: Archive directory creation fails (permissions, disk full, etc.)
    When: cleanup_agent_resources() called with keep_logs=True
    Then:
      - Error logged for archive directory creation
      - Falls back to deletion mode (keep_logs=False)
      - Files deleted instead of archived
      - Partial success with errors array populated
    """
```

**Coverage:** Lines 4032-4039 (archive dir creation error handling)

#### TC1.7: File Move Failure Handling
```python
def test_cleanup_agent_resources_file_move_errors():
    """
    Verify individual file move failures don't stop entire cleanup.

    Given: One log file locked/in-use, others available
    When: cleanup_agent_resources() called
    Then:
      - Available files archived successfully
      - Locked file logs error
      - errors array contains failure details
      - Partial success (some files cleaned)
    """
```

**Coverage:** Lines 4042-4055 (per-file error handling)

#### TC1.8: Overall Success Determination
```python
def test_cleanup_agent_resources_success_criteria():
    """
    Verify success determination based on critical operations.

    Test scenarios:
    - All critical ops succeed → success=True
    - Tmux kill fails → success=False
    - Prompt delete fails → success=False
    - Log archive fails → success=False
    - Zombie detection fails → success=True (non-critical)
    """
```

**Coverage:** Lines 4112-4124 (success determination logic)

---

### 2. kill_real_agent Integration Tests

**Location to test:** `real_mcp_server.py:3867-3938`

**Test Cases Required:**

#### TC2.1: Integration with cleanup_agent_resources()
```python
def test_kill_real_agent_calls_cleanup():
    """
    Verify kill_real_agent calls cleanup_agent_resources.

    Given: Running agent with all resources
    When: kill_real_agent() called
    Then:
      - cleanup_agent_resources() called with correct params
      - Cleanup results included in return dict
      - Registry updated with terminated status
      - All resources freed
    """
```

**Coverage:** Lines 3878-3883 (cleanup call integration)

#### TC2.2: Cleanup Results in Return Value
```python
def test_kill_real_agent_returns_cleanup_status():
    """
    Verify kill_real_agent return value includes cleanup status.

    Given: Agent termination with partial cleanup failure
    When: kill_real_agent() called
    Then:
      - Return dict contains 'cleanup' key
      - Cleanup results show partial success
      - Caller can verify which files cleaned
    """
```

**Coverage:** Lines 3925-3932 (return value structure)

---

### 3. File Tracking System Tests

**Location to test:** `real_mcp_server.py:2417-2423` (deploy), 3878-3904 (cleanup)

**Test Cases Required:**

#### TC3.1: File Tracking on Deployment
```python
def test_deploy_agent_tracks_files():
    """
    Verify agent deployment creates tracked_files in registry.

    Given: New agent deployment
    When: deploy_headless_agent() completes
    Then:
      - Agent registry entry contains 'tracked_files' dict
      - All 5 file paths present: prompt, log, progress, findings, deploy
      - Paths are absolute and correct
    """
```

**Coverage:** Lines 2417-2423 in deploy_headless_agent

#### TC3.2: Backwards Compatibility with Old Agents
```python
def test_kill_old_agent_without_tracked_files():
    """
    Verify cleanup works with old agents (no tracked_files).

    Given: Agent registry entry without 'tracked_files' key
    When: kill_real_agent() called
    Then:
      - No error thrown
      - Tmux session still killed
      - Cleanup skips file deletion gracefully
    """
```

**Coverage:** Lines 3878-3904 (agent.get('tracked_files', {}))

---

### 4. Daemon Script Tests

**Location to test:** `resource_cleanup_daemon.sh`

**Test Cases Required:**

#### TC4.1: Registry Processing
```python
def test_daemon_processes_registry():
    """
    Verify daemon correctly parses AGENT_REGISTRY.json.

    Given: Registry with 3 completed agents
    When: process_registry() called
    Then:
      - Python JSON parser extracts all 3 agents
      - Only completed/terminated/error status agents returned
      - Running agents skipped
    """
```

**Coverage:** Lines 138-176 (process_registry function)

#### TC4.2: Session Cleanup
```python
def test_daemon_cleanup_agent():
    """
    Verify daemon cleanup_agent() function.

    Given: Completed agent with running tmux session
    When: cleanup_agent() called
    Then:
      - Tmux session killed
      - Log files archived
      - Prompt file deleted
      - Zombie check performed
      - Actions logged
    """
```

**Coverage:** Lines 88-136 (cleanup_agent function)

#### TC4.3: Inactive Session Detection
```python
def test_daemon_inactive_session_cleanup():
    """
    Verify daemon cleans up sessions inactive > MAX_INACTIVITY_MINUTES.

    Given: Agent session inactive for 120 minutes (> 110 threshold)
    When: cleanup_inactive_sessions() runs
    Then:
      - Session detected as inactive
      - Workspace found via registry search
      - cleanup_agent() called with reason='inactivity timeout'
    """
```

**Coverage:** Lines 178-211 (cleanup_inactive_sessions)

#### TC4.4: Zombie Process Detection Bug
```python
def test_daemon_zombie_detection_bug():
    """
    CRITICAL BUG TEST: Verify zombie detection doesn't count grep itself.

    Bug Location: Line 128
    Buggy Code: zombie_count=$(ps aux | grep -c "$agent_id" | grep -v grep || echo 0)
    Issue: grep -c counts BEFORE grep -v grep, always counts itself

    Given: No zombie processes exist for agent
    When: Zombie detection runs
    Then:
      - CURRENT BEHAVIOR: Reports 1 zombie (false positive)
      - EXPECTED: Reports 0 zombies

    This test WILL FAIL with current implementation.
    Fix: zombie_count=$(ps aux | grep "$agent_id" | grep -v grep | wc -l)
    """
```

**Coverage:** Lines 127-133 (zombie detection - KNOWN BUG)

---

### 5. Integration Test Scenarios (from RESOURCE_LIFECYCLE_ANALYSIS.md Section 8)

#### Scenario 1: Normal Completion
```python
def test_integration_normal_completion():
    """
    Test Scenario 1 from analysis: Agent completes normally.

    1. Deploy test agent
    2. Agent reports status='completed' via update_agent_progress
    3. Verify:
       - Tmux session killed
       - Prompt file deleted
       - Logs archived
       - No zombie processes
       - Files exist in archive/
       - Active file count decreased
    """
```

**Reference:** RESOURCE_LIFECYCLE_ANALYSIS.md:480-488

#### Scenario 2: Manual Termination
```python
def test_integration_manual_termination():
    """
    Test Scenario 2 from analysis: User manually terminates agent.

    1. Deploy test agent
    2. Call kill_real_agent directly
    3. Verify same cleanup as Scenario 1
    4. Verify cleanup results returned to caller
    """
```

**Reference:** RESOURCE_LIFECYCLE_ANALYSIS.md:490-493

#### Scenario 3: Error/Crash
```python
def test_integration_agent_crash():
    """
    Test Scenario 3 from analysis: Agent crashes or is killed externally.

    1. Deploy test agent
    2. Simulate crash: kill -9 tmux session
    3. Wait for daemon cycle
    4. Verify daemon detects and cleans up orphaned resources
    5. Verify no files left behind
    """
```

**Reference:** RESOURCE_LIFECYCLE_ANALYSIS.md:495-498

#### Scenario 4: Resource Accumulation Prevention
```python
def test_integration_resource_accumulation():
    """
    Test Scenario 4 from analysis: Multiple agents don't accumulate resources.

    1. Deploy 10 test agents
    2. All complete normally
    3. Verify:
       - Only 10 archived log sets exist
       - No active tmux sessions remain
       - Process count returns to baseline
       - Disk space bounded (not growing unbounded)
    """
```

**Reference:** RESOURCE_LIFECYCLE_ANALYSIS.md:500-506

---

## Test Infrastructure Requirements

### Mock/Fixture Setup

```python
@pytest.fixture
def test_workspace(tmp_path):
    """Create test workspace with expected directory structure."""
    workspace = tmp_path / "test_workspace"
    (workspace / "logs").mkdir(parents=True)
    (workspace / "progress").mkdir(parents=True)
    (workspace / "findings").mkdir(parents=True)
    return str(workspace)

@pytest.fixture
def mock_agent_data():
    """Create mock agent registry data."""
    return {
        "id": "test_agent_123",
        "tmux_session": "agent_test_agent_123",
        "status": "running",
        "tracked_files": {
            "prompt_file": "/workspace/agent_prompt_test_agent_123.txt",
            "log_file": "/workspace/logs/test_agent_123_stream.jsonl",
            "progress_file": "/workspace/progress/test_agent_123_progress.jsonl",
            "findings_file": "/workspace/findings/test_agent_123_findings.jsonl",
            "deploy_log": "/workspace/logs/deploy_test_agent_123.json"
        }
    }

@pytest.fixture
def mock_tmux_session(monkeypatch):
    """Mock tmux session operations."""
    def mock_check_exists(session_name):
        return True

    def mock_kill_session(session_name):
        return True

    monkeypatch.setattr("real_mcp_server.check_tmux_session_exists", mock_check_exists)
    monkeypatch.setattr("real_mcp_server.kill_tmux_session", mock_kill_session)
```

### Test Data Helpers

```python
def create_test_agent_files(workspace, agent_id):
    """Create all files an agent would have."""
    files = {
        "prompt": f"{workspace}/agent_prompt_{agent_id}.txt",
        "stream": f"{workspace}/logs/{agent_id}_stream.jsonl",
        "progress": f"{workspace}/progress/{agent_id}_progress.jsonl",
        "findings": f"{workspace}/findings/{agent_id}_findings.jsonl",
        "deploy": f"{workspace}/logs/deploy_{agent_id}.json"
    }

    for file_path in files.values():
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w') as f:
            f.write('{"test": "data"}')

    return files

def verify_files_archived(workspace, agent_id):
    """Verify all files moved to archive."""
    archive_dir = f"{workspace}/archive"
    assert os.path.exists(archive_dir)
    assert os.path.exists(f"{archive_dir}/{agent_id}_stream.jsonl")
    assert os.path.exists(f"{archive_dir}/{agent_id}_progress.jsonl")
    assert os.path.exists(f"{archive_dir}/{agent_id}_findings.jsonl")

    # Verify originals deleted
    assert not os.path.exists(f"{workspace}/logs/{agent_id}_stream.jsonl")
    assert not os.path.exists(f"{workspace}/agent_prompt_{agent_id}.txt")
```

---

## Critical Issues Found During Review

### Issue 1: File Handle Leak in cleanup_agent_resources()
**Reported by:** code_quality_reviewer-233824-475513
**Location:** `real_mcp_server.py:4042-4055`
**Severity:** CRITICAL

**Problem:**
```python
# Lines 4042-4055
for src_path, file_type in files_to_process:
    if os.path.exists(src_path):
        dst_path = f"{archive_dir}/{os.path.basename(src_path)}"
        try:
            # Comment says "Ensure file is flushed and closed" but doesn't actually do it
            import shutil
            shutil.move(src_path, dst_path)  # File handles may still be open!
```

**Impact:** If Python's GC hasn't closed file handles (e.g., write operations in progress), `shutil.move` can fail or move incomplete data.

**Test Case Required:**
```python
def test_cleanup_with_open_file_handles():
    """
    Verify cleanup handles open file handles correctly.

    Given: Agent with JSONL file handles still open (write in progress)
    When: cleanup_agent_resources() called
    Then:
      - Files flushed before move
      - No incomplete data archiving
      - No OS-level file handle leaks
    """
```

### Issue 2: Daemon Zombie Detection Bug
**Reported by:** daemon_script_reviewer-233829-6c2867
**Location:** `resource_cleanup_daemon.sh:128`
**Severity:** CRITICAL

**Problem:**
```bash
# Line 128 - BUGGY
zombie_count=$(ps aux | grep -c "$agent_id" | grep -v grep || echo 0)
# grep -c counts lines BEFORE grep -v grep can filter
# This ALWAYS counts grep itself, showing false positive
```

**Correct Fix:**
```bash
zombie_count=$(ps aux | grep "$agent_id" | grep -v grep | wc -l)
```

**Test Case:** See TC4.4 above

---

## Test Execution Strategy

### Phase 1: Unit Tests (Priority: CRITICAL)
1. Run all cleanup_agent_resources() unit tests (TC1.1-TC1.8)
2. Verify 100% code coverage of function
3. Test all error paths and edge cases

**Timeline:** Implement immediately

### Phase 2: Integration Tests (Priority: CRITICAL)
1. Run kill_real_agent integration tests (TC2.1-TC2.2)
2. Run file tracking tests (TC3.1-TC3.2)
3. Run 4 scenario tests from analysis

**Timeline:** Implement within 24h

### Phase 3: Daemon Tests (Priority: HIGH)
1. Run daemon script tests (TC4.1-TC4.4)
2. Fix identified bugs
3. Verify daemon behavior over time

**Timeline:** Implement within 48h

### Phase 4: Performance & Stress Tests (Priority: MEDIUM)
1. Test with 100+ agents
2. Verify no resource accumulation
3. Measure cleanup timing
4. Monitor disk space over time

**Timeline:** Implement within 1 week

---

## Test Coverage Metrics

### Target Coverage Goals

| Component | Target Coverage | Current Coverage |
|-----------|----------------|------------------|
| cleanup_agent_resources() | 100% | 0% |
| kill_real_agent cleanup integration | 100% | 0% |
| File tracking system | 100% | 0% |
| Daemon script functions | 90% | 0% |
| Error handling paths | 100% | 0% |
| Edge cases | 100% | 0% |

### Acceptance Criteria

Before production deployment:
- ✅ All unit tests passing (TC1.1-TC1.8)
- ✅ All integration tests passing (TC2.1-TC3.2)
- ✅ All scenario tests passing (Scenarios 1-4)
- ✅ Critical bugs fixed (file handle leak, zombie detection)
- ✅ Code coverage ≥ 95% for cleanup functions
- ✅ Documentation updated with test results

---

## Recommendations

### Immediate Actions (P0)

1. **Create test_resource_cleanup.py** with all unit tests
2. **Fix critical bugs** identified by reviewers:
   - File handle leak in cleanup_agent_resources
   - Zombie detection bug in daemon script
3. **Run manual test cycle** for 4 scenarios
4. **Add pytest to requirements.txt** if not present

### Short-term Actions (P1)

1. **Add CI/CD integration** to run tests on every commit
2. **Create test fixtures** for common scenarios
3. **Document test execution** in README
4. **Set up test coverage reporting** (pytest-cov)

### Long-term Actions (P2)

1. **Add property-based testing** (hypothesis library)
2. **Create load tests** for daemon over extended time
3. **Add mutation testing** to verify test quality
4. **Implement integration with real tmux** (not just mocks)

---

## Conclusion

The resource cleanup implementation is architecturally sound and well-documented, but **lacks any automated test coverage**. This creates significant risk for production deployment:

1. **No verification** that cleanup actually works
2. **No regression protection** for future changes
3. **Critical bugs undetected** (file handles, zombie detection)
4. **No confidence** in edge case handling

**Status:** ❌ NOT PRODUCTION READY
**Blocker:** Zero test coverage
**Timeline:** Implement comprehensive test suite IMMEDIATELY before deployment

**Next Steps:**
1. Create test_resource_cleanup.py (this document provides full specification)
2. Fix identified critical bugs
3. Run all tests and achieve ≥95% coverage
4. Document test results and mark as production ready

---

**Review Complete:** 2025-10-29T23:39:30
**Test Suite Specification:** Ready for implementation
**Status:** COMPREHENSIVE TEST PLAN CREATED
