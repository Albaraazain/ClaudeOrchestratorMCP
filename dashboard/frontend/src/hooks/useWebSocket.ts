/**
 * React Hook for WebSocket Connection
 * Provides WebSocket functionality to React components
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import { wsManager, WebSocketMessage, ConnectionState } from '../services/websocket';

export interface UseWebSocketOptions {
  autoConnect?: boolean;
  taskId?: string;
  agentId?: string;
  subscribeToAll?: boolean;
  onMessage?: (message: WebSocketMessage) => void;
}

export interface UseWebSocketReturn {
  connected: boolean;
  connecting: boolean;
  error: string | null;
  messages: WebSocketMessage[];
  lastMessage: WebSocketMessage | null;
  reconnectAttempts: number;
  send: (message: any) => void;
  connect: () => void;
  disconnect: () => void;
  clearMessages: () => void;
  subscribeToTask: (taskId: string) => void;
  subscribeToAgent: (agentId: string) => void;
}

const MAX_MESSAGES = 1000; // Limit stored messages to prevent memory issues

export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketReturn {
  const {
    autoConnect = true,
    taskId,
    agentId,
    subscribeToAll = false,
    onMessage
  } = options;

  const [connectionState, setConnectionState] = useState<ConnectionState>(
    wsManager.getState()
  );
  const [messages, setMessages] = useState<WebSocketMessage[]>([]);
  const messageHandlerRef = useRef<((msg: WebSocketMessage) => void) | null>(null);
  const connectionHandlerRef = useRef<((state: ConnectionState) => void) | null>(null);

  // Handle connection state changes
  useEffect(() => {
    const unsubscribe = wsManager.onConnectionChange((state) => {
      setConnectionState(state);
    });

    connectionHandlerRef.current = unsubscribe;
    return unsubscribe;
  }, []);

  // Handle incoming messages
  useEffect(() => {
    const handleMessage = (message: WebSocketMessage) => {
      // Add to messages array
      setMessages(prev => {
        const updated = [...prev, message];
        // Keep only last MAX_MESSAGES
        return updated.slice(-MAX_MESSAGES);
      });

      // Call custom handler if provided
      if (onMessage) {
        onMessage(message);
      }
    };

    const unsubscribe = wsManager.onMessage(handleMessage);
    messageHandlerRef.current = unsubscribe;

    return unsubscribe;
  }, [onMessage]);

  // Auto-connect on mount if enabled
  useEffect(() => {
    if (autoConnect && !connectionState.connected && !connectionState.connecting) {
      wsManager.connect();
    }

    return () => {
      // Don't auto-disconnect on unmount - allow shared connection
    };
  }, [autoConnect]);

  // Subscribe to specific resources once connected
  useEffect(() => {
    if (!connectionState.connected) return;

    if (taskId) {
      console.log(`[useWebSocket] Subscribing to task: ${taskId}`);
      wsManager.subscribeToTask(taskId);
    }

    if (agentId) {
      console.log(`[useWebSocket] Subscribing to agent: ${agentId}`);
      wsManager.subscribeToAgent(agentId);
    }

    if (subscribeToAll) {
      console.log('[useWebSocket] Subscribing to all updates');
      wsManager.subscribeToAll();
    }
  }, [connectionState.connected, taskId, agentId, subscribeToAll]);

  // Memoized functions
  const send = useCallback((message: any) => {
    wsManager.send(message);
  }, []);

  const connect = useCallback(() => {
    wsManager.connect();
  }, []);

  const disconnect = useCallback(() => {
    wsManager.disconnect();
  }, []);

  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  const subscribeToTask = useCallback((id: string) => {
    if (connectionState.connected) {
      wsManager.subscribeToTask(id);
    }
  }, [connectionState.connected]);

  const subscribeToAgent = useCallback((id: string) => {
    if (connectionState.connected) {
      wsManager.subscribeToAgent(id);
    }
  }, [connectionState.connected]);

  return {
    connected: connectionState.connected,
    connecting: connectionState.connecting,
    error: connectionState.error,
    messages,
    lastMessage: connectionState.lastMessage,
    reconnectAttempts: connectionState.reconnectAttempts,
    send,
    connect,
    disconnect,
    clearMessages,
    subscribeToTask,
    subscribeToAgent
  };
}

/**
 * Hook for subscribing to task updates
 */
export function useTaskUpdates(taskId: string | undefined) {
  const [taskUpdates, setTaskUpdates] = useState<WebSocketMessage[]>([]);

  const handleMessage = useCallback((message: WebSocketMessage) => {
    if (message.type === 'task_update' || message.type === 'phase_change') {
      setTaskUpdates(prev => [...prev, message]);
    }
  }, []);

  const ws = useWebSocket({
    taskId,
    onMessage: handleMessage
  });

  return {
    ...ws,
    taskUpdates
  };
}

/**
 * Hook for subscribing to agent updates
 */
export function useAgentUpdates(agentId: string | undefined) {
  const [agentUpdates, setAgentUpdates] = useState<WebSocketMessage[]>([]);
  const [logEntries, setLogEntries] = useState<string[]>([]);

  const handleMessage = useCallback((message: WebSocketMessage) => {
    if (message.type === 'agent_update') {
      setAgentUpdates(prev => [...prev, message]);
    } else if (message.type === 'log_entry') {
      setLogEntries(prev => [...prev, message.data.content || '']);
    }
  }, []);

  const ws = useWebSocket({
    agentId,
    onMessage: handleMessage
  });

  return {
    ...ws,
    agentUpdates,
    logEntries
  };
}