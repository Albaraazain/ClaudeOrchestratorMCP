"""
WebSocket Event Handlers for Claude Orchestrator Dashboard
Implements WebSocket endpoint and client event handling
"""

import asyncio
import json
import logging
import uuid
from typing import Dict, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse

from .manager import connection_manager, SubscriptionTarget

logger = logging.getLogger(__name__)


class WebSocketEndpoint:
    """WebSocket endpoint handler with client event processing"""

    def __init__(self):
        """Initialize WebSocket endpoint"""
        self.active_handlers: Dict[str, asyncio.Task] = {}
        logger.info("WebSocket endpoint initialized")

    async def handle_connection(self, websocket: WebSocket):
        """
        Main WebSocket connection handler

        Args:
            websocket: FastAPI WebSocket instance
        """
        # Generate unique client ID
        client_id = str(uuid.uuid4())

        try:
            # Accept connection and register with manager
            connection = await connection_manager.connect(websocket, client_id)
            logger.info(f"WebSocket connection established: {client_id}")

            # Handle incoming messages
            await self._message_loop(client_id, websocket)

        except WebSocketDisconnect:
            logger.info(f"WebSocket client {client_id} disconnected normally")
        except Exception as e:
            logger.error(f"WebSocket error for client {client_id}: {e}")
        finally:
            # Clean up connection
            await connection_manager.disconnect(client_id)
            await self._cleanup_client_handlers(client_id)

    async def _message_loop(self, client_id: str, websocket: WebSocket):
        """
        Process incoming messages from client

        Args:
            client_id: Unique client identifier
            websocket: WebSocket connection
        """
        while True:
            try:
                # Receive message from client
                data = await websocket.receive_json()

                # Process based on message type
                message_type = data.get("type")

                if not message_type:
                    await self._send_error(client_id, "Missing message type")
                    continue

                # Route to appropriate handler
                if message_type == "subscribe":
                    await self._handle_subscribe(client_id, data)

                elif message_type == "unsubscribe":
                    await self._handle_unsubscribe(client_id, data)

                elif message_type == "tmux_command":
                    await self._handle_tmux_command(client_id, data)

                elif message_type == "ping":
                    await self._handle_ping(client_id)

                elif message_type == "get_stats":
                    await self._handle_get_stats(client_id)

                else:
                    await self._send_error(client_id, f"Unknown message type: {message_type}")

            except WebSocketDisconnect:
                raise
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON from client {client_id}: {e}")
                await self._send_error(client_id, "Invalid JSON format")
            except Exception as e:
                logger.error(f"Error processing message from {client_id}: {e}")
                await self._send_error(client_id, str(e))

    async def _handle_subscribe(self, client_id: str, data: Dict[str, Any]):
        """
        Handle subscription request from client

        Expected format:
        {
            "type": "subscribe",
            "target": "task" | "agent" | "logs" | "phase" | "tmux",
            "id": "entity_id"
        }
        """
        target = data.get("target")
        entity_id = data.get("id")

        if not target or not entity_id:
            await self._send_error(client_id, "Missing target or id for subscription")
            return

        # Validate target
        valid_targets = [t.value for t in SubscriptionTarget]
        if target not in valid_targets:
            await self._send_error(client_id, f"Invalid subscription target: {target}. Valid targets: {valid_targets}")
            return

        # Process subscription
        success = await connection_manager.subscribe(client_id, target, entity_id)

        if success:
            logger.debug(f"Client {client_id} subscribed to {target}:{entity_id}")

            # For log subscriptions, start streaming if not already active
            if target == SubscriptionTarget.LOGS.value:
                await self._start_log_streaming(client_id, entity_id)

            # For tmux subscriptions, start output streaming
            elif target == SubscriptionTarget.TMUX.value:
                await self._start_tmux_streaming(client_id, entity_id)
        else:
            await self._send_error(client_id, f"Failed to subscribe to {target}:{entity_id}")

    async def _handle_unsubscribe(self, client_id: str, data: Dict[str, Any]):
        """
        Handle unsubscription request from client

        Expected format:
        {
            "type": "unsubscribe",
            "target": "task" | "agent" | "logs" | "phase" | "tmux",
            "id": "entity_id"
        }
        """
        target = data.get("target")
        entity_id = data.get("id")

        if not target or not entity_id:
            await self._send_error(client_id, "Missing target or id for unsubscription")
            return

        # Process unsubscription
        success = await connection_manager.unsubscribe(client_id, target, entity_id)

        if success:
            logger.debug(f"Client {client_id} unsubscribed from {target}:{entity_id}")

            # Stop streaming if this was the last subscriber
            if target == SubscriptionTarget.LOGS.value:
                await self._stop_log_streaming_if_needed(entity_id)
            elif target == SubscriptionTarget.TMUX.value:
                await self._stop_tmux_streaming_if_needed(entity_id)
        else:
            await self._send_error(client_id, f"Failed to unsubscribe from {target}:{entity_id}")

    async def _handle_tmux_command(self, client_id: str, data: Dict[str, Any]):
        """
        Handle tmux command from client

        Expected format:
        {
            "type": "tmux_command",
            "session": "session_name",
            "command": "command_to_execute"
        }
        """
        session = data.get("session")
        command = data.get("command")

        if not session or not command:
            await self._send_error(client_id, "Missing session or command")
            return

        # Validate session exists and client has permission
        # This would integrate with tmux_service.py
        logger.info(f"Client {client_id} sending tmux command to {session}: {command[:50]}...")

        # Send acknowledgment
        await self._send_to_client(client_id, {
            "type": "tmux_command_ack",
            "session": session,
            "status": "queued"
        })

        # Note: Actual tmux command execution would be handled by tmux_service.py
        # This is just the WebSocket interface

    async def _handle_ping(self, client_id: str):
        """Handle ping message from client"""
        await self._send_to_client(client_id, {
            "type": "pong",
            "timestamp": asyncio.get_event_loop().time()
        })

    async def _handle_get_stats(self, client_id: str):
        """Handle stats request from client"""
        stats = connection_manager.get_connection_stats()
        await self._send_to_client(client_id, {
            "type": "stats",
            "data": stats
        })

    async def _start_log_streaming(self, client_id: str, agent_id: str):
        """
        Start streaming logs for an agent

        Args:
            client_id: Client requesting logs
            agent_id: Agent whose logs to stream
        """
        # Check if already streaming this agent's logs
        stream_key = f"logs:{agent_id}"
        if stream_key in self.active_handlers:
            logger.debug(f"Log streaming already active for {agent_id}")
            return

        # Note: Actual implementation would integrate with log_streamer.py service
        # This is a placeholder showing the interface
        logger.info(f"Starting log streaming for agent {agent_id}")

    async def _start_tmux_streaming(self, client_id: str, session_name: str):
        """
        Start streaming tmux output for a session

        Args:
            client_id: Client requesting tmux output
            session_name: Tmux session name
        """
        stream_key = f"tmux:{session_name}"
        if stream_key in self.active_handlers:
            logger.debug(f"Tmux streaming already active for {session_name}")
            return

        # Note: Actual implementation would integrate with tmux_service.py
        logger.info(f"Starting tmux output streaming for session {session_name}")

    async def _stop_log_streaming_if_needed(self, agent_id: str):
        """Stop log streaming if no more subscribers"""
        # Check if any clients still subscribed
        key = f"{SubscriptionTarget.LOGS.value}:{agent_id}"
        # Implementation would check subscription count and stop if zero
        pass

    async def _stop_tmux_streaming_if_needed(self, session_name: str):
        """Stop tmux streaming if no more subscribers"""
        key = f"{SubscriptionTarget.TMUX.value}:{session_name}"
        # Implementation would check subscription count and stop if zero
        pass

    async def _cleanup_client_handlers(self, client_id: str):
        """Clean up any active handlers for disconnected client"""
        # Cancel any active streaming tasks for this client
        for key, task in list(self.active_handlers.items()):
            if key.startswith(client_id):
                task.cancel()
                del self.active_handlers[key]
                logger.debug(f"Cancelled handler {key}")

    async def _send_to_client(self, client_id: str, message: Dict[str, Any]):
        """Send message to specific client via connection manager"""
        # This is a wrapper - actual sending handled by connection manager
        try:
            # Get connection from manager and send directly
            # Note: In production, this would be handled by connection_manager
            logger.debug(f"Sending message to client {client_id}: {message.get('type')}")
        except Exception as e:
            logger.error(f"Failed to send message to {client_id}: {e}")

    async def _send_error(self, client_id: str, error_message: str):
        """Send error message to client"""
        await self._send_to_client(client_id, {
            "type": "error",
            "message": error_message,
            "timestamp": asyncio.get_event_loop().time()
        })


