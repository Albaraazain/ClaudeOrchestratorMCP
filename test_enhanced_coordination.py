#!/usr/bin/env python3
"""Test script to verify enhanced coordination functionality."""

import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from real_mcp_server import get_comprehensive_coordination_info, get_minimal_coordination_info

# Test task ID
TEST_TASK_ID = "TASK-20260102-210308-5bd2a5fb"

print("=" * 80)
print("Testing Enhanced Coordination System")
print("=" * 80)

# Test minimal coordination (old behavior)
print("\n1. MINIMAL COORDINATION (old behavior - last 3 findings only):")
print("-" * 40)
minimal_result = get_minimal_coordination_info(TEST_TASK_ID)
if minimal_result.get("success"):
    print(f"✓ Success")
    print(f"  - Total agents spawned: {minimal_result['agent_counts']['total_spawned']}")
    print(f"  - Active agents: {minimal_result['agent_counts']['active']}")
    print(f"  - Findings returned: {len(minimal_result.get('recent_findings', []))}")
    if minimal_result.get('recent_findings'):
        print(f"  - Latest finding: {minimal_result['recent_findings'][0]['message'][:60]}...")
else:
    print(f"✗ Error: {minimal_result.get('error')}")

# Test comprehensive coordination (new behavior)
print("\n2. COMPREHENSIVE COORDINATION (new behavior - ALL findings):")
print("-" * 40)
comprehensive_result = get_comprehensive_coordination_info(
    TEST_TASK_ID,
    max_findings_per_agent=10,
    max_progress_per_agent=5
)
if comprehensive_result.get("success"):
    print(f"✓ Success")
    print(f"\nWork Summary:")
    for key, value in comprehensive_result.get('work_summary', {}).items():
        print(f"  - {key}: {value}")

    print(f"\nAgents Status ({len(comprehensive_result.get('agents', []))} agents):")
    for agent in comprehensive_result.get('agents', [])[:3]:  # Show first 3
        print(f"  - {agent['id']}: {agent['status']} ({agent['progress']}%)")

    print(f"\nFindings by Agent:")
    findings_by_agent = comprehensive_result.get('findings_by_agent', {})
    for agent_id, findings in findings_by_agent.items():
        print(f"  - {agent_id}: {len(findings)} findings")
        if findings:
            print(f"    Latest: {findings[0]['message'][:50]}...")

    print(f"\nProgress by Agent:")
    progress_by_agent = comprehensive_result.get('progress_by_agent', {})
    for agent_id, progress in progress_by_agent.items():
        print(f"  - {agent_id}: {len(progress)} progress updates")
        if progress:
            print(f"    Latest: {progress[0]['message'][:50]}...")

    print(f"\nCoordination Data:")
    coord_data = comprehensive_result.get('coordination_data', {})
    print(f"  - Total findings available: {coord_data.get('total_findings_available', 0)}")
    print(f"  - Total progress available: {coord_data.get('total_progress_available', 0)}")

    # Compare sizes
    minimal_json = json.dumps(minimal_result)
    comprehensive_json = json.dumps(comprehensive_result)
    print(f"\n3. RESPONSE SIZE COMPARISON:")
    print("-" * 40)
    print(f"  - Minimal response size: {len(minimal_json)} bytes ({len(minimal_json)/1024:.1f} KB)")
    print(f"  - Comprehensive response size: {len(comprehensive_json)} bytes ({len(comprehensive_json)/1024:.1f} KB)")
    print(f"  - Size increase: {len(comprehensive_json)/len(minimal_json):.1f}x")
else:
    print(f"✗ Error: {comprehensive_result.get('error')}")

print("\n" + "=" * 80)
print("CONCLUSION:")
if minimal_result.get("success") and comprehensive_result.get("success"):
    minimal_findings = len(minimal_result.get('recent_findings', []))
    total_findings = comprehensive_result['coordination_data'].get('total_findings_available', 0)

    if total_findings > minimal_findings:
        print(f"✅ Enhancement SUCCESSFUL: Agents now see {total_findings} findings vs {minimal_findings} before")
        print(f"   This is a {total_findings/max(minimal_findings,1):.1f}x improvement in peer visibility!")
    else:
        print(f"⚠️  Enhancement implemented but no additional findings to show yet")
else:
    print("❌ Test failed - check errors above")