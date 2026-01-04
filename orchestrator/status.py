"""
Status and output retrieval functions for the Claude Orchestrator.

This module handles:
- Task status retrieval (get_real_task_status)
- Agent output retrieval (get_agent_output)
- JSONL parsing and filtering utilities
- Output truncation for log efficiency
"""

import json
import os
import re
import copy
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import logging

logger = logging.getLogger(__name__)

# ============================================================================
# Truncation Limits
# ============================================================================

MAX_LINE_LENGTH = 8192  # 8KB per JSONL line
MAX_TOOL_RESULT_CONTENT = 2048  # 2KB for tool_result.content
MAX_ASSISTANT_TEXT = 4096  # 4KB for assistant text messages

# Aggressive truncation limits (for quick status checks)
AGGRESSIVE_LINE_LENGTH = 1024  # 1KB per line
AGGRESSIVE_TOOL_RESULT = 512  # 512 bytes for tool_result.content


# ============================================================================
# JSONL Helper Functions for Robust Log Reading
# ============================================================================

def read_jsonl_lines(filepath: str, max_lines: Optional[int] = None) -> List[str]:
    """
    Read JSONL file with robust error handling for incomplete/malformed lines.
    Returns raw text lines (not parsed JSON).

    Args:
        filepath: Path to JSONL file
        max_lines: Maximum number of lines to read (None = all)

    Returns:
        List of text lines
    """
    if not os.path.exists(filepath):
        return []

    try:
        lines = []
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if line:  # Skip empty lines
                    lines.append(line)
                    if max_lines and len(lines) >= max_lines:
                        break
        return lines
    except Exception as e:
        logger.warning(f"Error reading JSONL file {filepath}: {e}")
        return []


def tail_jsonl_efficient(filepath: str, n_lines: int) -> List[str]:
    """
    Efficiently read last N lines from JSONL file using reverse seeking.
    Handles large files (GB+) without loading entire file into memory.

    Args:
        filepath: Path to JSONL file
        n_lines: Number of lines to read from end

    Returns:
        List of last N text lines
    """
    if not os.path.exists(filepath):
        return []

    if n_lines <= 0:
        return []

    try:
        file_size = os.path.getsize(filepath)
        if file_size == 0:
            return []

        # For small files, just read all lines
        if file_size < 1024 * 1024:  # < 1MB
            all_lines = read_jsonl_lines(filepath)
            return all_lines[-n_lines:] if len(all_lines) > n_lines else all_lines

        # For large files, seek from end
        # Estimate: avg line ~300 bytes, read slightly more to be safe
        seek_size = min(n_lines * 400, file_size)

        with open(filepath, 'rb') as f:
            f.seek(-seek_size, os.SEEK_END)
            data = f.read().decode('utf-8', errors='ignore')

        # Split into lines and filter
        lines = [line.strip() for line in data.split('\n') if line.strip()]

        # Return last N lines
        return lines[-n_lines:] if len(lines) > n_lines else lines

    except Exception as e:
        logger.warning(f"Error tailing JSONL file {filepath}: {e}")
        return []


def filter_lines_regex(lines: List[str], pattern: Optional[str]) -> Tuple[List[str], Optional[str]]:
    """
    Apply regex filter to lines.

    Args:
        lines: List of text lines
        pattern: Regex pattern (None = no filtering)

    Returns:
        Tuple of (filtered_lines, error_message)
        error_message is None if successful, string if regex invalid
    """
    if not pattern:
        return lines, None

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return [], f"Invalid regex pattern: {e}"

    filtered = [line for line in lines if regex.search(line)]
    return filtered, None


def parse_jsonl_lines(lines: List[str]) -> Tuple[List[dict], List[dict]]:
    """
    Parse JSONL lines with robust error recovery.
    Skips malformed lines and continues parsing.

    Args:
        lines: List of text lines (each should be valid JSON)

    Returns:
        Tuple of (parsed_objects, parse_errors)
        parse_errors contains info about lines that failed to parse
    """
    parsed = []
    errors = []

    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)
            parsed.append(obj)
        except json.JSONDecodeError as e:
            errors.append({
                "line_number": i + 1,
                "line_preview": line[:100],  # Truncate for safety
                "error": str(e)
            })
            # Continue parsing next lines (don't fail on single bad line)

    return parsed, errors


