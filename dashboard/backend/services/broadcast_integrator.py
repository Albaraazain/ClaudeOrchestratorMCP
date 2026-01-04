"""
Integration module that connects file watchers and log streamers to WebSocket broadcasting.

This module bridges the gap between file system events and WebSocket clients,
ensuring that all relevant changes are broadcast to subscribed clients in real-time.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Set
from datetime import datetime, timezone
from pathlib import Path

from .watcher import WorkspaceWatcher, FileChange, FileType
from .log_streamer import LogStreamManager, LogEntry, LogEntryType

logger = logging.getLogger(__name__)


class BroadcastIntegrator:
    """
    Integrates file watching and log streaming with WebSocket broadcasting.

    Coordinates between:
    - File system watchers (for registry/progress/findings changes)
    - Log stream readers (for real-time log tailing)
    - WebSocket connection manager (for client broadcasting)
    """

    def __init__(
        self,
        workspace_path: str = ".agent-workspace",
        buffer_size: int = 1000,
        debounce_ms: int = 100
    ):
        """
        Initialize broadcast integrator.

        Args:
            workspace_path: Path to agent workspace
            buffer_size: Size of log buffers
            debounce_ms: Debounce delay for file events
        """
        self.workspace_path = Path(workspace_path).resolve()

        # Create watcher and stream manager
        self.watcher = WorkspaceWatcher(
            workspace_path=str(self.workspace_path),
            debounce_ms=debounce_ms
        )
        self.stream_manager = LogStreamManager(buffer_size=buffer_size)

        # WebSocket manager reference (set by main app)
        self.ws_manager = None

        # Track active streams
        self.active_streams: Dict[str, str] = {}  # agent_id -> stream_id

        # Stats
        self.stats = {
            "file_changes_broadcast": 0,
            "log_entries_broadcast": 0,
            "active_watchers": 0,
            "active_streams": 0
        }

        # Register file watcher callbacks
        self._setup_file_watchers()

    def set_websocket_manager(self, ws_manager):
        """
        Set the WebSocket connection manager.

        Args:
            ws_manager: WebSocket ConnectionManager instance
        """
        self.ws_manager = ws_manager
        logger.info("WebSocket manager connected to broadcast integrator")

    def _setup_file_watchers(self):
        """Register callbacks for different file types."""
        # Registry changes
        self.watcher.register_callback(
            FileType.REGISTRY,
            self._handle_registry_change
        )

        # Progress updates
        self.watcher.register_callback(
            FileType.PROGRESS,
            self._handle_progress_change
        )

        # Finding reports
        self.watcher.register_callback(
            FileType.FINDINGS,
            self._handle_findings_change
        )

        # Log file changes (for starting/stopping streams)
        self.watcher.register_callback(
            FileType.LOGS,
            self._handle_log_file_change
        )

    async def _handle_registry_change(self, change: FileChange):
        """
        Handle registry file changes.

        Args:
            change: File change event
        """
        if not self.ws_manager:
            return

        logger.debug(f"Registry change: {change.file_path}")

        # Determine event type
        if "AGENT_REGISTRY" in change.file_path:
            event_type = "task_update"
        else:
            event_type = "global_registry_update"

        # Parse registry data
        if change.data:
            # Broadcast to interested clients
            message = {
                "type": event_type,
                "task_id": change.task_id,
                "data": change.data,
                "timestamp": change.timestamp.isoformat()
            }

            # Send to subscribed clients
            if change.task_id:
                # Task-specific update
                await self._broadcast_to_task_subscribers(
                    change.task_id,
                    message
                )
            else:
                # Global update
                await self._broadcast_to_all(message)

            self.stats["file_changes_broadcast"] += 1

    async def _handle_progress_change(self, change: FileChange):
        """
        Handle progress file changes.

        Args:
            change: File change event
        """
        if not self.ws_manager:
            return

        logger.debug(f"Progress change: {change.file_path}")

        if change.data and "entries" in change.data:
            # Get latest progress entries
            for entry in change.data["entries"]:
                message = {
                    "type": "agent_progress",
                    "task_id": change.task_id,
                    "agent_id": change.agent_id,
                    "data": entry,
                    "timestamp": change.timestamp.isoformat()
                }

                # Broadcast to task subscribers
                if change.task_id:
                    await self._broadcast_to_task_subscribers(
                        change.task_id,
                        message
                    )

                # Also broadcast to agent-specific subscribers
                if change.agent_id:
                    await self._broadcast_to_agent_subscribers(
                        change.agent_id,
                        message
                    )

            self.stats["file_changes_broadcast"] += 1

    async def _handle_findings_change(self, change: FileChange):
        """
        Handle findings file changes.

        Args:
            change: File change event
        """
        if not self.ws_manager:
            return

        logger.debug(f"Findings change: {change.file_path}")

        if change.data and "entries" in change.data:
            # Get latest findings
            for entry in change.data["entries"]:
                message = {
                    "type": "agent_finding",
                    "task_id": change.task_id,
                    "agent_id": change.agent_id,
                    "data": entry,
                    "timestamp": change.timestamp.isoformat()
                }

                # Broadcast to subscribers
                if change.task_id:
                    await self._broadcast_to_task_subscribers(
                        change.task_id,
                        message
                    )

                if change.agent_id:
                    await self._broadcast_to_agent_subscribers(
                        change.agent_id,
                        message
                    )

            self.stats["file_changes_broadcast"] += 1

    async def _handle_log_file_change(self, change: FileChange):
        """
        Handle log file changes (start/stop streaming).

        Args:
            change: File change event
        """
        if change.event_type == "created" and change.agent_id:
            # New log file - start streaming
            await self.start_log_stream(
                change.agent_id,
                change.file_path,
                change.task_id
            )
        elif change.event_type == "deleted" and change.agent_id:
            # Log file removed - stop streaming
            await self.stop_log_stream(change.agent_id)

    async def start_log_stream(
        self,
        agent_id: str,
        log_path: str,
        task_id: Optional[str] = None
    ):
        """
        Start streaming a log file.

        Args:
            agent_id: Agent ID
            log_path: Path to log file
            task_id: Optional task ID
        """
        # Check if already streaming
        if agent_id in self.active_streams:
            logger.debug(f"Already streaming logs for agent: {agent_id}")
            return

        stream_id = f"stream_{agent_id}"

        # Add stream to manager
        await self.stream_manager.add_stream(
            stream_id,
            log_path,
            agent_id,
            task_id
        )

        # Subscribe to stream
        async def log_callback(entry: LogEntry):
            await self._handle_log_entry(entry)

        self.stream_manager.subscribe(stream_id, log_callback)

        # Track active stream
        self.active_streams[agent_id] = stream_id
        self.stats["active_streams"] = len(self.active_streams)

        logger.info(f"Started log stream for agent: {agent_id}")

    async def stop_log_stream(self, agent_id: str):
        """
        Stop streaming a log file.

        Args:
            agent_id: Agent ID
        """
        stream_id = self.active_streams.get(agent_id)
        if not stream_id:
            return

        # Remove stream
        await self.stream_manager.remove_stream(stream_id)

        # Remove tracking
        del self.active_streams[agent_id]
        self.stats["active_streams"] = len(self.active_streams)

        logger.info(f"Stopped log stream for agent: {agent_id}")

    async def _handle_log_entry(self, entry: LogEntry):
        """
        Handle a log entry from stream.

        Args:
            entry: Log entry
        """
        if not self.ws_manager:
            return

        # Format log entry for broadcasting
        message = {
            "type": "log_entry",
            "task_id": entry.task_id,
            "agent_id": entry.agent_id,
            "data": {
                "line_number": entry.line_number,
                "timestamp": entry.timestamp.isoformat(),
                "entry_type": entry.entry_type.value,
                "content": entry.content
            }
        }

        # Broadcast to subscribers
        if entry.agent_id:
            await self._broadcast_to_agent_subscribers(
                entry.agent_id,
                message
            )

        if entry.task_id:
            await self._broadcast_to_task_subscribers(
                entry.task_id,
                message
            )

        self.stats["log_entries_broadcast"] += 1

    async def _broadcast_to_all(self, message: Dict[str, Any]):
        """
        Broadcast message to all connected clients.

        Args:
            message: Message to broadcast
        """
        if self.ws_manager:
            await self.ws_manager.broadcast(json.dumps(message))

    async def _broadcast_to_task_subscribers(
        self,
        task_id: str,
        message: Dict[str, Any]
    ):
        """
        Broadcast message to task subscribers.

        Args:
            task_id: Task ID
            message: Message to broadcast
        """
        if self.ws_manager:
            # Get task subscribers
            subscribers = self.ws_manager.get_subscribers("task", task_id)

            # Send to each subscriber
            message_str = json.dumps(message)
            for connection_id in subscribers:
                await self.ws_manager.send_to_connection(
                    connection_id,
                    message_str
                )

    async def _broadcast_to_agent_subscribers(
        self,
        agent_id: str,
        message: Dict[str, Any]
    ):
        """
        Broadcast message to agent subscribers.

        Args:
            agent_id: Agent ID
            message: Message to broadcast
        """
        if self.ws_manager:
            # Get agent subscribers
            subscribers = self.ws_manager.get_subscribers("agent", agent_id)

            # Send to each subscriber
            message_str = json.dumps(message)
            for connection_id in subscribers:
                await self.ws_manager.send_to_connection(
                    connection_id,
                    message_str
                )

    def set_active_tasks(self, task_ids: List[str]):
        """
        Set active tasks to monitor.

        Args:
            task_ids: List of active task IDs
        """
        self.watcher.set_active_tasks(task_ids)
        logger.info(f"Monitoring {len(task_ids)} active tasks")

    async def start(self):
        """Start the broadcast integrator."""
        # Start file watcher
        self.watcher.start()
        self.stats["active_watchers"] = 1

        # Auto-discover existing log files
        await self._discover_existing_logs()

        logger.info("Broadcast integrator started")

    async def stop(self):
        """Stop the broadcast integrator."""
        # Stop all log streams
        for agent_id in list(self.active_streams.keys()):
            await self.stop_log_stream(agent_id)

        # Stop file watcher
        self.watcher.stop()
        self.stats["active_watchers"] = 0

        logger.info("Broadcast integrator stopped")

    async def _discover_existing_logs(self):
        """Discover and start streaming existing log files."""
        # Find all log files in workspace
        log_pattern = "**/*.stream-json"
        log_files = list(self.workspace_path.glob(log_pattern))

        # Also check for .jsonl logs
        jsonl_pattern = "**/*_stream.jsonl"
        log_files.extend(self.workspace_path.glob(jsonl_pattern))

        for log_file in log_files:
            # Extract IDs from path
            parts = log_file.parts
            task_id = None
            agent_id = None

            for part in parts:
                if part.startswith("TASK-"):
                    task_id = part
                    break

            # Extract agent ID from filename
            stem = log_file.stem
            if "_stream" in stem:
                agent_id = stem.replace("_stream", "")
            elif stem.endswith("-stream"):
                agent_id = stem.replace("-stream", "")
            else:
                agent_id = stem

            if agent_id and not agent_id in self.active_streams:
                await self.start_log_stream(
                    agent_id,
                    str(log_file),
                    task_id
                )

        logger.info(f"Discovered {len(self.active_streams)} existing log streams")

    def get_stats(self) -> Dict[str, Any]:
        """Get integrator statistics."""
        return {
            **self.stats,
            "watcher_stats": self.watcher.get_stats(),
            "stream_manager_stats": self.stream_manager.get_stats()
        }

    def get_log_buffer(self, agent_id: str):
        """
        Get log buffer for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            Log buffer or None
        """
        stream_id = self.active_streams.get(agent_id)
        if stream_id:
            return self.stream_manager.get_buffer(stream_id)
        return None


# Example usage
async def main():
    """Example usage of broadcast integrator."""
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Create integrator
    workspace = sys.argv[1] if len(sys.argv) > 1 else ".agent-workspace"
    integrator = BroadcastIntegrator(workspace_path=workspace)

    # Mock WebSocket manager for testing
    class MockWSManager:
        async def broadcast(self, message):
            print(f"Broadcast: {message[:100]}...")

        def get_subscribers(self, target_type, target_id):
            return []

        async def send_to_connection(self, conn_id, message):
            pass

    integrator.set_websocket_manager(MockWSManager())

    # Start integrator
    await integrator.start()

    try:
        # Run for a while
        print(f"Monitoring {workspace}... Press Ctrl+C to stop")
        while True:
            await asyncio.sleep(10)
            stats = integrator.get_stats()
            print(f"Stats: {json.dumps(stats, indent=2)}")
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        await integrator.stop()


if __name__ == "__main__":
    asyncio.run(main())