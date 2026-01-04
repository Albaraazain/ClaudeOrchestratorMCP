/**
 * WebSocket Provider Component
 * Initializes and manages WebSocket connection at app level
 */

import React, { useEffect, ReactNode } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useRealtimeStore } from '../stores/realtimeStore';
import ConnectionStatus from '../components/ConnectionStatus';

interface WebSocketProviderProps {
  children: ReactNode;
}

export const WebSocketProvider: React.FC<WebSocketProviderProps> = ({ children }) => {
  const { connected, messages } = useWebSocket({
    autoConnect: true,
    subscribeToAll: true // Subscribe to all updates by default
  });

  const { processWebSocketMessage, setConnectionStatus } = useRealtimeStore();

  // Update connection status in store
  useEffect(() => {
    setConnectionStatus(connected);
  }, [connected, setConnectionStatus]);

  // Process all incoming messages through the store
  useEffect(() => {
    messages.forEach(message => {
      processWebSocketMessage(message);
    });
  }, [messages, processWebSocketMessage]);

  // Clear old data periodically
  useEffect(() => {
    const interval = setInterval(() => {
      useRealtimeStore.getState().clearOldData();
    }, 60000); // Clear old data every minute

    return () => clearInterval(interval);
  }, []);

  return (
    <>
      {children}
      <ConnectionStatus />
    </>
  );
};

export default WebSocketProvider;