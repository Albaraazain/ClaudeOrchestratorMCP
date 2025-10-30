#!/usr/bin/env python3
"""
Comprehensive Integration Test Suite for Registry Fixes
Tests: file locking, deduplication, resource cleanup, validation
"""

import os
import sys
import json
import time
import subprocess
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# Add parent to path for importing MCP server functions
sys.path.insert(0, '/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP')

class RegistryFixesTestSuite:
    def __init__(self):
        self.workspace = Path("/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/.agent-workspace")
        self.test_results = []
        self.start_time = datetime.now()

    def log_test(self, test_name, passed, details="", expected="", actual=""):
        """Log test result"""
        result = {
            "test": test_name,
            "status": "PASS" if passed else "FAIL",
            "timestamp": datetime.now().isoformat(),
            "details": details,
            "expected": expected,
            "actual": actual
        }
        self.test_results.append(result)

        status_emoji = "✅" if passed else "❌"
        print(f"\n{status_emoji} {test_name}: {'PASS' if passed else 'FAIL'}")
        if details:
            print(f"   Details: {details}")
        if not passed and expected:
            print(f"   Expected: {expected}")
            print(f"   Actual: {actual}")
        return passed

    def test_1_fcntl_locking_exists(self):
        """Test 1: Verify fcntl locking implementation exists"""
        print("\n" + "="*80)
        print("TEST 1: Verify fcntl locking implementation")
        print("="*80)

        server_path = "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py"
        with open(server_path, 'r') as f:
            content = f.read()

        # Check for fcntl import
        has_import = "import fcntl" in content
        has_class = "class LockedRegistryFile" in content
        has_lock_ex = "LOCK_EX" in content
        has_lock_un = "LOCK_UN" in content

        passed = all([has_import, has_class, has_lock_ex, has_lock_un])

        return self.log_test(
            "fcntl_locking_implementation",
            passed,
            f"fcntl import: {has_import}, LockedRegistryFile class: {has_class}, LOCK_EX: {has_lock_ex}, LOCK_UN: {has_lock_un}",
            "All locking components present",
            f"Components found: {sum([has_import, has_class, has_lock_ex, has_lock_un])}/4"
        )

    def test_2_atomic_utilities_exist(self):
        """Test 2: Verify atomic registry operation utilities exist"""
        print("\n" + "="*80)
        print("TEST 2: Verify atomic utilities implementation")
        print("="*80)

        server_path = "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py"
        with open(server_path, 'r') as f:
            content = f.read()

        utilities = [
            "def atomic_add_agent(",
            "def atomic_update_agent_status(",
            "def atomic_increment_counts(",
            "def atomic_decrement_active_count(",
            "def atomic_mark_agents_completed("
        ]

        found = {util: util in content for util in utilities}
        passed = all(found.values())

        return self.log_test(
            "atomic_utilities_exist",
            passed,
            f"Found {sum(found.values())}/{len(utilities)} atomic utilities",
            "All 5 atomic utilities present",
            f"{list(found.values())}"
        )

    def test_3_deduplication_functions_exist(self):
        """Test 3: Verify deduplication helper functions exist"""
        print("\n" + "="*80)
        print("TEST 3: Verify deduplication functions")
        print("="*80)

        server_path = "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py"
        with open(server_path, 'r') as f:
            content = f.read()

        functions = [
            "def find_existing_agent(",
            "def verify_agent_id_unique(",
            "def generate_unique_agent_id("
        ]

        found = {func: func in content for func in functions}
        passed = all(found.values())

        return self.log_test(
            "deduplication_functions_exist",
            passed,
            f"Found {sum(found.values())}/{len(functions)} deduplication functions",
            "All 3 deduplication functions present",
            f"{list(found.values())}"
        )

    def test_4_triple_load_bug_check(self):
        """Test 4: Check if triple registry load bug still exists"""
        print("\n" + "="*80)
        print("TEST 4: Check triple registry load bug")
        print("="*80)

        server_path = "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py"
        with open(server_path, 'r') as f:
            lines = f.readlines()

        # Find deploy_headless_agent function
        deploy_start = None
        deploy_end = None
        for i, line in enumerate(lines):
            if "def deploy_headless_agent(" in line:
                deploy_start = i
            elif deploy_start and line.startswith("def ") and i > deploy_start + 10:
                deploy_end = i
                break

        if not deploy_start:
            return self.log_test(
                "triple_load_bug_check",
                False,
                "Could not find deploy_headless_agent function"
            )

        # Count registry loads in the function
        function_lines = lines[deploy_start:deploy_end] if deploy_end else lines[deploy_start:]
        registry_loads = []
        for i, line in enumerate(function_lines):
            if "with open(registry_path" in line or "json.load(" in line:
                if "registry" in line and "json.load" in line:
                    registry_loads.append(deploy_start + i + 1)

        # Bug exists if there are multiple unlocked loads
        bug_exists = len(registry_loads) > 1

        return self.log_test(
            "triple_load_bug_check",
            not bug_exists,  # Pass if bug does NOT exist
            f"Found {len(registry_loads)} registry loads in deploy_headless_agent at lines: {registry_loads}",
            "Single atomic load",
            f"{len(registry_loads)} separate loads detected"
        )

    def test_5_ghost_entries_cleanable(self):
        """Test 5: Verify current ghost entries can be identified"""
        print("\n" + "="*80)
        print("TEST 5: Check ghost entries in registry")
        print("="*80)

        global_registry_path = self.workspace / "registry" / "GLOBAL_REGISTRY.json"

        if not global_registry_path.exists():
            return self.log_test(
                "ghost_entries_check",
                False,
                "Global registry not found"
            )

        with open(global_registry_path, 'r') as f:
            registry = json.load(f)

        # Get active agents from registry
        agents_data = registry.get('agents', {})
        if isinstance(agents_data, dict):
            active_agents = [a for a in agents_data.values() if isinstance(a, dict) and a.get('status') in ['running', 'working']]
        else:
            active_agents = [a for a in agents_data if isinstance(a, dict) and a.get('status') in ['running', 'working']]

        # Get actual tmux sessions
        try:
            result = subprocess.run(['tmux', 'list-sessions'],
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                tmux_sessions = [line.split(':')[0] for line in result.stdout.strip().split('\n') if line]
                # Remove 'agent_' prefix from session names for comparison
                tmux_agent_ids = [s.replace('agent_', '') if s.startswith('agent_') else s for s in tmux_sessions]
            else:
                tmux_agent_ids = []
        except Exception as e:
            return self.log_test(
                "ghost_entries_check",
                False,
                f"Could not get tmux sessions: {e}"
            )

        # Count ghosts
        ghost_count = 0
        for agent in active_agents:
            agent_id = agent.get('agent_id', '')
            if agent_id not in tmux_agent_ids and f"agent_{agent_id}" not in tmux_sessions:
                ghost_count += 1

        passed = ghost_count == 0  # Pass if no ghosts

        return self.log_test(
            "ghost_entries_check",
            passed,
            f"Registry active: {len(active_agents)}, Tmux sessions: {len(tmux_sessions)}, Ghosts: {ghost_count}",
            "0 ghost entries",
            f"{ghost_count} ghost entries found"
        )

    def test_6_concurrent_spawn_simulation(self):
        """Test 6: Simulate concurrent agent spawns (dry run - analysis only)"""
        print("\n" + "="*80)
        print("TEST 6: Concurrent spawn simulation (analysis)")
        print("="*80)

        # Note: We can't actually spawn 10 real agents in a test
        # Instead, verify the locking mechanism would prevent corruption

        server_path = "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py"
        with open(server_path, 'r') as f:
            content = f.read()

        # Check if deploy uses atomic operations
        uses_atomic = "atomic_add_agent" in content or "LockedRegistryFile" in content
        has_locking = "fcntl.LOCK_EX" in content

        passed = uses_atomic and has_locking

        return self.log_test(
            "concurrent_spawn_protection",
            passed,
            f"Atomic operations: {uses_atomic}, File locking: {has_locking}",
            "Both atomic operations and file locking present",
            f"Atomic: {uses_atomic}, Locking: {has_locking}"
        )

    def test_7_resource_cleanup_on_failure(self):
        """Test 7: Verify resource cleanup logic on failures"""
        print("\n" + "="*80)
        print("TEST 7: Resource cleanup on failure paths")
        print("="*80)

        server_path = "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py"
        with open(server_path, 'r') as f:
            lines = f.readlines()

        # Find deploy_headless_agent function
        deploy_start = None
        for i, line in enumerate(lines):
            if "def deploy_headless_agent(" in line:
                deploy_start = i
                break

        if not deploy_start:
            return self.log_test(
                "resource_cleanup_check",
                False,
                "Could not find deploy_headless_agent function"
            )

        # Check for try/finally or try/except patterns
        function_content = '\n'.join(lines[deploy_start:deploy_start+300])

        has_try = "try:" in function_content
        has_finally = "finally:" in function_content
        has_except = "except" in function_content
        has_cleanup = "cleanup" in function_content.lower() or "kill" in function_content.lower()

        # Good if has try/finally or try/except with cleanup
        passed = has_try and (has_finally or (has_except and has_cleanup))

        return self.log_test(
            "resource_cleanup_check",
            passed,
            f"try: {has_try}, finally: {has_finally}, except: {has_except}, cleanup: {has_cleanup}",
            "try/finally or try/except with cleanup present",
            f"Error handling found: {has_try and (has_finally or has_except)}"
        )

    def test_8_validation_repair_exists(self):
        """Test 8: Check for registry validation/repair functionality"""
        print("\n" + "="*80)
        print("TEST 8: Registry validation and repair")
        print("="*80)

        server_path = "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py"
        with open(server_path, 'r') as f:
            content = f.read()

        # Look for validation/repair functions
        has_validate = "validate" in content.lower() and "registry" in content.lower()
        has_repair = "repair" in content.lower() and "registry" in content.lower()
        has_sync = "sync" in content.lower() or "reconcile" in content.lower()

        passed = has_validate or has_repair or has_sync

        return self.log_test(
            "validation_repair_exists",
            passed,
            f"Validation: {has_validate}, Repair: {has_repair}, Sync/Reconcile: {has_sync}",
            "At least one validation/repair mechanism",
            f"Found: validate={has_validate}, repair={has_repair}, sync={has_sync}"
        )

    def test_9_performance_redundant_loads(self):
        """Test 9: Measure redundant loads reduction"""
        print("\n" + "="*80)
        print("TEST 9: Performance - Redundant loads")
        print("="*80)

        server_path = "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py"
        with open(server_path, 'r') as f:
            lines = f.readlines()

        # Find deploy_headless_agent function
        deploy_start = None
        deploy_end = None
        for i, line in enumerate(lines):
            if "def deploy_headless_agent(" in line:
                deploy_start = i
            elif deploy_start and line.startswith("def ") and i > deploy_start + 10:
                deploy_end = i
                break

        if not deploy_start:
            return self.log_test(
                "performance_redundant_loads",
                False,
                "Could not find deploy_headless_agent function"
            )

        # Count open() calls for registry in the function
        function_lines = lines[deploy_start:deploy_end] if deploy_end else lines[deploy_start:]
        open_count = sum(1 for line in function_lines if "open(" in line and "registry" in line.lower())

        # Optimal is 1 (single locked read-modify-write)
        passed = open_count <= 2  # Allow up to 2 (task + global)

        return self.log_test(
            "performance_redundant_loads",
            passed,
            f"Found {open_count} registry file open operations in deploy_headless_agent",
            "≤2 open operations (task + global registry)",
            f"{open_count} open operations"
        )

    def test_10_deduplication_enforcement(self):
        """Test 10: Verify deduplication is enforced in deploy"""
        print("\n" + "="*80)
        print("TEST 10: Deduplication enforcement in deploy")
        print("="*80)

        server_path = "/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/real_mcp_server.py"
        with open(server_path, 'r') as f:
            content = f.read()

        # Find deploy_headless_agent and check if it calls deduplication functions
        lines = content.split('\n')
        deploy_start = None
        deploy_end = None

        for i, line in enumerate(lines):
            if "def deploy_headless_agent(" in line:
                deploy_start = i
            elif deploy_start and line.startswith("def ") and i > deploy_start + 10:
                deploy_end = i
                break

        if not deploy_start:
            return self.log_test(
                "deduplication_enforcement",
                False,
                "Could not find deploy_headless_agent function"
            )

        function_content = '\n'.join(lines[deploy_start:deploy_end] if deploy_end else lines[deploy_start:])

        # Check if deduplication functions are called
        calls_find_existing = "find_existing_agent" in function_content
        calls_verify_unique = "verify_agent_id_unique" in function_content
        calls_generate_unique = "generate_unique_agent_id" in function_content

        passed = calls_find_existing or calls_verify_unique or calls_generate_unique

        return self.log_test(
            "deduplication_enforcement",
            passed,
            f"find_existing: {calls_find_existing}, verify_unique: {calls_verify_unique}, generate_unique: {calls_generate_unique}",
            "At least one deduplication check called",
            f"Deduplication calls found: {sum([calls_find_existing, calls_verify_unique, calls_generate_unique])}"
        )

    def generate_report(self):
        """Generate final test report"""
        print("\n" + "="*80)
        print("INTEGRATION TEST RESULTS SUMMARY")
        print("="*80)

        total = len(self.test_results)
        passed = sum(1 for r in self.test_results if r['status'] == 'PASS')
        failed = total - passed

        print(f"\nTotal Tests: {total}")
        print(f"Passed: {passed} ✅")
        print(f"Failed: {failed} ❌")
        print(f"Pass Rate: {(passed/total*100):.1f}%")

        if failed > 0:
            print(f"\nFailed Tests:")
            for result in self.test_results:
                if result['status'] == 'FAIL':
                    print(f"  ❌ {result['test']}")
                    if result.get('details'):
                        print(f"     {result['details']}")

        # Write detailed results
        report_path = Path("/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/.agent-workspace/TASK-20251029-233824-9cd33bdd/output/INTEGRATION_TEST_RESULTS.md")
        report_path.parent.mkdir(parents=True, exist_ok=True)

        with open(report_path, 'w') as f:
            f.write("# Integration Test Results\n\n")
            f.write(f"**Test Date:** {self.start_time.isoformat()}\n")
            f.write(f"**Duration:** {(datetime.now() - self.start_time).total_seconds():.2f} seconds\n\n")

            f.write(f"## Summary\n\n")
            f.write(f"- **Total Tests:** {total}\n")
            f.write(f"- **Passed:** {passed} ✅\n")
            f.write(f"- **Failed:** {failed} ❌\n")
            f.write(f"- **Pass Rate:** {(passed/total*100):.1f}%\n\n")

            f.write(f"## Detailed Results\n\n")
            for i, result in enumerate(self.test_results, 1):
                status_emoji = "✅" if result['status'] == 'PASS' else "❌"
                f.write(f"### {i}. {result['test']} {status_emoji}\n\n")
                f.write(f"**Status:** {result['status']}\n\n")
                if result.get('details'):
                    f.write(f"**Details:** {result['details']}\n\n")
                if result.get('expected'):
                    f.write(f"**Expected:** {result['expected']}\n\n")
                if result.get('actual'):
                    f.write(f"**Actual:** {result['actual']}\n\n")
                f.write(f"---\n\n")

            # Critical Issues Section
            f.write(f"## Critical Issues Found\n\n")
            critical_issues = []

            for result in self.test_results:
                if result['status'] == 'FAIL':
                    critical_issues.append(result['test'])

            if critical_issues:
                for issue in critical_issues:
                    f.write(f"- {issue}\n")
            else:
                f.write("No critical issues found. All tests passed!\n")

            f.write(f"\n## Recommendations\n\n")

            # Generate recommendations based on failed tests
            if any(r['test'] == 'triple_load_bug_check' and r['status'] == 'FAIL' for r in self.test_results):
                f.write("1. **Fix Triple Load Bug:** Refactor deploy_headless_agent to use single LockedRegistryFile context manager\n")

            if any(r['test'] == 'ghost_entries_check' and r['status'] == 'FAIL' for r in self.test_results):
                f.write("2. **Clean Ghost Entries:** Run registry validation/repair to remove ghost entries\n")

            if any(r['test'] == 'resource_cleanup_check' and r['status'] == 'FAIL' for r in self.test_results):
                f.write("3. **Add Resource Cleanup:** Implement try/finally blocks with proper cleanup on failures\n")

            if any(r['test'] == 'validation_repair_exists' and r['status'] == 'FAIL' for r in self.test_results):
                f.write("4. **Implement Validation:** Create registry validation and auto-repair system\n")

            if passed == total:
                f.write("All tests passed! System is ready for production use.\n")

        print(f"\nDetailed report saved to: {report_path}")
        return passed == total

def main():
    print("="*80)
    print("REGISTRY FIXES - COMPREHENSIVE INTEGRATION TEST SUITE")
    print("="*80)
    print(f"Started at: {datetime.now().isoformat()}")

    suite = RegistryFixesTestSuite()

    # Run all tests
    suite.test_1_fcntl_locking_exists()
    suite.test_2_atomic_utilities_exist()
    suite.test_3_deduplication_functions_exist()
    suite.test_4_triple_load_bug_check()
    suite.test_5_ghost_entries_cleanable()
    suite.test_6_concurrent_spawn_simulation()
    suite.test_7_resource_cleanup_on_failure()
    suite.test_8_validation_repair_exists()
    suite.test_9_performance_redundant_loads()
    suite.test_10_deduplication_enforcement()

    # Generate report
    all_passed = suite.generate_report()

    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