def format_output_by_type(lines: List[str], format_type: str) -> Tuple[Any, Optional[List[dict]]]:
    """
    Format lines according to requested output format.

    Args:
        lines: List of text lines
        format_type: 'text', 'jsonl', or 'parsed'

    Returns:
        Tuple of (formatted_output, parse_errors)
        parse_errors is None unless format_type='parsed'
    """
    if format_type == "text":
        return '\n'.join(lines), None

    elif format_type == "jsonl":
        return '\n'.join(lines), None

    elif format_type == "parsed":
        parsed, errors = parse_jsonl_lines(lines)
        return parsed, errors if errors else None

    else:
        raise ValueError(f"Unknown format type: {format_type}. Must be 'text', 'jsonl', or 'parsed'")


def collect_log_metadata(filepath: str, lines: List[str], filtered_lines: List[str],
                         parse_errors: Optional[List[dict]], source: str) -> dict:
    """
    Collect metadata about the log file and processing.

    Args:
        filepath: Path to log file
        lines: Original lines before filtering
        filtered_lines: Lines after filtering
        parse_errors: Parse errors if format='parsed', None otherwise
        source: 'jsonl_log' or 'tmux_session'

    Returns:
        Metadata dictionary
    """
    metadata = {
        "log_source": source,
        "total_lines": len(lines),
        "returned_lines": len(filtered_lines)
    }

    if os.path.exists(filepath):
        stat = os.stat(filepath)
        metadata["file_path"] = filepath
        metadata["file_size_bytes"] = stat.st_size
        metadata["file_modified_time"] = datetime.fromtimestamp(stat.st_mtime).isoformat()

    # Extract timestamps from first and last lines (if JSONL)
    if filtered_lines:
        try:
            first_obj = json.loads(filtered_lines[0])
            if 'timestamp' in first_obj:
                metadata["first_timestamp"] = first_obj['timestamp']
        except:
            pass

        try:
            last_obj = json.loads(filtered_lines[-1])
            if 'timestamp' in last_obj:
                metadata["last_timestamp"] = last_obj['timestamp']
        except:
            pass

    if parse_errors:
        metadata["parse_errors"] = parse_errors

    return metadata


# ============================================================================
# Content Analysis Functions
# ============================================================================

def detect_repetitive_content(lines: List[str]) -> dict:
    """
    Analyze lines for repetitive patterns (e.g., same tool calls repeated).

    Returns:
        Dict with repetition statistics and groups of similar lines
    """
    tool_call_counts = {}
    error_patterns = {}
    status_updates = []

    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)

            # Track tool calls
            if obj.get('type') == 'tool_use':
                tool_name = obj.get('name', 'unknown')
                tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1

            # Track errors
            elif 'error' in obj or obj.get('type') == 'error':
                error_msg = str(obj.get('error', obj.get('message', '')))[:100]
                error_patterns[error_msg] = error_patterns.get(error_msg, 0) + 1

            # Track status updates
            elif obj.get('type') in ['status', 'progress']:
                status_updates.append(i)

        except (json.JSONDecodeError, AttributeError):
            continue

    # Identify highly repetitive tool calls (more than 5 occurrences)
    repetitive_tools = {k: v for k, v in tool_call_counts.items() if v > 5}

    return {
        'tool_call_counts': tool_call_counts,
        'repetitive_tools': repetitive_tools,
        'error_patterns': error_patterns,
        'status_update_indices': status_updates,
        'has_repetition': bool(repetitive_tools) or any(count > 3 for count in error_patterns.values())
    }


def extract_critical_lines(lines: List[str], analysis: dict) -> List[int]:
    """
    Identify indices of critical lines that should be preserved.

    Returns:
        List of line indices that are critical
    """
    critical_indices = set()

    for i, line in enumerate(lines):
        try:
            obj = json.loads(line)
            obj_type = obj.get('type', '')

            # Always keep errors
            if 'error' in obj or obj_type == 'error':
                critical_indices.add(i)

            # Keep status changes (but not all status updates)
            elif obj_type in ['completed', 'failed', 'blocked']:
                critical_indices.add(i)

            # Keep findings/insights
            elif obj_type in ['finding', 'insight', 'recommendation']:
                critical_indices.add(i)

            # Keep first and last occurrence of each unique tool call
            elif obj_type == 'tool_use':
                tool_name = obj.get('name', '')
                # This is simplified - in practice we'd track first/last per tool
                # For now, we'll handle this in the sampling logic
                pass

        except (json.JSONDecodeError, AttributeError):
            continue

    # Always include first and last lines
    if lines:
        critical_indices.add(0)
        critical_indices.add(len(lines) - 1)

    return sorted(list(critical_indices))


