/**
 * WebSocket Connection Manager
 * Handles real-time communication with the dashboard backend
 */

export type MessageType =
  | 'task_update'
  | 'agent_update'
  | 'phase_change'
  | 'log_entry'
  | 'finding'
  | 'tmux_output'
  | 'connection_established'
  | 'subscription_confirmed'
  | 'error';

export interface WebSocketMessage {
  type: MessageType;
  data: any;
  timestamp?: string;
}

export interface ConnectionState {
  connected: boolean;
  connecting: boolean;
  error: string | null;
  lastMessage: WebSocketMessage | null;
  reconnectAttempts: number;
}

type MessageHandler = (message: WebSocketMessage) => void;
type ConnectionHandler = (state: ConnectionState) => void;

export class WebSocketManager {
  private ws: WebSocket | null = null;
  private url: string;
  private messageHandlers: Set<MessageHandler> = new Set();
  private connectionHandlers: Set<ConnectionHandler> = new Set();
  private reconnectTimeout: NodeJS.Timeout | null = null;
  private heartbeatInterval: NodeJS.Timeout | null = null;
  private state: ConnectionState = {
    connected: false,
    connecting: false,
    error: null,
    lastMessage: null,
    reconnectAttempts: 0
  };

  private readonly MAX_RECONNECT_ATTEMPTS = 5;
  private readonly RECONNECT_DELAY = 3000;
  private readonly HEARTBEAT_INTERVAL = 30000;

  constructor(baseUrl: string = 'ws://localhost:8765') {
    this.url = baseUrl;
  }

  /**
   * Connect to WebSocket server
   */
  connect(path: string = '/ws'): void {
    if (this.state.connected || this.state.connecting) {
      console.log('[WebSocket] Already connected or connecting');
      return;
    }

    this.updateState({ connecting: true, error: null });

    try {
      const fullUrl = `${this.url}${path}`;
      console.log(`[WebSocket] Connecting to ${fullUrl}...`);
      this.ws = new WebSocket(fullUrl);

      this.ws.onopen = this.handleOpen.bind(this);
      this.ws.onmessage = this.handleMessage.bind(this);
      this.ws.onerror = this.handleError.bind(this);
      this.ws.onclose = this.handleClose.bind(this);
    } catch (error) {
      console.error('[WebSocket] Connection failed:', error);
      this.updateState({
        connecting: false,
        error: error instanceof Error ? error.message : 'Connection failed'
      });
      this.scheduleReconnect();
    }
  }

  /**
   * Disconnect from WebSocket server
   */
  disconnect(): void {
    console.log('[WebSocket] Disconnecting...');
    this.clearTimers();

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.updateState({
      connected: false,
      connecting: false,
      reconnectAttempts: 0
    });
  }

  /**
   * Send message to server
   */
  send(message: any): void {
    if (!this.state.connected || !this.ws) {
      console.warn('[WebSocket] Cannot send - not connected');
      return;
    }

    try {
      const payload = typeof message === 'string'
        ? message
        : JSON.stringify(message);

      this.ws.send(payload);
      console.log('[WebSocket] Sent:', message);
    } catch (error) {
      console.error('[WebSocket] Send failed:', error);
    }
  }

  /**
   * Subscribe to a specific task
   */
  subscribeToTask(taskId: string): void {
    this.send({
      type: 'subscribe',
      target: 'task',
      id: taskId
    });
  }

  /**
   * Subscribe to a specific agent
   */
  subscribeToAgent(agentId: string): void {
    this.send({
      type: 'subscribe',
      target: 'agent',
      id: agentId
    });
  }

  /**
   * Subscribe to all updates
   */
  subscribeToAll(): void {
    this.send({
      type: 'subscribe',
      target: 'all'
    });
  }

  /**
   * Add message handler
   */
  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  /**
   * Add connection state handler
   */
  onConnectionChange(handler: ConnectionHandler): () => void {
    this.connectionHandlers.add(handler);
    // Immediately call with current state
    handler(this.state);
    return () => this.connectionHandlers.delete(handler);
  }

  // Private methods

  private handleOpen(): void {
    console.log('[WebSocket] Connected');
    this.updateState({
      connected: true,
      connecting: false,
      error: null,
      reconnectAttempts: 0
    });

    // Start heartbeat
    this.startHeartbeat();
  }

  private handleMessage(event: MessageEvent): void {
    try {
      const message = JSON.parse(event.data) as WebSocketMessage;
      console.log('[WebSocket] Received:', message.type, message);

      this.updateState({ lastMessage: message });

      // Notify all handlers
      this.messageHandlers.forEach(handler => {
        try {
          handler(message);
        } catch (error) {
          console.error('[WebSocket] Handler error:', error);
        }
      });
    } catch (error) {
      console.error('[WebSocket] Failed to parse message:', error);
    }
  }

  private handleError(event: Event): void {
    console.error('[WebSocket] Error:', event);
    this.updateState({
      error: 'WebSocket error occurred'
    });
  }

  private handleClose(event: CloseEvent): void {
    console.log('[WebSocket] Closed:', event.code, event.reason);
    this.updateState({
      connected: false,
      connecting: false,
      error: event.reason || 'Connection closed'
    });

    this.clearTimers();

    // Auto-reconnect if not manually closed
    if (event.code !== 1000) {
      this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    if (this.state.reconnectAttempts >= this.MAX_RECONNECT_ATTEMPTS) {
      console.error('[WebSocket] Max reconnect attempts reached');
      this.updateState({
        error: 'Max reconnection attempts reached'
      });
      return;
    }

    const delay = this.RECONNECT_DELAY * (this.state.reconnectAttempts + 1);
    console.log(`[WebSocket] Reconnecting in ${delay}ms...`);

    this.reconnectTimeout = setTimeout(() => {
      this.updateState({
        reconnectAttempts: this.state.reconnectAttempts + 1
      });
      this.connect();
    }, delay);
  }

  private startHeartbeat(): void {
    this.heartbeatInterval = setInterval(() => {
      if (this.state.connected) {
        this.send({ type: 'ping' });
      }
    }, this.HEARTBEAT_INTERVAL);
  }

  private clearTimers(): void {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }
  }

  private updateState(updates: Partial<ConnectionState>): void {
    this.state = { ...this.state, ...updates };

    // Notify all connection handlers
    this.connectionHandlers.forEach(handler => {
      try {
        handler(this.state);
      } catch (error) {
        console.error('[WebSocket] Connection handler error:', error);
      }
    });
  }

  /**
   * Get current connection state
   */
  getState(): ConnectionState {
    return { ...this.state };
  }
}

// Singleton instance
export const wsManager = new WebSocketManager();