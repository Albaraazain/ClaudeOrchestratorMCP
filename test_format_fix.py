#!/usr/bin/env python3
"""
Test script to verify the format_task_enrichment_prompt fix
"""

def format_task_enrichment_prompt_test(task_registry):
    """Test version of the function"""
    task_context = task_registry.get('task_context', {})
    if not task_context:
        return ""

    sections = []

    # Background context
    if bg := task_context.get('background_context'):
        sections.append(f"""
📋 BACKGROUND CONTEXT:
{bg}
""")

    # Expected deliverables - FIXED VERSION
    if deliverables := task_context.get('expected_deliverables'):
        items = '\n'.join(f"  • {d}" for d in deliverables)
        sections.append(f"""
✅ EXPECTED DELIVERABLES:
{items}
""")

    # Success criteria - FIXED VERSION
    if criteria := task_context.get('success_criteria'):
        items = '\n'.join(f"  • {c}" for c in criteria)
        sections.append(f"""
🎯 SUCCESS CRITERIA:
{items}
""")

    # Constraints - FIXED VERSION
    if constraints := task_context.get('constraints'):
        items = '\n'.join(f"  • {c}" for c in constraints)
        sections.append(f"""
⚠️ CONSTRAINTS:
{items}
""")

    return '\n'.join(sections)


# Test data matching what create_real_task stores
test_registry = {
    'task_id': 'TEST-001',
    'task_description': 'Test task',
    'task_context': {
        'background_context': 'Some background info',
        'expected_deliverables': ['Deliverable 1', 'Deliverable 2'],  # Simple list, not nested dict
        'success_criteria': ['Criteria 1', 'Criteria 2'],  # Simple list, not nested dict
        'constraints': ['Constraint 1', 'Constraint 2']  # Simple list, not nested dict
    }
}

print("Testing format_task_enrichment_prompt with list values...")
try:
    result = format_task_enrichment_prompt_test(test_registry)
    print("✅ SUCCESS! Function works correctly with list values")
    print("\nGenerated output:")
    print(result)
except AttributeError as e:
    print(f"❌ FAILED! Got error: {e}")
except Exception as e:
    print(f"❌ FAILED! Unexpected error: {e}")