def intelligent_sample_lines(lines: List[str], max_bytes: int, analysis: dict) -> Tuple[List[str], dict]:
    """
    Intelligently sample lines to fit within max_bytes while preserving critical info.

    Strategy:
    1. Always include critical lines (errors, status changes, findings)
    2. For repetitive content, show first + last + count summary
    3. Sample evenly from remaining lines

    Returns:
        Tuple of (sampled_lines, sampling_stats)
    """
    if not lines:
        return [], {'sampled': False}

    # Calculate current size
    current_size = sum(len(line) for line in lines)
    if current_size <= max_bytes:
        return lines, {'sampled': False, 'original_size': current_size}

    # Get critical line indices
    critical_indices = extract_critical_lines(lines, analysis)
    critical_lines_size = sum(len(lines[i]) for i in critical_indices)

    # If critical lines alone exceed max_bytes, we need aggressive truncation
    if critical_lines_size > max_bytes:
        # Take first N and last N critical lines
        budget_per_end = max_bytes // 2
        result = []
        size = 0

        # Add from beginning
        for i in critical_indices:
            if size + len(lines[i]) > budget_per_end:
                break
            result.append((i, lines[i]))
            size += len(lines[i])

        # Add separator
        separator = json.dumps({
            'type': 'truncation_marker',
            'message': f'... {len(lines) - len(result)} lines omitted ...',
            'reason': 'Critical lines exceeded budget'
        })
        result.append((-1, separator))

        # Add from end
        size = 0
        end_lines = []
        for i in reversed(critical_indices):
            if size + len(lines[i]) > budget_per_end:
                break
            end_lines.insert(0, (i, lines[i]))
            size += len(lines[i])

        result.extend(end_lines)

        return [line for _, line in result], {
            'sampled': True,
            'strategy': 'critical_only',
            'original_lines': len(lines),
            'sampled_lines': len(result),
            'original_size': current_size,
            'final_size': sum(len(l) for _, l in result)
        }

    # Otherwise, smart sampling: critical + evenly sampled non-critical
    remaining_budget = max_bytes - critical_lines_size
    non_critical_indices = [i for i in range(len(lines)) if i not in critical_indices]

    # Sample non-critical lines
    sampled_non_critical = []
    if non_critical_indices and remaining_budget > 0:
        # Calculate how many we can fit
        avg_line_size = sum(len(lines[i]) for i in non_critical_indices) / len(non_critical_indices)
        target_count = min(len(non_critical_indices), int(remaining_budget / avg_line_size))

        # Sample evenly
        if target_count > 0:
            step = len(non_critical_indices) / target_count
            sampled_non_critical = [non_critical_indices[int(i * step)] for i in range(target_count)]

    # Combine and sort
    all_indices = sorted(critical_indices + sampled_non_critical)
    result = []

    for i, idx in enumerate(all_indices):
        result.append(lines[idx])
        # Add gap markers where we skipped lines
        if i < len(all_indices) - 1 and all_indices[i + 1] - idx > 1:
            gap_size = all_indices[i + 1] - idx - 1
            marker = json.dumps({
                'type': 'truncation_marker',
                'message': f'... {gap_size} lines omitted ...'
            })
            result.append(marker)

    final_size = sum(len(line) for line in result)

    return result, {
        'sampled': True,
        'strategy': 'intelligent_sampling',
        'original_lines': len(lines),
        'sampled_lines': len(all_indices),
        'critical_lines': len(critical_indices),
        'non_critical_sampled': len(sampled_non_critical),
        'original_size': current_size,
        'final_size': final_size,
        'compression_ratio': round(final_size / current_size, 3)
    }


