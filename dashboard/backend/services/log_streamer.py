"""
Log streaming service for tailing and parsing JSONL log files.

Provides real-time streaming of agent logs with:
- Tail functionality for new log entries
- JSONL parsing with error recovery
- Buffering for reconnection recovery
- Multiple subscriber support
- Log rotation handling
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Set
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class LogEntryType(Enum):
    """Types of log entries in agent stream files."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class LogEntry:
    """Represents a single log entry from a JSONL file."""
    line_number: int
    timestamp: datetime
    entry_type: LogEntryType
    content: Dict[str, Any]
    raw_line: str
    file_path: str
    agent_id: Optional[str] = None
    task_id: Optional[str] = None


@dataclass
class StreamPosition:
    """Tracks position in a log stream."""
    file_path: str
    line_number: int = 0
    byte_offset: int = 0
    last_read: Optional[datetime] = None


class LogBuffer:
    """
    Circular buffer for storing recent log entries.

    Used for reconnection recovery - clients can request
    logs from a specific position.
    """

    def __init__(self, max_size: int = 1000):
        """
        Initialize log buffer.

        Args:
            max_size: Maximum number of entries to buffer
        """
        self.max_size = max_size
        self.buffer: deque = deque(maxlen=max_size)
        self.total_entries = 0

    def add(self, entry: LogEntry):
        """Add entry to buffer."""
        self.buffer.append(entry)
        self.total_entries += 1

    def get_since(self, line_number: int) -> List[LogEntry]:
        """
        Get entries since specified line number.

        Args:
            line_number: Line number to start from

        Returns:
            List of entries after the specified line
        """
        result = []
        for entry in self.buffer:
            if entry.line_number > line_number:
                result.append(entry)
        return result

    def get_latest(self, count: int = 100) -> List[LogEntry]:
        """
        Get latest N entries.

        Args:
            count: Number of entries to return

        Returns:
            Latest entries (up to count)
        """
        if count >= len(self.buffer):
            return list(self.buffer)
        return list(self.buffer)[-count:]

    def clear(self):
        """Clear buffer."""
        self.buffer.clear()
        self.total_entries = 0

    def stats(self) -> Dict[str, Any]:
        """Get buffer statistics."""
        return {
            "current_size": len(self.buffer),
            "max_size": self.max_size,
            "total_entries": self.total_entries,
            "oldest_line": self.buffer[0].line_number if self.buffer else None,
            "newest_line": self.buffer[-1].line_number if self.buffer else None
        }


