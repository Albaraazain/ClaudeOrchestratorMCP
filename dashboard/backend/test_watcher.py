#!/usr/bin/env python3
"""
Test script for file watching services.

Run this to verify that file watchers and log streamers are working correctly.
"""

import asyncio
import json
import logging
from pathlib import Path

# Add parent directory to path
import sys
sys.path.append(str(Path(__file__).parent))

from services.watcher import WorkspaceWatcher, FileChange, FileType
from services.log_streamer import LogStreamManager, LogEntry
from services.broadcast_integrator import BroadcastIntegrator


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


async def test_file_watcher():
    """Test file watching functionality."""
    print("\n=== Testing File Watcher ===\n")

    # Create watcher
    watcher = WorkspaceWatcher(workspace_path=".agent-workspace")

    # Track changes
    changes = []

    async def change_callback(change: FileChange):
        changes.append(change)
        print(f"File {change.event_type}: {Path(change.file_path).name}")
        print(f"  Type: {change.file_type.value}")
        print(f"  Task: {change.task_id}")
        print(f"  Agent: {change.agent_id}")

    # Register callbacks
    watcher.register_callback(FileType.REGISTRY, change_callback)
    watcher.register_callback(FileType.PROGRESS, change_callback)
    watcher.register_callback(FileType.FINDINGS, change_callback)

    # Start watching
    watcher.start()

    print("Watching for changes... (10 seconds)")
    await asyncio.sleep(10)

    # Stop watching
    watcher.stop()

    # Print stats
    stats = watcher.get_stats()
    print(f"\nWatcher Stats:")
    print(f"  Events received: {stats['events_received']}")
    print(f"  Events processed: {stats['events_processed']}")
    print(f"  Total changes detected: {len(changes)}")


async def test_log_streamer():
    """Test log streaming functionality."""
    print("\n=== Testing Log Streamer ===\n")

    # Find a log file
    workspace = Path(".agent-workspace")
    log_files = list(workspace.glob("**/logs/*.stream-json"))
    log_files.extend(workspace.glob("**/logs/*_stream.jsonl"))

    if not log_files:
        print("No log files found to test")
        return

    # Use first log file
    log_file = log_files[0]
    print(f"Testing with log file: {log_file}")

    # Create stream manager
    manager = LogStreamManager()

    # Track entries
    entries = []

    async def entry_callback(entry: LogEntry):
        entries.append(entry)
        print(f"[{entry.timestamp.strftime('%H:%M:%S')}] {entry.entry_type.value}: ", end="")

        # Print summary based on type
        if entry.entry_type.value == "tool_call":
            print(f"{entry.content.get('tool_name', 'unknown')}")
        elif entry.entry_type.value in ("user", "assistant"):
            content = entry.content.get("content", "")
            print(content[:80] + "..." if len(content) > 80 else content)
        else:
            print(f"{list(entry.content.keys())}")

    # Add stream
    await manager.add_stream("test_stream", str(log_file))

    # Subscribe
    manager.subscribe("test_stream", entry_callback)

    print(f"Streaming for 5 seconds...")
    await asyncio.sleep(5)

    # Get buffer
    buffer = manager.get_buffer("test_stream")
    if buffer:
        buffer_stats = buffer.stats()
        print(f"\nBuffer Stats:")
        print(f"  Current size: {buffer_stats['current_size']}")
        print(f"  Total entries: {buffer_stats['total_entries']}")

    # Remove stream
    await manager.remove_stream("test_stream")

    print(f"\nTotal entries streamed: {len(entries)}")


async def test_broadcast_integrator():
    """Test broadcast integrator."""
    print("\n=== Testing Broadcast Integrator ===\n")

    # Create integrator
    integrator = BroadcastIntegrator()

    # Mock WebSocket manager
    class MockWSManager:
        def __init__(self):
            self.messages = []

        async def broadcast(self, message):
            msg_data = json.loads(message)
            self.messages.append(msg_data)
            print(f"Broadcast: {msg_data.get('type', 'unknown')}")

        def get_subscribers(self, target_type, target_id):
            return []

        async def send_to_connection(self, conn_id, message):
            pass

    ws_manager = MockWSManager()
    integrator.set_websocket_manager(ws_manager)

    # Start integrator
    await integrator.start()

    print("Monitoring for 10 seconds...")
    await asyncio.sleep(10)

    # Stop integrator
    await integrator.stop()

    # Print stats
    stats = integrator.get_stats()
    print(f"\nIntegrator Stats:")
    print(f"  File changes broadcast: {stats['file_changes_broadcast']}")
    print(f"  Log entries broadcast: {stats['log_entries_broadcast']}")
    print(f"  Active streams: {stats['active_streams']}")
    print(f"  Messages broadcast: {len(ws_manager.messages)}")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("File Watching Services Test")
    print("=" * 60)

    try:
        # Test individual components
        await test_file_watcher()
        await test_log_streamer()
        await test_broadcast_integrator()

        print("\n" + "=" * 60)
        print("All tests completed!")
        print("=" * 60)

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())