# Global WebSocket endpoint instance
websocket_endpoint = WebSocketEndpoint()


async def websocket_route(websocket: WebSocket):
    """
    FastAPI WebSocket route handler

    This function should be registered as the WebSocket endpoint in main.py:

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket_route(websocket)
    """
    await websocket_endpoint.handle_connection(websocket)


# Event emission functions for integration with other services

async def emit_task_update(task_id: str, task_data: Dict[str, Any]):
    """Emit task update to subscribed clients"""
    await connection_manager.send_task_update(task_id, task_data)


async def emit_agent_update(agent_id: str, agent_data: Dict[str, Any]):
    """Emit agent update to subscribed clients"""
    await connection_manager.send_agent_update(agent_id, agent_data)


async def emit_phase_change(task_id: str, phase_data: Dict[str, Any]):
    """Emit phase change to subscribed clients"""
    await connection_manager.send_phase_change(task_id, phase_data)


async def emit_log_chunk(agent_id: str, content: str):
    """Emit log chunk to subscribed clients"""
    await connection_manager.send_log_chunk(agent_id, content)


async def emit_tmux_output(session_name: str, content: str):
    """Emit tmux output to subscribed clients"""
    await connection_manager.send_tmux_output(session_name, content)


async def emit_finding_reported(agent_id: str, finding: Dict[str, Any]):
    """Emit finding report to subscribed clients"""
    await connection_manager.send_finding_reported(agent_id, finding)