#!/usr/bin/env python3
"""Test the enhanced coordination response format."""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from real_mcp_server import get_enhanced_coordination_response

# Test with current task
task_id = "TASK-20260102-210308-5bd2a5fb"
agent_id = "response_designer-211505-6d4754"

print("Testing enhanced coordination response...")
print("=" * 60)

# Test minimal level
print("\n1. MINIMAL DETAIL LEVEL:")
print("-" * 40)
result = get_enhanced_coordination_response(task_id, agent_id, "minimal")
if result["success"]:
    print(result["formatted_response"])
    print(f"\nResponse size: {result['response_size']} bytes")
else:
    print(f"ERROR: {result['error']}")

# Test standard level
print("\n2. STANDARD DETAIL LEVEL:")
print("-" * 40)
result = get_enhanced_coordination_response(task_id, agent_id, "standard")
if result["success"]:
    print(result["formatted_response"])
    print(f"\nResponse size: {result['response_size']} bytes")
else:
    print(f"ERROR: {result['error']}")

print("\n" + "=" * 60)
print("Test complete!")