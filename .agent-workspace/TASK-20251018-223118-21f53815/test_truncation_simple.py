#!/usr/bin/env python3
"""
Simple test of truncation functions without importing full MCP server.
"""

import json
import copy

# Copy truncation functions directly for testing
MAX_LINE_LENGTH = 8192
MAX_TOOL_RESULT_CONTENT = 2048
MAX_ASSISTANT_TEXT = 4096

def smart_preview_truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    lines = text.split('\n')
    PREVIEW_HEAD = 30
    PREVIEW_TAIL = 10
    if len(lines) <= PREVIEW_HEAD + PREVIEW_TAIL:
        return line_based_truncate(text, max_length)
    head_lines = lines[:PREVIEW_HEAD]
    tail_lines = lines[-PREVIEW_TAIL:]
    removed_lines = len(lines) - (PREVIEW_HEAD + PREVIEW_TAIL)
    removed_chars = len(text) - (sum(len(l) for l in head_lines) + sum(len(l) for l in tail_lines))
    marker = f"\n\n[... TRUNCATED: {removed_lines} lines ({removed_chars} chars) removed ...]\n\n"
    preview = '\n'.join(head_lines) + marker + '\n'.join(tail_lines)
    if len(preview) > max_length:
        return line_based_truncate(preview, max_length)
    return preview

def line_based_truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    lines = text.split('\n')
    kept_lines = []
    current_length = 0
    marker_space = 200
    for line in lines:
        line_len = len(line) + 1
        if current_length + line_len > max_length - marker_space:
            break
        kept_lines.append(line)
        current_length += line_len
    if len(kept_lines) == len(lines):
        return text
    removed_lines = len(lines) - len(kept_lines)
    removed_chars = len(text) - current_length
    marker = f"\n\n[... TRUNCATED: {removed_lines} lines ({removed_chars} chars) removed ...]"
    return '\n'.join(kept_lines) + marker

def detect_and_truncate_binary(content: str, max_length: int) -> str:
    import re
    if len(content) > 200:
        base64_pattern = r'^[A-Za-z0-9+/]{100,}={0,2}$'
        if re.match(base64_pattern, content[:200]):
            return f"[BASE64_DATA: {len(content)} bytes, truncated for log efficiency]"
    if len(content) > 500:
        binary_indicators = ['\\x00', 'PNG\\r\\n', 'GIF89', 'JFIF']
        if any(indicator in content[:500] for indicator in binary_indicators):
            return f"[BINARY_DATA: {len(content)} bytes, truncated for log efficiency]"
    return smart_preview_truncate(content, max_length)

def is_already_truncated(obj: dict) -> bool:
    if obj.get('truncated') == True:
        return True
    def has_truncation_marker(value):
        if isinstance(value, str):
            return '[... TRUNCATED:' in value or '[BASE64_DATA:' in value or '[BINARY_DATA:' in value
        elif isinstance(value, dict):
            return any(has_truncation_marker(v) for v in value.values())
        elif isinstance(value, list):
            return any(has_truncation_marker(item) for item in value)
        return False
    return has_truncation_marker(obj)

def truncate_json_structure(obj: dict, max_length: int) -> dict:
    if is_already_truncated(obj):
        return obj
    truncated = copy.deepcopy(obj)
    msg_type = truncated.get('type')
    if msg_type == 'error':
        return truncated
    if msg_type == 'system' and truncated.get('subtype') == 'init':
        return truncated
    if msg_type == 'user' and 'message' in truncated:
        message = truncated['message']
        if 'content' in message and isinstance(message['content'], list):
            for item in message['content']:
                if isinstance(item, dict) and item.get('type') == 'tool_result':
                    if 'content' in item and isinstance(item['content'], str):
                        original_len = len(item['content'])
                        if original_len > MAX_TOOL_RESULT_CONTENT:
                            item['content'] = detect_and_truncate_binary(
                                item['content'],
                                MAX_TOOL_RESULT_CONTENT
                            )
                            item['truncated'] = True
                            item['original_length'] = original_len
    if msg_type == 'assistant' and 'message' in truncated:
        message = truncated['message']
        if 'content' in message and isinstance(message['content'], list):
            for item in message['content']:
                if isinstance(item, dict) and 'text' in item:
                    original_len = len(item['text'])
                    if original_len > MAX_ASSISTANT_TEXT:
                        item['text'] = line_based_truncate(
                            item['text'],
                            MAX_ASSISTANT_TEXT
                        )
                        item['truncated'] = True
                        item['original_length'] = original_len
    return truncated

def safe_json_truncate(line: str, max_length: int) -> str:
    if len(line) <= max_length:
        return line
    try:
        obj = json.loads(line)
        truncated_obj = truncate_json_structure(obj, max_length)
        truncated_line = json.dumps(truncated_obj)
        if len(truncated_line) > max_length:
            return json.dumps({
                "type": "truncation_error",
                "error": "Line too large even after content truncation",
                "original_type": obj.get('type'),
                "original_size": len(line),
                "max_allowed": max_length,
                "note": "Check raw log file for full content"
            })
        return truncated_line
    except json.JSONDecodeError as e:
        print(f"Warning: Malformed JSON: {e}")
        return line[:max_length] + "..."

# Test with the bloated log
log_file = ".agent-workspace/TASK-20251017-215604-df6a3cbd/logs/simple_test_agent-212031-9d5ba0_stream.jsonl"

print("=" * 80)
print("TESTING TRUNCATION ON BLOATED LOG")
print("=" * 80)
print()

lines_truncated = 0
bytes_before = 0
bytes_after = 0
line_num = 0

with open(log_file, 'r') as f:
    for line in f:
        line_num += 1
        line = line.strip()
        if not line:
            continue

        original_size = len(line)
        bytes_before += original_size

        if original_size > MAX_LINE_LENGTH:
            print(f"Line {line_num}: {original_size:,} bytes -> truncating...")
            truncated = safe_json_truncate(line, MAX_LINE_LENGTH)
            new_size = len(truncated)
            bytes_after += new_size
            lines_truncated += 1
            saved = original_size - new_size
            print(f"  After: {new_size:,} bytes (saved {saved:,} bytes, {saved/original_size*100:.1f}%)")
            print()
        else:
            bytes_after += original_size

print("=" * 80)
print("RESULTS:")
print(f"  Lines truncated: {lines_truncated}/{line_num}")
print(f"  Bytes before: {bytes_before:,}")
print(f"  Bytes after: {bytes_after:,}")
print(f"  Bytes saved: {bytes_before - bytes_after:,}")
print(f"  Space savings: {(bytes_before - bytes_after)/bytes_before*100:.1f}%")
print()

if lines_truncated > 0:
    print("✅ TRUNCATION WORKING!")
else:
    print("⚠️  No lines needed truncation")