def summarize_output(lines: List[str]) -> str:
    """
    Create a summary showing only errors, status changes, and key findings.

    Returns:
        Summary string
    """
    summary_items = []
    errors = []
    status_changes = []
    findings = []
    tool_calls = {}

    for line in lines:
        try:
            obj = json.loads(line)
            obj_type = obj.get('type', '')

            # Collect errors
            if 'error' in obj or obj_type == 'error':
                error_msg = obj.get('error', obj.get('message', 'Unknown error'))
                errors.append(error_msg)

            # Collect status changes
            elif obj_type in ['completed', 'failed', 'blocked', 'status']:
                status = obj.get('status', obj_type)
                message = obj.get('message', '')
                status_changes.append(f"{status}: {message}")

            # Collect findings
            elif obj_type in ['finding', 'insight', 'recommendation']:
                findings.append(obj.get('message', str(obj)))

            # Count tool calls
            elif obj_type == 'tool_use':
                tool_name = obj.get('name', 'unknown')
                tool_calls[tool_name] = tool_calls.get(tool_name, 0) + 1

        except (json.JSONDecodeError, AttributeError):
            continue

    # Build summary
    summary_items.append(f"=== OUTPUT SUMMARY ({len(lines)} total lines) ===\n")

    if errors:
        summary_items.append(f"\nERRORS ({len(errors)}):")
        for i, err in enumerate(errors[:5], 1):  # Show first 5
            summary_items.append(f"  {i}. {err}")
        if len(errors) > 5:
            summary_items.append(f"  ... and {len(errors) - 5} more errors")

    if status_changes:
        summary_items.append(f"\nSTATUS CHANGES ({len(status_changes)}):")
        for i, status in enumerate(status_changes[-5:], 1):  # Show last 5
            summary_items.append(f"  {i}. {status}")

    if findings:
        summary_items.append(f"\nFINDINGS ({len(findings)}):")
        for i, finding in enumerate(findings, 1):
            summary_items.append(f"  {i}. {finding}")

    if tool_calls:
        summary_items.append(f"\nTOOL CALLS:")
        for tool, count in sorted(tool_calls.items(), key=lambda x: -x[1]):
            summary_items.append(f"  - {tool}: {count}x")

    return '\n'.join(summary_items)


# ============================================================================
# Truncation Functions
# ============================================================================

def smart_preview_truncate(text: str, max_length: int) -> str:
    """
    Intelligent preview: first N + last M lines.
    Use for: file contents, long outputs.

    Optimized for orchestrator's use case:
    - Main agent doesn't need full file contents
    - Wants to see: what file, rough size, first/last lines
    - Debugging: can always read raw log if needed

    Args:
        text: Text to truncate
        max_length: Maximum length in characters

    Returns:
        Truncated text with marker
    """
    if len(text) <= max_length:
        return text

    lines = text.split('\n')

    # Strategy: Keep first 30 lines + last 10 lines
    # This shows: file header/structure + recent changes
    PREVIEW_HEAD = 30
    PREVIEW_TAIL = 10

    if len(lines) <= PREVIEW_HEAD + PREVIEW_TAIL:
        # Fallback to line-based truncation
        return line_based_truncate(text, max_length)

    head_lines = lines[:PREVIEW_HEAD]
    tail_lines = lines[-PREVIEW_TAIL:]

    removed_lines = len(lines) - (PREVIEW_HEAD + PREVIEW_TAIL)
    removed_chars = len(text) - (sum(len(l) for l in head_lines) + sum(len(l) for l in tail_lines))

    marker = f"\n\n[... TRUNCATED: {removed_lines} lines ({removed_chars} chars) removed ...]\n\n"

    preview = '\n'.join(head_lines) + marker + '\n'.join(tail_lines)

    # If preview still too long, use line-based truncation
    if len(preview) > max_length:
        return line_based_truncate(preview, max_length)

    return preview


def line_based_truncate(text: str, max_length: int) -> str:
    """
    Truncate at line boundaries to preserve readability.
    Use for: code snippets, structured output.

    Args:
        text: Text to truncate
        max_length: Maximum length in characters

    Returns:
        Truncated text with marker
    """
    if len(text) <= max_length:
        return text

    lines = text.split('\n')

    # Try to fit whole lines within max_length
    kept_lines = []
    current_length = 0
    marker_space = 200  # Reserve space for marker

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_length + line_len > max_length - marker_space:
            break
        kept_lines.append(line)
        current_length += line_len

    if len(kept_lines) == len(lines):
        return text  # All fit

    removed_lines = len(lines) - len(kept_lines)
    removed_chars = len(text) - current_length

    marker = f"\n\n[... TRUNCATED: {removed_lines} lines ({removed_chars} chars) removed ...]"
    return '\n'.join(kept_lines) + marker


