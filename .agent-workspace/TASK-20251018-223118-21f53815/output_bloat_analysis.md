# JSONL Log Bloat Analysis Report

**Date:** 2025-10-18
**Analyzed by:** output_bloat_analyzer-223210-7523c1
**Task ID:** TASK-20251018-223118-21f53815

## Executive Summary

**ROOT CAUSE IDENTIFIED:** MCP tool `update_agent_progress` returns massive `coordination_info` objects (35KB+) in tool_result responses. This coordination data gets logged in EVERY progress update, causing severe log bloat.

**Impact:** 76% space savings possible with 5KB line truncation on bloated logs.

---

## 1. Sample Log Statistics

### Log Files Analyzed

| File | Size | Lines | Max Line | Lines >10KB | Space Savings (5KB trunc) |
|------|------|-------|----------|-------------|---------------------------|
| simple_test_agent-212031-9d5ba0_stream.jsonl | 129KB | 16 | 39,550 bytes | 3 (19%) | **76% (101KB saved)** |
| truncation_strategy_designer-223212-36569a_stream.jsonl | 89KB | 37 | 16,550 bytes | 1 (3%) | **25% (24KB saved)** |
| jsonl_test_agent-212417-4b12e2_stream.jsonl | 33KB | 21 | 4,962 bytes | 0 (0%) | 0% (no bloat) |

### Line Length Distribution (simple_test_agent - worst case)

```
Min:     304 bytes
Median:  1,177 bytes
P95:     39,550 bytes  ← BLOAT
P99:     39,550 bytes  ← BLOAT
Max:     39,550 bytes  ← BLOAT
```

**Key Finding:** Bloated lines are ~40KB each, while typical lines are ~1KB.

---

## 2. Top Offenders - Which Tool Types Cause Bloat

### Primary Culprit: `mcp__claude-orchestrator__update_agent_progress`

**Evidence from simple_test_agent log:**

- **Line 3 (Assistant message):** tool_use calling `update_agent_progress`
  ```json
  {
    "type": "tool_use",
    "name": "mcp__claude-orchestrator__update_agent_progress",
    "input": {
      "task_id": "TASK-...",
      "agent_id": "simple_test_agent-212031-9d5ba0",
      "status": "working",
      "message": "Hello from test agent",
      "progress": 25
    }
  }
  ```

- **Line 5 (User message):** tool_result response = **38,193 bytes total**
  - Content field: **35,538 bytes** (93% of line)
  - Contains massive `coordination_info` object with:
    - Complete task state
    - All 13 agents' full status (completed + active)
    - Each agent's full prompt (multi-KB)
    - Recent progress array (all updates)
    - Recent findings array (all discoveries)

**Pattern:** Every `update_agent_progress` and `report_agent_finding` call returns this bloated coordination_info.

### Tool Result Content Size Distribution

From simple_test_agent (5 tool_result blocks analyzed):

```
Min:     27 bytes
Median:  35,538 bytes  ← coordination_info
Max:     36,835 bytes  ← coordination_info
> 10KB:  3 out of 5 (60%)
> 30KB:  3 out of 5 (60%)
```

**Conclusion:** 60% of tool_result responses are bloated. ALL bloat is from MCP coordination_info.

---

## 3. Quantified Problem

### Space Wasted

**Worst case (simple_test_agent):**
- Total log size: 132,288 bytes (129KB)
- Bloated lines: 3 out of 16 (19% of lines)
- Bloat accounts for: 115,990 bytes (88% of total log size!)
- Space savings with 5KB truncation: 101,190 bytes (76%)

**Moderate case (truncation_strategy_designer):**
- Total log size: 91,316 bytes (89KB)
- Bloated lines: 1 out of 37 (3% of lines)
- Space savings with 5KB truncation: 23,616 bytes (25%)

### Lines Needing Truncation

| Threshold | simple_test_agent | truncation_strategy_designer |
|-----------|-------------------|------------------------------|
| > 5KB | 3 lines (19%) | 7 lines (19%) |
| > 10KB | 3 lines (19%) | 1 line (3%) |
| > 50KB | 0 lines (0%) | 0 lines (0%) |

**Key Insight:** Most bloat is in the 35-40KB range (coordination_info). No bloat exceeds 50KB in current samples.

---

## 4. Examples of Bloated Lines

### Example 1: Line 5 from simple_test_agent