class LogStreamReader:
    """
    Reads and tails a single JSONL log file.

    Handles:
    - Initial file reading
    - Tailing for new entries
    - JSONL parsing with error recovery
    - File rotation detection
    """

    def __init__(
        self,
        file_path: str,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None
    ):
        """
        Initialize log stream reader.

        Args:
            file_path: Path to JSONL log file
            agent_id: Agent ID for this log
            task_id: Task ID for this log
        """
        self.file_path = Path(file_path)
        self.agent_id = agent_id
        self.task_id = task_id

        # Current position
        self.position = StreamPosition(file_path=str(file_path))

        # File handle
        self.file_handle = None
        self.file_inode = None

        # Stats
        self.stats = {
            "lines_read": 0,
            "parse_errors": 0,
            "last_read": None
        }

    def _classify_entry(self, data: Dict[str, Any]) -> LogEntryType:
        """Classify log entry type based on content."""
        if "type" in data:
            type_val = data["type"]
            if type_val == "system":
                return LogEntryType.SYSTEM
            elif type_val == "user":
                return LogEntryType.USER
            elif type_val == "assistant":
                return LogEntryType.ASSISTANT
            elif type_val == "tool_call":
                return LogEntryType.TOOL_CALL
            elif type_val == "tool_result":
                return LogEntryType.TOOL_RESULT
            elif type_val == "error":
                return LogEntryType.ERROR

        return LogEntryType.UNKNOWN

    def _parse_line(self, line: str, line_number: int) -> Optional[LogEntry]:
        """
        Parse a single JSONL line into LogEntry.

        Args:
            line: Raw line from file
            line_number: Line number in file

        Returns:
            Parsed LogEntry or None if parse fails
        """
        line = line.strip()
        if not line:
            return None

        try:
            # Parse JSON
            data = json.loads(line)

            # Extract timestamp (try multiple formats)
            timestamp = None
            for ts_field in ["timestamp", "created_at", "time"]:
                if ts_field in data:
                    try:
                        timestamp = datetime.fromisoformat(data[ts_field])
                        break
                    except:
                        pass

            if not timestamp:
                timestamp = datetime.now(timezone.utc)

            # Create entry
            entry = LogEntry(
                line_number=line_number,
                timestamp=timestamp,
                entry_type=self._classify_entry(data),
                content=data,
                raw_line=line,
                file_path=str(self.file_path),
                agent_id=self.agent_id,
                task_id=self.task_id
            )

            return entry

        except json.JSONDecodeError as e:
            self.stats["parse_errors"] += 1
            logger.debug(f"Failed to parse line {line_number}: {e}")
            return None

    async def open(self):
        """Open log file for reading."""
        try:
            self.file_handle = open(self.file_path, "r")

            # Get file inode for rotation detection
            stat = os.fstat(self.file_handle.fileno())
            self.file_inode = stat.st_ino

            logger.debug(f"Opened log file: {self.file_path}")

        except FileNotFoundError:
            logger.warning(f"Log file not found: {self.file_path}")
            raise
        except Exception as e:
            logger.error(f"Error opening log file: {e}")
            raise

    async def close(self):
        """Close log file."""
        if self.file_handle:
            self.file_handle.close()
            self.file_handle = None
            logger.debug(f"Closed log file: {self.file_path}")

    async def read_all(self) -> List[LogEntry]:
        """
        Read all entries from the beginning of the file.

        Returns:
            List of all log entries
        """
        if not self.file_handle:
            await self.open()

        # Seek to beginning
        self.file_handle.seek(0)
        self.position.byte_offset = 0
        self.position.line_number = 0

        entries = []
        for line in self.file_handle:
            self.position.line_number += 1
            entry = self._parse_line(line, self.position.line_number)
            if entry:
                entries.append(entry)
                self.stats["lines_read"] += 1

        self.position.byte_offset = self.file_handle.tell()
        self.position.last_read = datetime.now(timezone.utc)
        self.stats["last_read"] = self.position.last_read

        return entries

    async def tail(self) -> AsyncIterator[LogEntry]:
        """
        Tail log file for new entries.

        Yields:
            New log entries as they appear
        """
        if not self.file_handle:
            await self.open()

        # Seek to saved position
        if self.position.byte_offset > 0:
            self.file_handle.seek(self.position.byte_offset)

        while True:
            # Check for file rotation
            if await self._check_rotation():
                # Reopen file from beginning
                await self.close()
                await self.open()
                self.position.byte_offset = 0
                self.position.line_number = 0

            # Read new lines
            line = self.file_handle.readline()

            if line:
                self.position.line_number += 1
                entry = self._parse_line(line, self.position.line_number)
                if entry:
                    self.stats["lines_read"] += 1
                    yield entry

                self.position.byte_offset = self.file_handle.tell()
                self.position.last_read = datetime.now(timezone.utc)
                self.stats["last_read"] = self.position.last_read
            else:
                # No new data, sleep briefly
                await asyncio.sleep(0.1)

    async def _check_rotation(self) -> bool:
        """
        Check if log file has been rotated.

        Returns:
            True if file was rotated
        """
        if not self.file_handle:
            return False

        try:
            # Check if file still exists
            if not self.file_path.exists():
                return True

            # Check inode
            stat = self.file_path.stat()
            if stat.st_ino != self.file_inode:
                logger.info(f"Log file rotated: {self.file_path}")
                return True

            # Check if file shrunk (truncated)
            if stat.st_size < self.position.byte_offset:
                logger.info(f"Log file truncated: {self.file_path}")
                return True

        except Exception as e:
            logger.error(f"Error checking rotation: {e}")

        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get reader statistics."""
        return {
            **self.stats,
            "file_path": str(self.file_path),
            "position": {
                "line": self.position.line_number,
                "bytes": self.position.byte_offset
            },
            "is_open": self.file_handle is not None
        }


class LogStreamManager:
    """
    Manages multiple log streams and subscribers.

    Coordinates streaming from multiple log files to
    multiple subscribers with buffering and recovery.
    """

    def __init__(self, buffer_size: int = 1000):
        """
        Initialize log stream manager.

        Args:
            buffer_size: Size of buffer per stream
        """
        self.buffer_size = buffer_size

        # Active streams
        self.streams: Dict[str, LogStreamReader] = {}
        self.buffers: Dict[str, LogBuffer] = {}
        self.tasks: Dict[str, asyncio.Task] = {}

        # Subscribers
        self.subscribers: Dict[str, Set[Callable]] = {}

        # Stats
        self.stats = {
            "active_streams": 0,
            "total_subscribers": 0,
            "total_entries_streamed": 0
        }

    async def add_stream(
        self,
        stream_id: str,
        file_path: str,
        agent_id: Optional[str] = None,
        task_id: Optional[str] = None
    ):
        """
        Add a new log stream to monitor.

        Args:
            stream_id: Unique ID for this stream
            file_path: Path to log file
            agent_id: Optional agent ID
            task_id: Optional task ID
        """
        if stream_id in self.streams:
            logger.warning(f"Stream already exists: {stream_id}")
            return

        # Create reader and buffer
        reader = LogStreamReader(file_path, agent_id, task_id)
        buffer = LogBuffer(self.buffer_size)

        self.streams[stream_id] = reader
        self.buffers[stream_id] = buffer
        self.subscribers[stream_id] = set()

        # Start tailing task
        task = asyncio.create_task(self._tail_stream(stream_id))
        self.tasks[stream_id] = task

        self.stats["active_streams"] += 1
        logger.info(f"Added stream: {stream_id} -> {file_path}")

    async def remove_stream(self, stream_id: str):
        """
        Remove a log stream.

        Args:
            stream_id: ID of stream to remove
        """
        if stream_id not in self.streams:
            return

        # Cancel task
        if stream_id in self.tasks:
            self.tasks[stream_id].cancel()
            try:
                await self.tasks[stream_id]
            except asyncio.CancelledError:
                pass
            del self.tasks[stream_id]

        # Close reader
        await self.streams[stream_id].close()
        del self.streams[stream_id]

        # Clear buffer
        del self.buffers[stream_id]

        # Clear subscribers
        del self.subscribers[stream_id]

        self.stats["active_streams"] -= 1
        logger.info(f"Removed stream: {stream_id}")

    async def _tail_stream(self, stream_id: str):
        """
        Tail a stream and broadcast entries.

        Args:
            stream_id: ID of stream to tail
        """
        reader = self.streams[stream_id]
        buffer = self.buffers[stream_id]

        try:
            # Read existing entries first
            entries = await reader.read_all()
            for entry in entries:
                buffer.add(entry)
                await self._broadcast_entry(stream_id, entry)

            # Then tail for new entries
            async for entry in reader.tail():
                buffer.add(entry)
                await self._broadcast_entry(stream_id, entry)
                self.stats["total_entries_streamed"] += 1

        except asyncio.CancelledError:
            logger.debug(f"Stream tailing cancelled: {stream_id}")
            raise
        except Exception as e:
            logger.error(f"Error tailing stream {stream_id}: {e}")

    async def _broadcast_entry(self, stream_id: str, entry: LogEntry):
        """
        Broadcast log entry to subscribers.

        Args:
            stream_id: Stream ID
            entry: Log entry to broadcast
        """
        subscribers = self.subscribers.get(stream_id, set()).copy()

        for subscriber in subscribers:
            try:
                if asyncio.iscoroutinefunction(subscriber):
                    await subscriber(entry)
                else:
                    subscriber(entry)
            except Exception as e:
                logger.error(f"Error in subscriber callback: {e}")

    def subscribe(
        self,
        stream_id: str,
        callback: Callable[[LogEntry], None]
    ) -> bool:
        """
        Subscribe to log stream.

        Args:
            stream_id: Stream to subscribe to
            callback: Function to call with new entries

        Returns:
            True if subscribed successfully
        """
        if stream_id not in self.streams:
            logger.warning(f"Stream not found: {stream_id}")
            return False

        self.subscribers[stream_id].add(callback)
        self.stats["total_subscribers"] = sum(
            len(subs) for subs in self.subscribers.values()
        )

        logger.debug(f"Added subscriber to stream: {stream_id}")
        return True

    def unsubscribe(
        self,
        stream_id: str,
        callback: Callable[[LogEntry], None]
    ):
        """
        Unsubscribe from log stream.

        Args:
            stream_id: Stream to unsubscribe from
            callback: Callback to remove
        """
        if stream_id in self.subscribers:
            self.subscribers[stream_id].discard(callback)
            self.stats["total_subscribers"] = sum(
                len(subs) for subs in self.subscribers.values()
            )

    def get_buffer(self, stream_id: str) -> Optional[LogBuffer]:
        """
        Get buffer for stream.

        Args:
            stream_id: Stream ID

        Returns:
            Log buffer or None
        """
        return self.buffers.get(stream_id)

    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics."""
        stream_stats = {}
        for sid, reader in self.streams.items():
            stream_stats[sid] = {
                "reader": reader.get_stats(),
                "buffer": self.buffers[sid].stats(),
                "subscribers": len(self.subscribers.get(sid, set()))
            }

        return {
            **self.stats,
            "streams": stream_stats
        }