def simple_truncate(text: str, max_length: int) -> str:
    """
    Simple character-based truncation with marker.
    Use for: assistant text, simple strings.

    Args:
        text: Text to truncate
        max_length: Maximum length in characters

    Returns:
        Truncated text with marker
    """
    if len(text) <= max_length:
        return text

    marker_template = "\n\n[... TRUNCATED: {removed} chars removed ...]"
    # Calculate space needed for marker (with placeholder)
    marker_len = len(marker_template.format(removed=999999))  # Conservative estimate

    removed = len(text) - max_length + marker_len
    truncated = text[:max_length - marker_len]
    return truncated + marker_template.format(removed=removed)


def truncate_coordination_info(coord_data: dict) -> dict:
    """
    Intelligently truncate coordination_info structure to reduce size from ~25KB to ~5KB.

    This function is designed to handle the coordination_info structure returned by
    MCP tools (update_agent_progress, report_agent_finding) which contains:
    - agents_registry: Full details of all agents
    - coordination_data.recent_progress: Last 20 progress updates
    - coordination_data.recent_findings: Last 10 findings

    Strategy:
    - Keep only 3 most recent findings (not 10) → saves ~7KB
    - Keep only 5 most recent progress updates (not 20) → saves ~5KB
    - Summarize agents_registry (counts only, not full details) → saves ~4KB

    Args:
        coord_data: Parsed coordination_info dictionary

    Returns:
        Truncated coordination_info with same structure but reduced data
    """
    # Deep copy to avoid mutating original
    truncated = copy.deepcopy(coord_data)

    # Handle coordination_data if present
    if 'coordination_data' in truncated:
        coord = truncated['coordination_data']

        # Truncate recent_findings: keep only 3 most recent (not 10)
        if 'recent_findings' in coord and isinstance(coord['recent_findings'], list):
            if len(coord['recent_findings']) > 3:
                coord['recent_findings'] = coord['recent_findings'][:3]
                coord['findings_truncated'] = True

        # Truncate recent_progress: keep only 5 most recent (not 20)
        if 'recent_progress' in coord and isinstance(coord['recent_progress'], list):
            if len(coord['recent_progress']) > 5:
                coord['recent_progress'] = coord['recent_progress'][:5]
                coord['progress_truncated'] = True

    # Summarize agents_registry: keep counts only, not full details
    if 'agents' in truncated and isinstance(truncated['agents'], list):
        agent_list = truncated['agents']
        if len(agent_list) > 0:
            # Replace full agent list with summary
            truncated['agents_summary'] = {
                'total_count': len(agent_list),
                'by_status': {},
                'by_type': {}
            }

            # Count by status and type
            for agent in agent_list:
                status = agent.get('status', 'unknown')
                agent_type = agent.get('type', 'unknown')

                truncated['agents_summary']['by_status'][status] = \
                    truncated['agents_summary']['by_status'].get(status, 0) + 1
                truncated['agents_summary']['by_type'][agent_type] = \
                    truncated['agents_summary']['by_type'].get(agent_type, 0) + 1

            # Keep only 2 sample agents (first and last) for reference
            truncated['agents'] = [agent_list[0], agent_list[-1]] if len(agent_list) > 1 else agent_list
            truncated['agents_truncated'] = True

    # Mark as truncated for tracking
    truncated['_truncated'] = True

    return truncated


def detect_and_truncate_binary(content: str, max_length: int) -> str:
    """
    Aggressively truncate base64/binary data.

    Args:
        content: Content to check and potentially truncate
        max_length: Maximum length for non-binary content

    Returns:
        Truncated content or summary if binary
    """
    # Detect base64 pattern (long sequences of base64 chars)
    if len(content) > 200:
        base64_pattern = r'^[A-Za-z0-9+/]{100,}={0,2}$'
        if re.match(base64_pattern, content[:200]):
            return f"[BASE64_DATA: {len(content)} bytes, truncated for log efficiency]"

    # Detect binary indicators
    if len(content) > 500:
        binary_indicators = ['\\x00', 'PNG\\r\\n', 'GIF89', 'JFIF']
        if any(indicator in content[:500] for indicator in binary_indicators):
            return f"[BINARY_DATA: {len(content)} bytes, truncated for log efficiency]"

    # Not binary, use smart preview
    return smart_preview_truncate(content, max_length)


