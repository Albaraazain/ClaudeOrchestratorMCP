"""
WebSocket Connection Manager for Claude Orchestrator Dashboard
Manages active WebSocket connections and subscription routing
"""

import asyncio
import json
import logging
from typing import Dict, Set, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect
from enum import Enum

logger = logging.getLogger(__name__)


class SubscriptionTarget(Enum):
    """Types of entities clients can subscribe to"""
    TASK = "task"
    AGENT = "agent"
    LOGS = "logs"
    PHASE = "phase"
    TMUX = "tmux"


class EventType(Enum):
    """Server-to-client event types"""
    TASK_UPDATE = "task_update"
    AGENT_UPDATE = "agent_update"
    PHASE_CHANGE = "phase_change"
    LOG_CHUNK = "log_chunk"
    TMUX_OUTPUT = "tmux_output"
    FINDING_REPORTED = "finding_reported"
    CONNECTION_STATUS = "connection_status"
    ERROR = "error"


@dataclass
class ClientConnection:
    """Represents a connected WebSocket client"""
    client_id: str
    websocket: WebSocket
    connected_at: datetime
    subscriptions: Dict[str, Set[str]] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize subscription dictionary structure"""
        for target in SubscriptionTarget:
            self.subscriptions[target.value] = set()


class ConnectionManager:
    """Manages WebSocket connections and message routing"""

    def __init__(self):
        """Initialize the connection manager"""
        self._connections: Dict[str, ClientConnection] = {}
        self._subscription_index: Dict[str, Set[str]] = {}  # subscription_key -> client_ids
        self._lock = asyncio.Lock()
        logger.info("WebSocket ConnectionManager initialized")

    async def connect(self, websocket: WebSocket, client_id: str) -> ClientConnection:
        """
        Accept a new WebSocket connection

        Args:
            websocket: The FastAPI WebSocket instance
            client_id: Unique identifier for the client

        Returns:
            ClientConnection object
        """
        await websocket.accept()

        async with self._lock:
            connection = ClientConnection(
                client_id=client_id,
                websocket=websocket,
                connected_at=datetime.utcnow()
            )
            self._connections[client_id] = connection

            # Send connection confirmation
            await self._send_to_client(client_id, {
                "type": EventType.CONNECTION_STATUS.value,
                "status": "connected",
                "client_id": client_id,
                "timestamp": connection.connected_at.isoformat()
            })

            logger.info(f"Client {client_id} connected. Total connections: {len(self._connections)}")
            return connection

    async def disconnect(self, client_id: str):
        """
        Handle client disconnection

        Args:
            client_id: ID of disconnecting client
        """
        async with self._lock:
            if client_id not in self._connections:
                return

            connection = self._connections[client_id]

            # Remove from all subscription indices
            for target, ids in connection.subscriptions.items():
                for entity_id in ids:
                    key = self._make_subscription_key(target, entity_id)
                    if key in self._subscription_index:
                        self._subscription_index[key].discard(client_id)
                        if not self._subscription_index[key]:
                            del self._subscription_index[key]

            del self._connections[client_id]
            logger.info(f"Client {client_id} disconnected. Remaining connections: {len(self._connections)}")

    async def subscribe(self, client_id: str, target: str, entity_id: str) -> bool:
        """
        Subscribe a client to updates for a specific entity

        Args:
            client_id: Client requesting subscription
            target: Type of subscription (task, agent, logs, etc.)
            entity_id: ID of entity to subscribe to

        Returns:
            True if subscription successful
        """
        async with self._lock:
            if client_id not in self._connections:
                logger.warning(f"Subscribe request from unknown client: {client_id}")
                return False

            connection = self._connections[client_id]

            # Validate target
            if target not in [t.value for t in SubscriptionTarget]:
                logger.warning(f"Invalid subscription target: {target}")
                await self._send_to_client(client_id, {
                    "type": EventType.ERROR.value,
                    "message": f"Invalid subscription target: {target}"
                })
                return False

            # Add to client's subscriptions
            connection.subscriptions[target].add(entity_id)

            # Add to subscription index
            key = self._make_subscription_key(target, entity_id)
            if key not in self._subscription_index:
                self._subscription_index[key] = set()
            self._subscription_index[key].add(client_id)

            logger.debug(f"Client {client_id} subscribed to {target}:{entity_id}")

            # Send confirmation
            await self._send_to_client(client_id, {
                "type": "subscription_confirmed",
                "target": target,
                "id": entity_id,
                "timestamp": datetime.utcnow().isoformat()
            })

            return True

    async def unsubscribe(self, client_id: str, target: str, entity_id: str) -> bool:
        """
        Unsubscribe a client from updates for a specific entity

        Args:
            client_id: Client requesting unsubscription
            target: Type of subscription (task, agent, logs, etc.)
            entity_id: ID of entity to unsubscribe from

        Returns:
            True if unsubscription successful
        """
        async with self._lock:
            if client_id not in self._connections:
                return False

            connection = self._connections[client_id]

            if target not in connection.subscriptions:
                return False

            # Remove from client's subscriptions
            connection.subscriptions[target].discard(entity_id)

            # Remove from subscription index
            key = self._make_subscription_key(target, entity_id)
            if key in self._subscription_index:
                self._subscription_index[key].discard(client_id)
                if not self._subscription_index[key]:
                    del self._subscription_index[key]

            logger.debug(f"Client {client_id} unsubscribed from {target}:{entity_id}")

            # Send confirmation
            await self._send_to_client(client_id, {
                "type": "unsubscription_confirmed",
                "target": target,
                "id": entity_id,
                "timestamp": datetime.utcnow().isoformat()
            })

            return True

    async def broadcast(self, message: Dict[str, Any]):
        """
        Broadcast a message to all connected clients

        Args:
            message: Message to broadcast
        """
        disconnected = []
        for client_id in list(self._connections.keys()):
            try:
                await self._send_to_client(client_id, message)
            except Exception as e:
                logger.error(f"Error broadcasting to {client_id}: {e}")
                disconnected.append(client_id)

        # Clean up disconnected clients
        for client_id in disconnected:
            await self.disconnect(client_id)

    async def send_to_subscription(self, target: str, entity_id: str, message: Dict[str, Any]):
        """
        Send a message to all clients subscribed to a specific entity

        Args:
            target: Subscription target type
            entity_id: ID of entity
            message: Message to send
        """
        key = self._make_subscription_key(target, entity_id)

        async with self._lock:
            client_ids = self._subscription_index.get(key, set()).copy()

        if not client_ids:
            logger.debug(f"No subscribers for {target}:{entity_id}")
            return

        disconnected = []
        for client_id in client_ids:
            try:
                await self._send_to_client(client_id, message)
            except Exception as e:
                logger.error(f"Error sending to {client_id}: {e}")
                disconnected.append(client_id)

        # Clean up disconnected clients
        for client_id in disconnected:
            await self.disconnect(client_id)

        logger.debug(f"Sent message to {len(client_ids) - len(disconnected)} subscribers of {target}:{entity_id}")

    async def send_task_update(self, task_id: str, data: Dict[str, Any]):
        """Send task update to subscribed clients"""
        message = {
            "type": EventType.TASK_UPDATE.value,
            "task_id": task_id,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.send_to_subscription(SubscriptionTarget.TASK.value, task_id, message)

    async def send_agent_update(self, agent_id: str, data: Dict[str, Any]):
        """Send agent update to subscribed clients"""
        message = {
            "type": EventType.AGENT_UPDATE.value,
            "agent_id": agent_id,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.send_to_subscription(SubscriptionTarget.AGENT.value, agent_id, message)

    async def send_phase_change(self, task_id: str, phase_data: Dict[str, Any]):
        """Send phase change notification"""
        message = {
            "type": EventType.PHASE_CHANGE.value,
            "task_id": task_id,
            "phase": phase_data,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.send_to_subscription(SubscriptionTarget.PHASE.value, task_id, message)

    async def send_log_chunk(self, agent_id: str, content: str):
        """Send log chunk to subscribed clients"""
        message = {
            "type": EventType.LOG_CHUNK.value,
            "agent_id": agent_id,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.send_to_subscription(SubscriptionTarget.LOGS.value, agent_id, message)

    async def send_tmux_output(self, session_name: str, content: str):
        """Send tmux output to subscribed clients"""
        message = {
            "type": EventType.TMUX_OUTPUT.value,
            "session": session_name,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        }
        await self.send_to_subscription(SubscriptionTarget.TMUX.value, session_name, message)

    async def send_finding_reported(self, agent_id: str, finding: Dict[str, Any]):
        """Send finding report notification"""
        message = {
            "type": EventType.FINDING_REPORTED.value,
            "agent_id": agent_id,
            "finding": finding,
            "timestamp": datetime.utcnow().isoformat()
        }
        # Send to both agent and task subscribers
        await self.send_to_subscription(SubscriptionTarget.AGENT.value, agent_id, message)
        if "task_id" in finding:
            await self.send_to_subscription(SubscriptionTarget.TASK.value, finding["task_id"], message)

    async def _send_to_client(self, client_id: str, message: Dict[str, Any]):
        """
        Send a message to a specific client

        Args:
            client_id: Target client ID
            message: Message to send
        """
        if client_id not in self._connections:
            return

        connection = self._connections[client_id]
        try:
            await connection.websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send message to {client_id}: {e}")
            raise

    def _make_subscription_key(self, target: str, entity_id: str) -> str:
        """Create a unique key for subscription indexing"""
        return f"{target}:{entity_id}"

    def get_connection_stats(self) -> Dict[str, Any]:
        """Get statistics about current connections"""
        total_subscriptions = sum(
            len(ids) for ids in self._subscription_index.values()
        )

        subscription_breakdown = {}
        for target in SubscriptionTarget:
            count = sum(
                1 for key in self._subscription_index.keys()
                if key.startswith(f"{target.value}:")
            )
            subscription_breakdown[target.value] = count

        return {
            "total_connections": len(self._connections),
            "total_subscriptions": total_subscriptions,
            "subscription_breakdown": subscription_breakdown,
            "clients": [
                {
                    "client_id": conn.client_id,
                    "connected_at": conn.connected_at.isoformat(),
                    "subscription_count": sum(len(subs) for subs in conn.subscriptions.values())
                }
                for conn in self._connections.values()
            ]
        }


# Global connection manager instance
connection_manager = ConnectionManager()