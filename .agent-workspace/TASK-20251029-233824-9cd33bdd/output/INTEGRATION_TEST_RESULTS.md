# Integration Test Results

**Test Date:** 2025-10-29T23:52:29.022859
**Duration:** 0.10 seconds

## Summary

- **Total Tests:** 10
- **Passed:** 7 ✅
- **Failed:** 3 ❌
- **Pass Rate:** 70.0%

## Detailed Results

### 1. fcntl_locking_implementation ✅

**Status:** PASS

**Details:** fcntl import: True, LockedRegistryFile class: True, LOCK_EX: True, LOCK_UN: True

**Expected:** All locking components present

**Actual:** Components found: 4/4

---

### 2. atomic_utilities_exist ✅

**Status:** PASS

**Details:** Found 5/5 atomic utilities

**Expected:** All 5 atomic utilities present

**Actual:** [True, True, True, True, True]

---

### 3. deduplication_functions_exist ✅

**Status:** PASS

**Details:** Found 3/3 deduplication functions

**Expected:** All 3 deduplication functions present

**Actual:** [True, True, True]

---

### 4. triple_load_bug_check ❌

**Status:** FAIL

**Details:** Found 4 registry loads in deploy_headless_agent at lines: [2882, 2913, 2932, 2940]

**Expected:** Single atomic load

**Actual:** 4 separate loads detected

---

### 5. ghost_entries_check ❌

**Status:** FAIL

**Details:** Registry active: 18, Tmux sessions: 17, Ghosts: 18

**Expected:** 0 ghost entries

**Actual:** 18 ghost entries found

---

### 6. concurrent_spawn_protection ✅

**Status:** PASS

**Details:** Atomic operations: True, File locking: True

**Expected:** Both atomic operations and file locking present

**Actual:** Atomic: True, Locking: True

---

### 7. resource_cleanup_check ✅

**Status:** PASS

**Details:** try: True, finally: False, except: True, cleanup: True

**Expected:** try/finally or try/except with cleanup present

**Actual:** Error handling found: True

---

### 8. validation_repair_exists ✅

**Status:** PASS

**Details:** Validation: True, Repair: True, Sync/Reconcile: True

**Expected:** At least one validation/repair mechanism

**Actual:** Found: validate=True, repair=True, sync=True

---

### 9. performance_redundant_loads ❌

**Status:** FAIL

**Details:** Found 4 registry file open operations in deploy_headless_agent

**Expected:** ≤2 open operations (task + global registry)

**Actual:** 4 open operations

---

### 10. deduplication_enforcement ✅

**Status:** PASS

**Details:** find_existing: True, verify_unique: False, generate_unique: True

**Expected:** At least one deduplication check called

**Actual:** Deduplication calls found: 2

---

## Critical Issues Found

- triple_load_bug_check
- ghost_entries_check
- performance_redundant_loads

## Recommendations

1. **Fix Triple Load Bug:** Refactor deploy_headless_agent to use single LockedRegistryFile context manager
2. **Clean Ghost Entries:** Run registry validation/repair to remove ghost entries
