"""WebSocket connection manager for real-time updates."""

from typing import Dict, List, Set
from datetime import datetime
from fastapi import WebSocket
import json


class ConnectionManager:
    """Manage WebSocket connections and subscriptions."""

    def __init__(self):
        """Initialize connection manager."""
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[str, Set[WebSocket]] = {}
        self.connection_metadata: Dict[WebSocket, Dict] = {}

    async def connect(self, websocket: WebSocket):
        """Accept and track a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        self.connection_metadata[websocket] = {
            "connected_at": datetime.now(),
            "subscriptions": set()
        }
        print(f"[WebSocket] New connection. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection and its subscriptions."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

        # Remove from all subscriptions
        for topic, connections in self.subscriptions.items():
            if websocket in connections:
                connections.remove(websocket)

        # Clean up metadata
        if websocket in self.connection_metadata:
            del self.connection_metadata[websocket]

        print(f"[WebSocket] Connection closed. Total: {len(self.active_connections)}")

    async def disconnect_all(self):
        """Disconnect all active connections."""
        for connection in self.active_connections[:]:
            try:
                await connection.close()
            except:
                pass
            self.disconnect(connection)

    async def subscribe(self, websocket: WebSocket, target: str, id: str):
        """Subscribe a connection to a specific target."""
        topic = f"{target}:{id}"
        if topic not in self.subscriptions:
            self.subscriptions[topic] = set()

        self.subscriptions[topic].add(websocket)

        if websocket in self.connection_metadata:
            self.connection_metadata[websocket]["subscriptions"].add(topic)

        await websocket.send_json({
            "type": "subscribed",
            "target": target,
            "id": id,
            "timestamp": datetime.now().isoformat()
        })

        print(f"[WebSocket] Subscribed to {topic}")

    async def unsubscribe(self, websocket: WebSocket, target: str, id: str):
        """Unsubscribe a connection from a specific target."""
        topic = f"{target}:{id}"

        if topic in self.subscriptions and websocket in self.subscriptions[topic]:
            self.subscriptions[topic].remove(websocket)

            if not self.subscriptions[topic]:
                del self.subscriptions[topic]

        if websocket in self.connection_metadata:
            self.connection_metadata[websocket]["subscriptions"].discard(topic)

        await websocket.send_json({
            "type": "unsubscribed",
            "target": target,
            "id": id,
            "timestamp": datetime.now().isoformat()
        })

        print(f"[WebSocket] Unsubscribed from {topic}")

    async def broadcast_to_topic(self, topic: str, data: dict):
        """Broadcast a message to all connections subscribed to a topic."""
        if topic not in self.subscriptions:
            return

        disconnected = []
        for connection in self.subscriptions[topic]:
            try:
                await connection.send_json(data)
            except:
                disconnected.append(connection)

        # Clean up disconnected connections
        for connection in disconnected:
            self.disconnect(connection)

    async def broadcast_task_update(self, task_id: str, task_data: dict):
        """Broadcast task update to subscribed clients."""
        await self.broadcast_to_topic(
            f"task:{task_id}",
            {
                "type": "task_update",
                "task_id": task_id,
                "data": task_data,
                "timestamp": datetime.now().isoformat()
            }
        )

    async def broadcast_agent_update(self, task_id: str, agent_id: str, agent_data: dict):
        """Broadcast agent update to subscribed clients."""
        # Broadcast to agent-specific subscribers
        await self.broadcast_to_topic(
            f"agent:{agent_id}",
            {
                "type": "agent_update",
                "agent_id": agent_id,
                "task_id": task_id,
                "data": agent_data,
                "timestamp": datetime.now().isoformat()
            }
        )

        # Also broadcast to task subscribers
        await self.broadcast_to_topic(
            f"task:{task_id}",
            {
                "type": "agent_update",
                "agent_id": agent_id,
                "task_id": task_id,
                "data": agent_data,
                "timestamp": datetime.now().isoformat()
            }
        )

    async def broadcast_log_chunk(self, agent_id: str, content: str):
        """Broadcast log chunk to subscribed clients."""
        await self.broadcast_to_topic(
            f"logs:{agent_id}",
            {
                "type": "log_chunk",
                "agent_id": agent_id,
                "content": content,
                "timestamp": datetime.now().isoformat()
            }
        )

    async def broadcast_phase_change(self, task_id: str, phase_data: dict):
        """Broadcast phase change to subscribed clients."""
        await self.broadcast_to_topic(
            f"task:{task_id}",
            {
                "type": "phase_change",
                "task_id": task_id,
                "phase": phase_data,
                "timestamp": datetime.now().isoformat()
            }
        )

    async def broadcast_finding_reported(self, task_id: str, agent_id: str, finding: dict):
        """Broadcast finding report to subscribed clients."""
        # Broadcast to agent subscribers
        await self.broadcast_to_topic(
            f"agent:{agent_id}",
            {
                "type": "finding_reported",
                "agent_id": agent_id,
                "finding": finding,
                "timestamp": datetime.now().isoformat()
            }
        )

        # Also broadcast to task subscribers
        await self.broadcast_to_topic(
            f"task:{task_id}",
            {
                "type": "finding_reported",
                "agent_id": agent_id,
                "finding": finding,
                "timestamp": datetime.now().isoformat()
            }
        )

    async def broadcast_tmux_output(self, session_name: str, content: str):
        """Broadcast tmux output to subscribed clients."""
        await self.broadcast_to_topic(
            f"tmux:{session_name}",
            {
                "type": "tmux_output",
                "session": session_name,
                "content": content,
                "timestamp": datetime.now().isoformat()
            }
        )

    def get_connection_stats(self) -> dict:
        """Get statistics about current connections."""
        return {
            "total_connections": len(self.active_connections),
            "total_topics": len(self.subscriptions),
            "subscriptions_per_topic": {
                topic: len(connections)
                for topic, connections in self.subscriptions.items()
            }
        }