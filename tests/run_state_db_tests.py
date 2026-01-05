#!/usr/bin/env python3
"""
Simple test runner for state_db tests.
Can be run directly without needing pytest installed globally.
"""

import sys
import os
import subprocess

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_tests():
    """Run the state_db tests."""
    test_file = os.path.join(os.path.dirname(__file__), "test_state_db.py")

    # Try running with pytest
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file, "-v", "--tb=short"],
            capture_output=True,
            text=True
        )

        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        return result.returncode

    except Exception as e:
        print(f"Could not run pytest: {e}")
        print("\nFalling back to direct test execution...")

        # Fall back to direct execution
        try:
            from test_state_db import TestStateDB
            import tempfile

            test_suite = TestStateDB()
            test_methods = [m for m in dir(test_suite) if m.startswith("test_")]

            passed = 0
            failed = 0

            print(f"\nRunning {len(test_methods)} tests...")
            print("=" * 60)

            for method_name in test_methods:
                try:
                    # Create temp workspace for each test
                    with tempfile.TemporaryDirectory() as temp_dir:
                        method = getattr(test_suite, method_name)

                        # Handle methods that need fixtures
                        if "temp_workspace" in method.__code__.co_varnames:
                            method(temp_dir)
                        elif "sample_task_data" in method.__code__.co_varnames:
                            sample_data = test_suite.sample_task_data()
                            method(temp_dir, sample_data)
                        else:
                            method()

                        print(f"✓ {method_name}")
                        passed += 1

                except Exception as e:
                    print(f"✗ {method_name}: {str(e)}")
                    failed += 1

            print("=" * 60)
            print(f"\nResults: {passed} passed, {failed} failed")

            return 1 if failed > 0 else 0

        except ImportError as e:
            print(f"Could not import test module: {e}")
            return 1


if __name__ == "__main__":
    exit_code = run_tests()
    sys.exit(exit_code)