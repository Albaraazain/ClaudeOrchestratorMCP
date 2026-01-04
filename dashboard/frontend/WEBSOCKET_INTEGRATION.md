# WebSocket Integration Documentation

## Overview

This frontend implements real-time WebSocket updates for the Claude Orchestrator Dashboard, providing live updates for tasks, agents, phases, and logs.

## Architecture

### Core Components

1. **WebSocket Service** (`src/services/websocket.ts`)
   - Singleton WebSocketManager class
   - Auto-reconnection with exponential backoff
   - Heartbeat/ping mechanism
   - Message type definitions
   - Subscription management

2. **React Hooks** (`src/hooks/useWebSocket.ts`)
   - `useWebSocket`: Main hook for WebSocket connection
   - `useTaskUpdates`: Specialized hook for task updates
   - `useAgentUpdates`: Specialized hook for agent updates

3. **Zustand Store** (`src/stores/realtimeStore.ts`)
   - Centralized real-time data management
   - Flash indicators for UI updates
   - Message processing and filtering
   - Auto-cleanup of old data

4. **UI Components**
   - `ConnectionStatus`: Shows connection state
   - `RealtimeLogViewer`: Live log streaming
   - `WebSocketProvider`: App-level connection provider

## Usage

### Basic Setup

1. **Install dependencies**:
```bash
npm install zustand
```

2. **Wrap your app with WebSocketProvider**:
```tsx
import WebSocketProvider from './providers/WebSocketProvider';

function App() {
  return (
    <WebSocketProvider>
      {/* Your app components */}
    </WebSocketProvider>
  );
}
```

3. **Use in components**:
```tsx
import { useWebSocket } from '../hooks/useWebSocket';

function MyComponent() {
  const { connected, messages, send } = useWebSocket({
    taskId: 'TASK-123',
    autoConnect: true
  });

  return (
    <div>
      Status: {connected ? 'Connected' : 'Disconnected'}
      Messages: {messages.length}
    </div>
  );
}
```

## Message Types

### Incoming Messages

- `task_update`: Task status/progress changes
- `agent_update`: Agent status/progress changes
- `phase_change`: Phase status transitions
- `log_entry`: New log lines from agents
- `finding`: Agent discoveries/insights
- `tmux_output`: Terminal output from tmux sessions

### Outgoing Messages

- `subscribe`: Subscribe to updates (task/agent/all)
- `unsubscribe`: Unsubscribe from updates
- `ping`: Heartbeat message

## Features

### Auto-Reconnection
- Automatic reconnection on disconnect
- Exponential backoff (3s, 6s, 9s, 12s, 15s)
- Max 5 reconnection attempts
- Visual indicator of reconnection status

### Flash Notifications
- Tasks and agents flash yellow when updated
- 2-second flash duration
- CSS animation for smooth effect

### Real-Time Updates
- Immediate UI updates on message receipt
- Progress bars update smoothly
- Status badges change color dynamically

### Log Streaming
- Live log streaming from agents
- Syntax highlighting by log level
- Auto-scroll with manual override
- Filtering and search capabilities

## Testing

### Browser Console Testing

```javascript
// Test WebSocket connection
window.testWebSocket('TASK-123');

// Access WebSocket instance
window.__testWS.send(JSON.stringify({ type: 'ping' }));
```

### Network Tab Testing

1. Open Chrome DevTools
2. Go to Network tab
3. Filter by WS (WebSocket)
4. Click on the WebSocket connection
5. View Messages tab for real-time data flow

## Connection States

| State | Description | UI Indicator |
|-------|-------------|--------------|
| Connecting | Initial connection attempt | Orange spinner |
| Connected | Active WebSocket connection | Green dot |
| Disconnected | Connection lost | Red X |
| Reconnecting | Auto-reconnection in progress | Orange spinner + attempt count |

## Store Integration

The Zustand store (`realtimeStore`) maintains:
- Task updates map (by task ID)
- Agent updates map (by agent ID)
- Recent logs (last 1000 entries)
- Findings list
- Flash indicators for highlighting

### Accessing Store Data

```tsx
import { useRealtimeStore } from '../stores/realtimeStore';

function Component() {
  const { taskUpdates, flashingTasks } = useRealtimeStore();

  // Check if task is flashing
  const isFlashing = flashingTasks.has(taskId);
}
```

## Performance Considerations

1. **Message Limiting**
   - Max 1000 stored messages in hook
   - Max 100 updates per task/agent
   - Old data auto-cleanup every minute

2. **Optimization**
   - Memoized callbacks in hooks
   - Selective re-renders with Zustand
   - Efficient DOM updates with React

3. **Memory Management**
   - Automatic cleanup of old messages
   - Limited buffer sizes
   - Unsubscribe on component unmount

## Troubleshooting

### Connection Issues

1. **Check backend is running**:
```bash
curl http://localhost:8000/health
```

2. **Verify WebSocket endpoint**:
```bash
wscat -c ws://localhost:8000/ws
```

3. **Check browser console for errors**

### Missing Updates

1. Verify subscription is active
2. Check message type filters
3. Ensure task/agent IDs match

### Performance Issues

1. Reduce max stored messages
2. Increase cleanup interval
3. Disable auto-scroll for large logs

## API Integration

The WebSocket integration expects the backend to:
1. Accept connections at `ws://localhost:8000/ws`
2. Handle subscription messages
3. Send typed messages with consistent structure
4. Support ping/pong for heartbeat

## Future Enhancements

- [ ] Binary message support for large logs
- [ ] Compression for high-volume updates
- [ ] Persistent message history
- [ ] Replay functionality
- [ ] Advanced filtering/search
- [ ] Export log functionality
- [ ] Multi-tab synchronization