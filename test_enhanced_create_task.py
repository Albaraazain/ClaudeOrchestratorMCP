#!/usr/bin/env python3
"""
Test enhanced create_real_task() function with new optional parameters
"""
import json
import os
import sys
import shutil
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from real_mcp_server import create_real_task

def cleanup_test_workspace(workspace_base):
    """Clean up test workspace"""
    if os.path.exists(workspace_base):
        shutil.rmtree(workspace_base)

def test_minimal_call():
    """Test backward compatibility: minimal call with only description"""
    print("\n=== TEST 1: Minimal Call (Backward Compatibility) ===")

    workspace_base = "/tmp/test-orchestrator-minimal"
    cleanup_test_workspace(workspace_base)

    result = create_real_task.fn(
        description="Test minimal task",
        client_cwd="/tmp"
    )

    print(f"✓ Result: {json.dumps(result, indent=2)}")

    assert result['success'] == True
    assert result['task_id'].startswith('TASK-')
    assert result['description'] == "Test minimal task"
    assert result['has_enhanced_context'] == False
    assert 'validation_warnings' not in result

    # Verify registry doesn't have task_context
    task_id = result['task_id']
    workspace = result['workspace']
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    with open(registry_path, 'r') as f:
        registry = json.load(f)

    assert 'task_context' not in registry
    print("✓ Registry has NO task_context (expected for minimal call)")

    cleanup_test_workspace(workspace_base)
    print("✓ Test 1 PASSED: Backward compatibility maintained\n")

def test_enhanced_call():
    """Test enhanced call with all 5 new parameters"""
    print("\n=== TEST 2: Enhanced Call (All New Parameters) ===")

    workspace_base = "/tmp/test-orchestrator-enhanced"
    cleanup_test_workspace(workspace_base)

    result = create_real_task.fn(
        description="Test enhanced task",
        priority="P1",
        client_cwd="/tmp",
        background_context="This is important context about the task",
        expected_deliverables=[
            "Implement feature X",
            "Write tests for feature X",
            "Update documentation"
        ],
        success_criteria=[
            "All tests pass",
            "Code coverage > 80%",
            "Documentation is clear"
        ],
        constraints=[
            "Must use Python 3.9+",
            "Follow PEP 8 style guide"
        ],
        relevant_files=[
            "/path/to/file1.py",
            "/path/to/file2.py"
        ]
    )

    print(f"✓ Result: {json.dumps(result, indent=2)}")

    assert result['success'] == True
    assert result['has_enhanced_context'] == True
    assert 'background_context' in result
    assert 'expected_deliverables' in result
    assert 'success_criteria' in result
    assert 'constraints' in result
    assert 'relevant_files' in result

    # Verify registry has task_context
    task_id = result['task_id']
    workspace = result['workspace']
    workspace_base_used = os.path.dirname(workspace)
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    with open(registry_path, 'r') as f:
        registry = json.load(f)

    assert 'task_context' in registry
    task_context = registry['task_context']
    assert task_context['background_context'] == "This is important context about the task"
    assert len(task_context['expected_deliverables']) == 3
    assert len(task_context['success_criteria']) == 3
    assert len(task_context['constraints']) == 2
    assert len(task_context['relevant_files']) == 2
    print("✓ Registry has task_context with all fields")

    # Verify global registry has enhancement flags
    global_reg_path = f"{workspace_base_used}/registry/GLOBAL_REGISTRY.json"
    with open(global_reg_path, 'r') as f:
        global_reg = json.load(f)

    assert global_reg['tasks'][task_id]['has_enhanced_context'] == True
    assert global_reg['tasks'][task_id]['deliverables_count'] == 3
    assert global_reg['tasks'][task_id]['success_criteria_count'] == 3
    print("✓ Global registry has enhancement flags and counts")

    cleanup_test_workspace(workspace_base)
    print("✓ Test 2 PASSED: Enhanced context stored correctly\n")

