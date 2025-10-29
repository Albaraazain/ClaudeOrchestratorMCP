#!/usr/bin/env python3
"""
Test to verify VALIDATION CHECKPOINT was added to fixer protocol.

This test verifies:
1. get_fixer_requirements() returns a string with validation checkpoint
2. The checkpoint contains 8 checkbox questions
3. Integration with get_type_specific_requirements() works correctly
"""

import sys
sys.path.insert(0, '/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP')

from real_mcp_server import get_fixer_requirements, get_type_specific_requirements


def test_fixer_requirements_has_validation_checkpoint():
    """Test that fixer protocol includes VALIDATION CHECKPOINT section."""
    protocol = get_fixer_requirements()

    # Verify it's a string and not empty
    assert isinstance(protocol, str), "Protocol should be a string"
    assert len(protocol) > 0, "Protocol should not be empty"

    # Verify VALIDATION CHECKPOINT section exists
    assert "🔍 VALIDATION CHECKPOINT" in protocol, \
        "Protocol should contain VALIDATION CHECKPOINT section"

    # Verify the checkpoint instruction text
    assert "Run this self-check" in protocol, \
        "Should have self-check instruction"
    assert "If you answer 'NO' to ANY question, you are NOT done" in protocol, \
        "Should have explicit NOT done warning"

    # Verify all 8 checkbox questions are present
    checkpoint_questions = [
        "□ Can I reproduce the bug?",
        "□ What is the root cause?",
        "□ Does my fix address root cause or just symptoms?",
        "□ Did I verify the bug no longer occurs?",
        "□ What regression tests did I add?",
        "□ Did I check for similar bugs?",
        "□ Could my fix break anything else?",
        "□ Did I update documentation if assumptions were wrong?"
    ]

    for question in checkpoint_questions:
        assert question in protocol, \
            f"Missing checkbox question: {question}"

    # Verify completion warning
    assert "If ANY checkbox is unchecked, CONTINUE fixing before reporting completed" in protocol, \
        "Should have explicit completion warning"

    print("✅ PASS: get_fixer_requirements() has VALIDATION CHECKPOINT with 8 questions")
    return True


def test_type_specific_requirements_integration():
    """Test that get_type_specific_requirements('fixer') returns enhanced protocol."""
    protocol = get_type_specific_requirements('fixer')

    # Verify it returns enhanced fixer protocol
    assert isinstance(protocol, str), "Should return string"
    assert len(protocol) > 0, "Should not be empty"

    # Verify VALIDATION CHECKPOINT is included
    assert "🔍 VALIDATION CHECKPOINT" in protocol, \
        "Should include VALIDATION CHECKPOINT when agent_type is 'fixer'"

    # Verify it has all the fixer-specific content
    assert "🔧 FIXER PROTOCOL - ROOT CAUSE DIAGNOSIS" in protocol, \
        "Should have fixer protocol header"
    assert "REPRODUCE FIRST" in protocol, \
        "Should have fixer-specific mandatory steps"

    # Test case insensitive lookup
    protocol_upper = get_type_specific_requirements('FIXER')
    assert "🔍 VALIDATION CHECKPOINT" in protocol_upper, \
        "Should work with uppercase 'FIXER'"

    print("✅ PASS: get_type_specific_requirements('fixer') returns enhanced protocol")
    print(f"   Protocol length: {len(protocol)} characters")
    print(f"   Contains 8 checkpoint questions: ✓")
    return True


def test_checkpoint_formatting():
    """Test that checkpoint formatting matches existing sections."""
    protocol = get_fixer_requirements()

    # Verify emoji icon is used
    assert "🔍" in protocol, "Should use magnifying glass emoji icon"

    # Verify checkbox character is used
    assert "□" in protocol, "Should use checkbox character □"

    # Count checkbox occurrences (should be 8)
    checkbox_count = protocol.count("□")
    assert checkbox_count == 8, \
        f"Should have exactly 8 checkboxes, found {checkbox_count}"

    print("✅ PASS: Checkpoint formatting matches existing sections")
    print(f"   Emoji icon: 🔍")
    print(f"   Checkbox count: {checkbox_count}")
    return True


if __name__ == "__main__":
    print("\n" + "="*70)
    print("TESTING FIXER PROTOCOL VALIDATION CHECKPOINT")
    print("="*70 + "\n")

    try:
        test_fixer_requirements_has_validation_checkpoint()
        print()
        test_type_specific_requirements_integration()
        print()
        test_checkpoint_formatting()
        print("\n" + "="*70)
        print("ALL TESTS PASSED ✅")
        print("="*70 + "\n")
        sys.exit(0)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}\n")
        sys.exit(1)