**Structure:**
```json
{
  "type": "user",
  "message": {
    "role": "user",
    "content": [
      {
        "type": "tool_result",
        "tool_use_id": "toolu_01RmkPZLBsNaVeq8x8zEufNc",
        "content": "{\"success\":true,\"own_update\":{...},\"coordination_info\":{...}}"
      }
    ]
  }
}
```

**Line size:** 38,193 bytes
**Content field:** 35,538 bytes (93%)

**Content breakdown:**
- `success: true` + `own_update`: ~200 bytes (ESSENTIAL)
- `coordination_info`: ~35,300 bytes (BLOAT)
  - `task_info`: ~300 bytes
  - `agents.agents_list`: ~30,000 bytes ← **PRIMARY BLOAT**
    - 13 agent objects
    - Each agent includes full `prompt` field (multi-KB text)
  - `coordination_data.recent_progress`: ~2,000 bytes
  - `coordination_data.recent_findings`: ~3,000 bytes

### Example 2: Line 14 from simple_test_agent

**Line size:** 39,550 bytes
**Content field:** 36,835 bytes (93%)

Similar structure, but with MORE agents spawned (agents array grew).

---

## 5. Critical vs Bloat Content Identification

### ESSENTIAL Content (must preserve)

From MCP tool_result responses:
- `success: true/false` (status)
- `own_update` object (agent's own progress/finding)
- Error messages (if any)
- **Size estimate:** ~200-500 bytes

### BLOAT Content (safe to truncate)

From `coordination_info` object:
- `agents.agents_list[].prompt` ← **Each agent's full multi-KB prompt** (PRIMARY BLOAT)
- `coordination_data.recent_progress` ← Full history of all updates
- `coordination_data.recent_findings` ← Full history of all discoveries
- `agents.agents_list[].started_at`, timestamps, etc. (non-critical metadata)
- **Size estimate:** 35KB+ per coordination_info

**Why it's bloat:**
- Agents already know their own prompts (no need to log)
- Recent progress/findings accumulate over time
- Orchestrator has this data in memory/DB already
- Logging full coordination_info on EVERY update is redundant

### What Agents Actually Need from Logs

1. **Own progress:** Own update_agent_progress messages
2. **Own findings:** Own report_agent_finding messages
3. **Error messages:** Tool failures, crashes
4. **Basic status:** success/failure indicators

**What agents DON'T need:**
- Other agents' full prompts
- Complete task state snapshots
- Full coordination history

---

## 6. Programmatic Detection Opportunities

### Detecting Bloat BEFORE Truncation

```python
def is_bloat_content(json_obj):
    """Detect if this line contains bloat worth truncating."""

    # Pattern 1: tool_result with coordination_info
    if json_obj.get('type') == 'user':
        content_blocks = json_obj.get('message', {}).get('content', [])
        for block in content_blocks:
            if block.get('type') == 'tool_result':
                content_str = block.get('content', '')
                try:
                    content_json = json.loads(content_str)
                    # If coordination_info exists and is large
                    if 'coordination_info' in content_json:
                        coord_size = len(json.dumps(content_json['coordination_info']))
                        if coord_size > 10000:  # 10KB threshold
                            return True, 'coordination_info', coord_size
                except:
                    pass

    # Pattern 2: Read tool results with large file contents
    # (not observed in current samples, but possible)
    if json_obj.get('type') == 'user':
        content_blocks = json_obj.get('message', {}).get('content', [])
        for block in content_blocks:
            if block.get('type') == 'tool_result':
                content_size = len(block.get('content', ''))
                if content_size > 50000:  # 50KB threshold
                    return True, 'large_tool_result', content_size

    return False, None, 0
```

---

## 7. Recommended Truncation Strategy

### Option A: Truncate coordination_info (SMART)

**Target:** Only truncate the `coordination_info` field in tool_result responses, preserve essential data.

**Implementation:**
```python
def smart_truncate_tool_result(json_obj, max_size=5000):
    """Truncate only bloat from tool_result content."""
    if json_obj.get('type') == 'user':
        for block in json_obj.get('message', {}).get('content', []):
            if block.get('type') == 'tool_result':
                try:
                    content = json.loads(block['content'])
                    if 'coordination_info' in content:
                        # Truncate coordination_info, keep own_update
                        content['coordination_info'] = {
                            'truncated': True,
                            'reason': 'Reduced log bloat',
                            'original_size': len(json.dumps(content['coordination_info']))
                        }
                        block['content'] = json.dumps(content)
                except:
                    pass
    return json_obj
```

**Pros:**
- Preserves essential data (own_update, errors)
- Removes 95% of bloat
- Semantically aware

**Cons:**
- Requires JSON parsing of tool_result content
- More complex implementation

### Option B: Line-level truncation (SIMPLE)

**Target:** Any line exceeding 5KB gets truncated with marker.

**Implementation:**
```python
def simple_truncate_line(line, max_size=5000):
    """Truncate line if it exceeds max_size."""
    if len(line) > max_size:
        truncated = line[:max_size-100]  # Leave room for marker
        marker = {'_truncated': True, 'original_size': len(line), 'truncated_at': max_size}
        return truncated + json.dumps(marker)
    return line
```

**Pros:**
- Simple, fast
- No JSON parsing required
- Works on any bloat pattern

**Cons:**
- May truncate essential data (rare)
- Breaks JSON structure (needs repair on read)

---

## 8. Space Savings Projections

### Current Samples

| Scenario | Log Size | After 5KB Trunc | Savings |
|----------|----------|-----------------|---------|
| Heavy bloat (13 agents) | 132KB | 31KB | **76%** |
| Medium bloat (3 agents) | 89KB | 67KB | **25%** |
| No bloat | 33KB | 33KB | 0% |

### Projected for Large Tasks

**Assumption:** Task with 50 agents, each reporting progress 10 times.

- Without truncation:
  - 50 agents × 10 updates × 40KB per update = **20MB per task**

- With 5KB truncation (Option B):
  - 50 agents × 10 updates × 5KB per update = **2.5MB per task**
  - **Savings: 87.5%**

- With smart truncation (Option A):
  - 50 agents × 10 updates × 1KB per update = **500KB per task**
  - **Savings: 97.5%**

---

## 9. Recommendations

### Immediate Actions

1. **Implement smart truncation (Option A)** in get_agent_output:
   - Detect `coordination_info` in tool_result content
   - Replace with `{truncated: true, original_size: X}` stub
   - Preserve `own_update` and `success` fields

2. **Set max line length to 5KB** as safety net:
   - Catches any non-coordination_info bloat
   - Simple fallback for edge cases

### Long-term Solutions

1. **Fix MCP tool responses:**
   - `update_agent_progress` should NOT return full coordination_info in tool_result
   - Return only `{success: true, own_update: {...}}` (200 bytes)
   - Agents can query coordination separately if needed

2. **Implement log rotation:**
   - Rotate logs at 10MB per file
   - Compress old logs with gzip (90% compression on JSON)

3. **Add monitoring:**
   - Track log sizes per task
   - Alert if any log exceeds 50MB
   - Collect metrics on truncation frequency

---

## 10. Evidence Summary

### Files Analyzed
- `.agent-workspace/TASK-20251017-215604-df6a3cbd/logs/simple_test_agent-212031-9d5ba0_stream.jsonl`
- `.agent-workspace/TASK-20251018-223118-21f53815/logs/truncation_strategy_designer-223212-36569a_stream.jsonl`
- `.agent-workspace/TASK-20251018-212410-ec53cbb6/logs/jsonl_test_agent-212417-4b12e2_stream.jsonl`

### Tools Used
- Python script: `/tmp/analyze_logs.py` (line length stats, tool_result analysis)
- Commands: `awk`, `sed`, `jq`, `find`

### Key Metrics
- **Bloat rate:** 19% of lines in worst case, 3% in moderate case
- **Bloat source:** 100% from MCP coordination_info
- **Space savings:** 76% in worst case, 25% in moderate case
- **Line size range:** 35-40KB for bloated lines

---

## Conclusion

The JSONL log bloat is caused by a **design flaw in MCP tool responses**. The `update_agent_progress` tool returns massive `coordination_info` objects (35KB+) containing:
- All agents' full prompts (multi-KB each)
- Complete task state snapshots
- Full coordination history

This gets logged on EVERY progress update, causing severe bloat. **Smart truncation of coordination_info can reduce log sizes by 76-97%** while preserving essential debugging data.

**Immediate fix:** Implement smart truncation in get_agent_output.
**Proper fix:** Modify MCP tools to NOT return bloated coordination_info in tool_result responses.