def test_partial_enhancement():
    """Test partial enhancement with only some parameters"""
    print("\n=== TEST 3: Partial Enhancement ===")

    workspace_base = "/tmp/test-orchestrator-partial"
    cleanup_test_workspace(workspace_base)

    result = create_real_task.fn(
        description="Test partial enhancement",
        client_cwd="/tmp",
        background_context="Just background, no deliverables",
        success_criteria=["One criterion"]
    )

    print(f"✓ Result: {json.dumps(result, indent=2)}")

    assert result['success'] == True
    assert result['has_enhanced_context'] == True
    assert 'background_context' in result
    assert 'success_criteria' in result
    assert 'expected_deliverables' not in result  # Not provided
    assert 'constraints' not in result  # Not provided

    # Verify registry
    task_id = result['task_id']
    workspace = result['workspace']
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    with open(registry_path, 'r') as f:
        registry = json.load(f)

    task_context = registry['task_context']
    assert 'background_context' in task_context
    assert 'success_criteria' in task_context
    assert 'expected_deliverables' not in task_context
    assert 'constraints' not in task_context
    print("✓ Registry has only provided fields")

    cleanup_test_workspace(workspace_base)
    print("✓ Test 3 PASSED: Partial enhancement works correctly\n")

def test_validation_warnings():
    """Test validation warnings for invalid inputs"""
    print("\n=== TEST 4: Validation Warnings ===")

    workspace_base = "/tmp/test-orchestrator-validation"
    cleanup_test_workspace(workspace_base)

    result = create_real_task.fn(
        description="Test validation",
        client_cwd="/tmp",
        background_context="  ",  # Empty after strip
        expected_deliverables=["Valid", "", "  "],  # Some invalid
        success_criteria=[],  # Empty list
    )

    print(f"✓ Result: {json.dumps(result, indent=2)}")

    assert result['success'] == True
    assert 'validation_warnings' in result
    assert len(result['validation_warnings']) >= 2  # At least background and success_criteria
    print(f"✓ Validation warnings: {result['validation_warnings']}")

    # Should have filtered deliverables
    if 'expected_deliverables' in result:
        assert len(result['expected_deliverables']) == 1  # Only "Valid"
        print("✓ Invalid deliverables filtered correctly")

    cleanup_test_workspace(workspace_base)
    print("✓ Test 4 PASSED: Validation warnings work correctly\n")

def test_type_validation():
    """Test type validation for parameters"""
    print("\n=== TEST 5: Type Validation ===")

    workspace_base = "/tmp/test-orchestrator-types"
    cleanup_test_workspace(workspace_base)

    result = create_real_task.fn(
        description="Test type validation",
        client_cwd="/tmp",
        background_context=123,  # Wrong type (should be string)
        expected_deliverables="not a list",  # Wrong type
        success_criteria=["Valid criterion"]  # Correct
    )

    print(f"✓ Result: {json.dumps(result, indent=2)}")

    assert result['success'] == True
    assert 'validation_warnings' in result

    # Invalid types should be ignored
    assert 'background_context' not in result
    assert 'expected_deliverables' not in result

    # Valid field should be present
    assert 'success_criteria' in result
    print(f"✓ Type validation warnings: {result['validation_warnings']}")

    cleanup_test_workspace(workspace_base)
    print("✓ Test 5 PASSED: Type validation works correctly\n")

if __name__ == "__main__":
    print("=" * 60)
    print("Testing Enhanced create_real_task() Implementation")
    print("=" * 60)

    try:
        test_minimal_call()
        test_enhanced_call()
        test_partial_enhancement()
        test_validation_warnings()
        test_type_validation()

        print("=" * 60)
        print("✓✓✓ ALL TESTS PASSED ✓✓✓")
        print("=" * 60)
        print("\nSUMMARY:")
        print("- Backward compatibility: ✓ (minimal calls work unchanged)")
        print("- Enhanced context: ✓ (all 5 parameters stored correctly)")
        print("- Partial enhancement: ✓ (only provided fields stored)")
        print("- Validation warnings: ✓ (invalid inputs handled gracefully)")
        print("- Type validation: ✓ (wrong types rejected with warnings)")
        print("- Registry storage: ✓ (task_context only when enhanced)")
        print("- Global registry flags: ✓ (has_enhanced_context + counts)")
        print("- Return value: ✓ (includes all enhancement fields)")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
