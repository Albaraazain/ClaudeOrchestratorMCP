#!/usr/bin/env python3
"""Direct test of coordination functions."""

import json
import sys
import os

# Add to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'orchestrator'))

# Import the functions directly from lifecycle
from orchestrator.lifecycle import get_minimal_coordination_info, get_comprehensive_coordination_info
from orchestrator.workspace import find_task_workspace

# Test task ID
TEST_TASK_ID = "TASK-20260102-210308-5bd2a5fb"

print("=" * 80)
print("Testing Enhanced Coordination Functions from orchestrator/lifecycle.py")
print("=" * 80)

# Test minimal coordination
print("\n1. MINIMAL (old - last 3 findings):")
print("-" * 40)
minimal_result = get_minimal_coordination_info(TEST_TASK_ID, find_task_workspace=find_task_workspace)
if minimal_result.get("success"):
    print(f"✓ Findings returned: {len(minimal_result.get('recent_findings', []))}")
    for i, finding in enumerate(minimal_result.get('recent_findings', []), 1):
        print(f"  {i}. {finding['agent_id']}: {finding['message'][:60]}...")

# Test comprehensive coordination
print("\n2. COMPREHENSIVE (new - ALL findings by agent):")
print("-" * 40)
comprehensive_result = get_comprehensive_coordination_info(
    TEST_TASK_ID,
    max_findings_per_agent=10,
    max_progress_per_agent=5,
    find_task_workspace=find_task_workspace
)
if comprehensive_result.get("success"):
    findings_by_agent = comprehensive_result.get('findings_by_agent', {})
    total_findings = sum(len(f) for f in findings_by_agent.values())

    print(f"✓ Total findings available: {total_findings}")
    print(f"✓ Grouped by {len(findings_by_agent)} agents:")

    for agent_id, findings in findings_by_agent.items():
        print(f"\n  {agent_id}: {len(findings)} findings")
        for finding in findings[:2]:  # Show first 2 per agent
            print(f"    - [{finding['severity']}] {finding['message'][:50]}...")

# Compare
print("\n" + "=" * 80)
print("COMPARISON:")
if minimal_result.get("success") and comprehensive_result.get("success"):
    minimal_count = len(minimal_result.get('recent_findings', []))
    comprehensive_count = sum(len(f) for f in comprehensive_result.get('findings_by_agent', {}).values())

    print(f"  Minimal returns: {minimal_count} findings (last 3 only)")
    print(f"  Comprehensive returns: {comprehensive_count} findings (ALL, grouped by agent)")

    if comprehensive_count > minimal_count:
        print(f"\n✅ SUCCESS: {comprehensive_count/max(minimal_count,1):.1f}x more visibility!")
    else:
        print(f"\n⚠️  Same number of findings (only {minimal_count} total exist)")