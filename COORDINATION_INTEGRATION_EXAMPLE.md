# Enhanced Coordination Response Integration Guide

## Overview

The enhanced coordination response format provides LLM agents with comprehensive, structured information about peer activities, enabling better collaboration and avoiding duplicate work.

## Key Components

### 1. New Module: `orchestrator/coordination.py`

- **CoordinationResponse**: Main dataclass for structured coordination data
- **format_text_response()**: Converts data to LLM-friendly text with 3 detail levels
- **calculate_relevance_score()**: Prioritizes findings based on agent context
- **detect_work_conflicts()**: Identifies overlapping work areas
- **generate_recommendations()**: Provides context-aware guidance
- **build_coordination_response()**: Constructs response from raw data

### 2. New Function: `get_enhanced_coordination_response()`

Located in `real_mcp_server.py:1997-2119`

```python
def get_enhanced_coordination_response(
    task_id: str,
    requesting_agent_id: str,
    detail_level: str = "standard"
) -> Dict[str, Any]:
    """Returns formatted text response and raw data."""
```

## Integration into MCP Tools

### Update `update_agent_progress()` (real_mcp_server.py:2468-2482)

Replace current minimal coordination with enhanced format:

```python
# BEFORE (current implementation):
minimal_status = get_minimal_coordination_info(task_id)
return {
    "success": True,
    "own_update": {...},
    "coordination_info": minimal_status if minimal_status["success"] else None
}

# AFTER (enhanced implementation):
enhanced_response = get_enhanced_coordination_response(
    task_id=task_id,
    requesting_agent_id=agent_id,
    detail_level="standard"  # Or make configurable
)

return {
    "success": True,
    "own_update": {
        "agent_id": agent_id,
        "status": status,
        "progress": progress,
        "message": message,
        "timestamp": progress_entry["timestamp"]
    },
    "coordination_text": enhanced_response.get("formatted_response", ""),
    "coordination_data": enhanced_response.get("raw_data", {}),
    "response_size": enhanced_response.get("response_size", 0)
}
```

### Update `report_agent_finding()` (real_mcp_server.py:2499-2553)

Similar enhancement for finding reports:

```python
# Replace get_comprehensive_coordination_info with:
enhanced_response = get_enhanced_coordination_response(
    task_id=task_id,
    requesting_agent_id=agent_id,
    detail_level="standard"
)

return {
    "success": True,
    "own_finding": {...},
    "coordination_text": enhanced_response.get("formatted_response", ""),
    "coordination_data": enhanced_response.get("raw_data", {})
}
```

## Response Format Examples

### Minimal Detail Level (~700 bytes)
```
============================================================
PEER COORDINATION UPDATE
============================================================
Task: TASK-20260102-210308-5bd2a5fb
Your ID: agent_123

## AGENT STATUS SUMMARY
Total Active: 3
Completed: 2
Blocked: 0

## RECENT PEER FINDINGS
  ### CRITICAL:
  🐛 [agent_2] 2 min ago
     Found SQL injection vulnerability
     ⚠️ HIGHLY RELEVANT TO YOUR WORK

## 🎯 RECOMMENDATIONS FOR YOU
🔴 COORDINATE_WITH: agent_2
   Reason: Potential duplicate work detected
```

### Standard Detail Level (~1KB)
Includes active agent details, work coverage analysis, and more findings.

### Full Detail Level (~2-3KB)
Complete information including all findings, detailed progress, and comprehensive recommendations.

## Key Features

1. **Relevance Scoring**: Findings are scored 0-1 based on:
   - Severity (critical/high gets bonus)
   - Agent type match (fixers see issues, investigators see insights)
   - Focus area keyword matching

2. **Conflict Detection**: Automatically identifies:
   - Multiple agents working on same area
   - Overlapping focus keywords
   - Duplicate investigations

3. **Smart Recommendations**:
   - Type-aware (different for fixers vs investigators)
   - Priority-based (high/medium/low)
   - Action-oriented (focus_on/avoid/coordinate_with)

4. **Work Coverage Analysis**:
   - Maps which areas have coverage
   - Identifies gaps (none), sufficient (partial/full), or excess (overlapping)

## Benefits for Agents

1. **Avoid Duplicate Work**: See what peers are working on
2. **Build on Findings**: Access relevant discoveries immediately
3. **Smart Focus**: Get recommendations on where to contribute
4. **Conflict Resolution**: Know when to coordinate vs work independently
5. **Context Preservation**: Formatted text works well in LLM context windows

## Performance Characteristics

- **Minimal**: ~700 bytes (essential info only)
- **Standard**: ~1KB (balanced detail)
- **Full**: ~2-3KB (comprehensive)
- **Max theoretical**: ~8KB (respects context window limits)

## Testing

Run the test script to see examples:

```bash
python orchestrator/coordination.py
```

Or test with real task data:

```python
from orchestrator.coordination import build_coordination_response
response = build_coordination_response(...)
print(response.format_text_response("standard"))
```

## Migration Path

1. Keep existing functions for backward compatibility
2. Add enhanced response as additional field
3. Agents can gradually adopt the new format
4. Eventually deprecate minimal format

## Future Enhancements

1. **Machine Learning**: Learn optimal relevance scoring weights
2. **Dynamic Detail**: Auto-adjust detail based on task complexity
3. **Visual Graphs**: ASCII art showing work distribution
4. **Time-based Views**: Show coordination over time windows
5. **Custom Filters**: Agent-specific finding filters