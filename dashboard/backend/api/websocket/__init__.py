"""
WebSocket module for Claude Orchestrator Dashboard
Provides real-time communication between backend and frontend
"""

from .manager import (
    ConnectionManager,
    connection_manager,
    SubscriptionTarget,
    EventType,
    ClientConnection
)

from .handlers import (
    WebSocketEndpoint,
    websocket_endpoint,
    websocket_route,
    emit_task_update,
    emit_agent_update,
    emit_phase_change,
    emit_log_chunk,
    emit_tmux_output,
    emit_finding_reported
)

__all__ = [
    # Manager components
    'ConnectionManager',
    'connection_manager',
    'SubscriptionTarget',
    'EventType',
    'ClientConnection',

    # Handler components
    'WebSocketEndpoint',
    'websocket_endpoint',
    'websocket_route',

    # Event emission functions
    'emit_task_update',
    'emit_agent_update',
    'emit_phase_change',
    'emit_log_chunk',
    'emit_tmux_output',
    'emit_finding_reported'
]