def is_already_truncated(obj: dict) -> bool:
    """
    Check if object was already truncated.
    Prevents re-truncation that loses more data.

    Args:
        obj: Parsed JSON object

    Returns:
        True if already truncated
    """
    # Check for truncation marker flag
    if obj.get('truncated') == True:
        return True

    # Check for truncation text markers (recursive)
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
    """
    Truncate while preserving JSON structure.
    Specifically targets tool_result.content and assistant text bloat.

    Args:
        obj: Parsed JSON object
        max_length: Maximum length for the serialized JSON

    Returns:
        Truncated object that maintains JSON validity
    """
    # Check if already truncated
    if is_already_truncated(obj):
        return obj

    # Deep copy to avoid mutating original
    truncated = copy.deepcopy(obj)

    # Handle different message types
    msg_type = truncated.get('type')

    # NEVER truncate error messages
    if msg_type == 'error':
        return truncated

    # NEVER truncate system init messages
    if msg_type == 'system' and truncated.get('subtype') == 'init':
        return truncated

    # Truncate user messages (tool_result content)
    if msg_type == 'user' and 'message' in truncated:
        message = truncated['message']
        if 'content' in message and isinstance(message['content'], list):
            for item in message['content']:
                if isinstance(item, dict) and item.get('type') == 'tool_result':
                    # This is the bloat target!
                    if 'content' in item and isinstance(item['content'], str):
                        original_len = len(item['content'])
                        if original_len > MAX_TOOL_RESULT_CONTENT:
                            # Try to detect and intelligently truncate coordination_info
                            try:
                                parsed_content = json.loads(item['content'])

                                # Check if this is coordination_info structure
                                # It typically has keys like: coordination_info, own_update, own_finding
                                is_coordination = (
                                    isinstance(parsed_content, dict) and
                                    'coordination_info' in parsed_content
                                )

                                if is_coordination:
                                    # Apply intelligent truncation to coordination_info
                                    if 'coordination_info' in parsed_content:
                                        parsed_content['coordination_info'] = truncate_coordination_info(
                                            parsed_content['coordination_info']
                                        )

                                    # Re-serialize with truncated coordination_info
                                    item['content'] = json.dumps(parsed_content)
                                    item['truncated'] = True
                                    item['truncation_type'] = 'intelligent_coordination_info'
                                    item['original_length'] = original_len
                                else:
                                    # Not coordination_info, use existing blind truncation
                                    item['content'] = detect_and_truncate_binary(
                                        item['content'],
                                        MAX_TOOL_RESULT_CONTENT
                                    )
                                    item['truncated'] = True
                                    item['truncation_type'] = 'blind_string'
                                    item['original_length'] = original_len

                            except (json.JSONDecodeError, TypeError, KeyError):
                                # Not JSON or parsing failed, fall back to binary detection
                                item['content'] = detect_and_truncate_binary(
                                    item['content'],
                                    MAX_TOOL_RESULT_CONTENT
                                )
                                item['truncated'] = True
                                item['truncation_type'] = 'blind_string_fallback'
                                item['original_length'] = original_len

    # Truncate assistant messages (long reasoning)
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
    """
    Truncate JSONL line while preserving JSON validity.
    Main entry point for line truncation.

    Args:
        line: Raw JSONL line
        max_length: Maximum length for the line

    Returns:
        Truncated line (still valid JSON)
    """
    if len(line) <= max_length:
        return line

    try:
        # Parse JSON
        obj = json.loads(line)

        # Truncate content fields (preserves structure)
        truncated_obj = truncate_json_structure(obj, max_length)

        # Re-serialize
        truncated_line = json.dumps(truncated_obj)

        # If STILL too long after smart truncation, aggressive fallback
        if len(truncated_line) > max_length:
            # Last resort: return error marker with metadata
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
        # Malformed JSON, simple truncate
        logger.warning(f"Malformed JSONL during truncation: {e}")
        return simple_truncate(line, max_length)


# ============================================================================
# Compact Line Formatting (for monitoring)
# ============================================================================

