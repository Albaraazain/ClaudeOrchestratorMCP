"""
File system watcher service for monitoring orchestrator data changes.

Monitors .agent-workspace/ directory for changes to:
- AGENT_REGISTRY.json files (task/agent status)
- progress/*.jsonl files (agent progress updates)
- findings/*.jsonl files (agent discoveries)
- logs/*.stream-json files (agent logs)

Uses watchdog library with debouncing to prevent event floods.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

# Watchdog library for file system monitoring
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileSystemEvent
except ImportError:
    # Fallback for development - will need watchdog installed for production
    Observer = None
    FileSystemEventHandler = object
    FileSystemEvent = None
    print("WARNING: watchdog not installed. File watching disabled.")

logger = logging.getLogger(__name__)


class FileType(Enum):
    """Types of files we monitor."""
    REGISTRY = "registry"
    PROGRESS = "progress"
    FINDINGS = "findings"
    LOGS = "logs"
    UNKNOWN = "unknown"


@dataclass
class FileChange:
    """Represents a detected file change."""
    file_path: str
    file_type: FileType
    task_id: Optional[str]
    agent_id: Optional[str]
    event_type: str  # 'created', 'modified', 'deleted'
    timestamp: datetime
    data: Optional[Dict[str, Any]] = None


class DebouncedEventHandler(FileSystemEventHandler):
    """
    Watchdog event handler with debouncing to prevent event floods.

    Groups rapid changes to the same file and only triggers callback
    after a quiet period (default 100ms).
    """

    def __init__(
        self,
        callback: Callable[[FileChange], None],
        debounce_ms: int = 100,
        loop: Optional[asyncio.AbstractEventLoop] = None
    ):
        """
        Initialize debounced event handler.

        Args:
            callback: Function to call with file changes
            debounce_ms: Milliseconds to wait before triggering callback
            loop: Event loop for async callbacks
        """
        super().__init__()
        self.callback = callback
        self.debounce_ms = debounce_ms
        self.loop = loop or asyncio.get_event_loop()

        # Track pending events per file
        self.pending_events: Dict[str, asyncio.TimerHandle] = {}
        self.event_queue: Dict[str, FileChange] = {}

        # File type patterns
        self.patterns = {
            FileType.REGISTRY: ["AGENT_REGISTRY.json", "GLOBAL_REGISTRY.json"],
            FileType.PROGRESS: ["*_progress.jsonl"],
            FileType.FINDINGS: ["*_findings.jsonl"],
            FileType.LOGS: ["*_stream.jsonl", "*.stream-json"]
        }

    def _classify_file(self, file_path: str) -> FileType:
        """Classify file type based on path patterns."""
        path_obj = Path(file_path)
        filename = path_obj.name

        # Check patterns
        if filename in self.patterns[FileType.REGISTRY]:
            return FileType.REGISTRY
        elif filename.endswith("_progress.jsonl"):
            return FileType.PROGRESS
        elif filename.endswith("_findings.jsonl"):
            return FileType.FINDINGS
        elif filename.endswith((".stream-json", "_stream.jsonl")):
            return FileType.LOGS

        return FileType.UNKNOWN

    def _extract_ids(self, file_path: str) -> tuple[Optional[str], Optional[str]]:
        """Extract task_id and agent_id from file path."""
        path_obj = Path(file_path)
        parts = path_obj.parts

        task_id = None
        agent_id = None

        # Look for TASK-* directory
        for part in parts:
            if part.startswith("TASK-"):
                task_id = part
                break

        # Extract agent_id from filename (e.g., agent_name-123456-abcdef_progress.jsonl)
        filename = path_obj.stem  # Remove extension
        if "_" in filename:
            # Remove suffix like _progress, _findings, _stream
            agent_id = filename.rsplit("_", 1)[0]

        return task_id, agent_id

    def _schedule_callback(self, file_path: str, change: FileChange):
        """Schedule debounced callback for file change."""
        # Cancel pending event if exists
        if file_path in self.pending_events:
            self.pending_events[file_path].cancel()

        # Store latest change
        self.event_queue[file_path] = change

        # Schedule new callback
        def trigger():
            if file_path in self.event_queue:
                change = self.event_queue.pop(file_path)
                self.pending_events.pop(file_path, None)

                # Call callback in event loop
                if asyncio.iscoroutinefunction(self.callback):
                    asyncio.create_task(self.callback(change))
                else:
                    self.callback(change)

        # Schedule with debounce delay
        delay = self.debounce_ms / 1000.0
        handle = self.loop.call_later(delay, trigger)
        self.pending_events[file_path] = handle

    def on_created(self, event):
        """Handle file creation events."""
        if event.is_directory:
            return

        self._handle_event(event, "created")

    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return

        self._handle_event(event, "modified")

    def on_deleted(self, event):
        """Handle file deletion events."""
        if event.is_directory:
            return

        self._handle_event(event, "deleted")

    def _handle_event(self, event, event_type: str):
        """Process file system event."""
        file_path = event.src_path

        # Classify file type
        file_type = self._classify_file(file_path)
        if file_type == FileType.UNKNOWN:
            return  # Ignore unknown files

        # Extract IDs
        task_id, agent_id = self._extract_ids(file_path)

        # Create change object
        change = FileChange(
            file_path=file_path,
            file_type=file_type,
            task_id=task_id,
            agent_id=agent_id,
            event_type=event_type,
            timestamp=datetime.now(timezone.utc)
        )

        # Schedule debounced callback
        self._schedule_callback(file_path, change)

        logger.debug(f"File {event_type}: {file_path} (type={file_type}, task={task_id}, agent={agent_id})")


class WorkspaceWatcher:
    """
    Main file watcher service for monitoring orchestrator workspace.

    Provides high-level API for watching workspace changes and
    triggering callbacks when files are modified.
    """

    def __init__(
        self,
        workspace_path: str = ".agent-workspace",
        debounce_ms: int = 100
    ):
        """
        Initialize workspace watcher.

        Args:
            workspace_path: Path to agent workspace directory
            debounce_ms: Milliseconds to debounce file events
        """
        self.workspace_path = Path(workspace_path).resolve()
        self.debounce_ms = debounce_ms

        # Watchdog observer
        self.observer: Optional[Observer] = None

        # Registered callbacks by file type
        self.callbacks: Dict[FileType, List[Callable]] = defaultdict(list)

        # Track active tasks for filtering
        self.active_tasks: Set[str] = set()

        # Stats
        self.stats = {
            "events_received": 0,
            "events_processed": 0,
            "events_debounced": 0,
            "last_event": None
        }

    def register_callback(
        self,
        file_type: FileType,
        callback: Callable[[FileChange], None]
    ):
        """
        Register callback for specific file type changes.

        Args:
            file_type: Type of files to watch
            callback: Function to call with changes
        """
        self.callbacks[file_type].append(callback)
        logger.info(f"Registered callback for {file_type.value} files")

    def set_active_tasks(self, task_ids: List[str]):
        """
        Set list of active tasks to monitor.

        Only changes to these tasks will trigger callbacks.
        This helps reduce noise from old/completed tasks.

        Args:
            task_ids: List of active task IDs
        """
        self.active_tasks = set(task_ids)
        logger.info(f"Monitoring {len(task_ids)} active tasks")

    async def _handle_change(self, change: FileChange):
        """
        Handle detected file change.

        Args:
            change: File change details
        """
        self.stats["events_received"] += 1

        # Filter by active tasks if configured
        if self.active_tasks and change.task_id:
            if change.task_id not in self.active_tasks:
                logger.debug(f"Ignoring change to inactive task: {change.task_id}")
                return

        # Load file data for certain types
        if change.event_type != "deleted":
            try:
                change.data = await self._read_file_data(change)
            except Exception as e:
                logger.error(f"Error reading file {change.file_path}: {e}")

        # Call registered callbacks
        for callback in self.callbacks.get(change.file_type, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(change)
                else:
                    callback(change)
            except Exception as e:
                logger.error(f"Error in callback for {change.file_type}: {e}")

        self.stats["events_processed"] += 1
        self.stats["last_event"] = change.timestamp

    async def _read_file_data(self, change: FileChange) -> Optional[Dict]:
        """
        Read and parse file data based on type.

        Args:
            change: File change details

        Returns:
            Parsed file data or None
        """
        try:
            path = Path(change.file_path)

            if change.file_type == FileType.REGISTRY:
                # Read full JSON file
                with open(path, "r") as f:
                    return json.load(f)

            elif change.file_type in (FileType.PROGRESS, FileType.FINDINGS, FileType.LOGS):
                # Read last N lines from JSONL
                lines = []
                with open(path, "r") as f:
                    # Read last 10 lines for efficiency
                    for line in f:
                        lines.append(line)
                        if len(lines) > 10:
                            lines.pop(0)

                # Parse JSONL lines
                entries = []
                for line in lines:
                    if line.strip():
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

                return {"entries": entries, "total_lines": len(lines)}

        except Exception as e:
            logger.error(f"Error reading file {change.file_path}: {e}")
            return None

    def start(self):
        """Start watching workspace directory."""
        if Observer is None:
            logger.error("watchdog library not installed. Cannot start file watching.")
            return

        if not self.workspace_path.exists():
            logger.warning(f"Workspace path does not exist: {self.workspace_path}")
            self.workspace_path.mkdir(parents=True, exist_ok=True)

        # Create observer
        self.observer = Observer()

        # Create event handler
        handler = DebouncedEventHandler(
            callback=lambda change: asyncio.create_task(self._handle_change(change)),
            debounce_ms=self.debounce_ms
        )

        # Schedule observer
        self.observer.schedule(
            handler,
            str(self.workspace_path),
            recursive=True
        )

        # Start observer thread
        self.observer.start()
        logger.info(f"Started watching: {self.workspace_path}")

    def stop(self):
        """Stop watching workspace directory."""
        if self.observer and self.observer.is_alive():
            self.observer.stop()
            self.observer.join(timeout=5)
            logger.info("Stopped file watching")

    def get_stats(self) -> Dict[str, Any]:
        """Get watcher statistics."""
        return {
            **self.stats,
            "is_running": self.observer.is_alive() if self.observer else False,
            "workspace_path": str(self.workspace_path),
            "active_tasks": len(self.active_tasks),
            "registered_callbacks": {
                ft.value: len(cbs) for ft, cbs in self.callbacks.items()
            }
        }


# Example usage and testing
async def example_callback(change: FileChange):
    """Example callback for file changes."""
    print(f"File changed: {change.file_path}")
    print(f"  Type: {change.file_type.value}")
    print(f"  Task: {change.task_id}")
    print(f"  Agent: {change.agent_id}")
    print(f"  Event: {change.event_type}")
    if change.data:
        print(f"  Data keys: {list(change.data.keys())}")


if __name__ == "__main__":
    # Test the watcher
    import sys

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    async def main():
        # Create watcher
        workspace = sys.argv[1] if len(sys.argv) > 1 else ".agent-workspace"
        watcher = WorkspaceWatcher(workspace_path=workspace)

        # Register callbacks
        watcher.register_callback(FileType.REGISTRY, example_callback)
        watcher.register_callback(FileType.PROGRESS, example_callback)
        watcher.register_callback(FileType.FINDINGS, example_callback)

        # Start watching
        watcher.start()

        try:
            # Run for a while
            print(f"Watching {workspace}... Press Ctrl+C to stop")
            while True:
                await asyncio.sleep(10)
                stats = watcher.get_stats()
                print(f"Stats: {stats}")
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            watcher.stop()

    # Run
    asyncio.run(main())