# Example usage
async def example_subscriber(entry: LogEntry):
    """Example subscriber callback."""
    print(f"[{entry.timestamp}] {entry.entry_type.value}: ", end="")
    if entry.entry_type == LogEntryType.TOOL_CALL:
        print(f"Tool: {entry.content.get('tool_name', 'unknown')}")
    elif entry.entry_type in (LogEntryType.USER, LogEntryType.ASSISTANT):
        content = entry.content.get("content", "")
        print(content[:100] + "..." if len(content) > 100 else content)
    else:
        print(f"{list(entry.content.keys())}")


if __name__ == "__main__":
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    async def main():
        # Get log file from args
        if len(sys.argv) < 2:
            print("Usage: python log_streamer.py <log_file>")
            sys.exit(1)

        log_file = sys.argv[1]

        # Create manager
        manager = LogStreamManager()

        # Add stream
        await manager.add_stream("test_stream", log_file)

        # Subscribe
        manager.subscribe("test_stream", example_subscriber)

        try:
            # Run for a while
            print(f"Streaming {log_file}... Press Ctrl+C to stop")
            while True:
                await asyncio.sleep(10)
                stats = manager.get_stats()
                print(f"\nStats: {json.dumps(stats, indent=2, default=str)}\n")
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            await manager.remove_stream("test_stream")

    # Run
    asyncio.run(main())