def format_line_compact(line: str) -> str:
    """
    Convert a JSONL log entry to a compact human-readable format.

    Extracts only essential information:
    - Tool calls: tool name + brief result
    - Progress updates: percentage + message
    - Assistant text: first 100 chars
    - Errors: full error message

    Returns single-line summary, max ~200 chars.
    """
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        # Not valid JSON, return truncated raw
        return line[:150] + "..." if len(line) > 150 else line

    msg_type = obj.get('type', 'unknown')

    # Handle tool_use (from assistant)
    if msg_type == 'assistant' and 'message' in obj:
        message = obj.get('message', {})
        content = message.get('content', [])

        # Look for tool_use in content
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get('type') == 'tool_use':
                tool_name = item.get('name', 'unknown')
                tool_input = item.get('input', {})

                # Extract brief description based on tool type
                if tool_name == 'Bash':
                    cmd = tool_input.get('command', '')[:60]
                    return f"[TOOL] Bash: {cmd}"
                elif tool_name in ('Read', 'Write', 'Edit'):
                    path = tool_input.get('file_path', '')
                    filename = path.split('/')[-1] if path else 'unknown'
                    return f"[TOOL] {tool_name}: {filename}"
                elif 'mcp__claude-orchestrator__' in tool_name:
                    short_name = tool_name.replace('mcp__claude-orchestrator__', '')
                    # Extract key param
                    if 'status' in tool_input:
                        return f"[MCP] {short_name}: {tool_input.get('status')} - {tool_input.get('message', '')[:50]}"
                    return f"[MCP] {short_name}"
                else:
                    return f"[TOOL] {tool_name}"

        # No tool_use, check for text
        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get('type') == 'text':
                text = item.get('text', '')[:100]
                return f"[ASST] {text}"

    # Handle tool_result (from user)
    if msg_type == 'user' and 'message' in obj:
        message = obj.get('message', {})
        content = message.get('content', [])

        for item in content if isinstance(content, list) else []:
            if isinstance(item, dict) and item.get('type') == 'tool_result':
                result = item.get('content', '')
                is_error = item.get('is_error', False)

                if is_error:
                    # Show full error
                    return f"[ERROR] {result[:150]}"
                else:
                    # Show brief result
                    result_preview = result[:80] if isinstance(result, str) else str(result)[:80]
                    return f"[RESULT] {result_preview}"

    # Handle progress updates (MCP responses)
    if 'progress' in str(obj) and 'status' in str(obj):
        return f"[PROGRESS] {obj.get('progress', 0)}% - {obj.get('message', '')[:60]}"

    # Handle errors
    if msg_type == 'error' or 'error' in obj:
        error = obj.get('error', obj.get('message', 'Unknown error'))
        return f"[ERROR] {error[:150]}"

    # Handle system messages
    if msg_type == 'system':
        subtype = obj.get('subtype', '')
        return f"[SYS] {subtype}" if subtype else "[SYS] init"

    # Fallback: show type and first bit of content
    return f"[{msg_type.upper()}] (entry)"


def format_lines_compact(lines: List[str]) -> str:
    """
    Convert multiple JSONL lines to compact format.
    Returns newline-separated compact summaries.
    """
    compact_lines = []
    for line in lines:
        compact = format_line_compact(line.strip())
        if compact:
            compact_lines.append(compact)
    return '\n'.join(compact_lines)


# ============================================================================
# Export List
# ============================================================================

__all__ = [
    # Truncation limits
    'MAX_LINE_LENGTH',
    'MAX_TOOL_RESULT_CONTENT',
    'MAX_ASSISTANT_TEXT',
    'AGGRESSIVE_LINE_LENGTH',
    'AGGRESSIVE_TOOL_RESULT',
    # JSONL helpers
    'read_jsonl_lines',
    'tail_jsonl_efficient',
    'filter_lines_regex',
    'parse_jsonl_lines',
    'format_output_by_type',
    'collect_log_metadata',
    # Content analysis
    'detect_repetitive_content',
    'extract_critical_lines',
    'intelligent_sample_lines',
    'summarize_output',
    # Truncation functions
    'smart_preview_truncate',
    'line_based_truncate',
    'simple_truncate',
    'truncate_coordination_info',
    'detect_and_truncate_binary',
    'is_already_truncated',
    'truncate_json_structure',
    'safe_json_truncate',
    # Compact formatting
    'format_line_compact',
    'format_lines_compact',
]
