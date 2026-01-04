/**
 * WebSocket Connection Test Utility
 * Use this to test WebSocket connectivity from browser console
 */

export function testWebSocketConnection(taskId?: string): void {
  console.log('[WebSocket Test] Starting connection test...');

  const ws = new WebSocket('ws://localhost:8000/ws');

  ws.onopen = () => {
    console.log('[WebSocket Test] ✅ Connected successfully');

    // Test subscription
    if (taskId) {
      console.log(`[WebSocket Test] Subscribing to task: ${taskId}`);
      ws.send(JSON.stringify({
        type: 'subscribe',
        target: 'task',
        id: taskId
      }));
    } else {
      console.log('[WebSocket Test] Subscribing to all updates');
      ws.send(JSON.stringify({
        type: 'subscribe',
        target: 'all'
      }));
    }

    // Send test ping
    setTimeout(() => {
      console.log('[WebSocket Test] Sending ping...');
      ws.send(JSON.stringify({ type: 'ping' }));
    }, 1000);
  };

  ws.onmessage = (event) => {
    console.log('[WebSocket Test] 📨 Message received:', JSON.parse(event.data));
  };

  ws.onerror = (error) => {
    console.error('[WebSocket Test] ❌ Error:', error);
  };

  ws.onclose = (event) => {
    console.log('[WebSocket Test] Connection closed:', {
      code: event.code,
      reason: event.reason,
      wasClean: event.wasClean
    });
  };

  // Close after 10 seconds
  setTimeout(() => {
    console.log('[WebSocket Test] Closing connection after test...');
    ws.close();
  }, 10000);

  // Make available globally for manual testing
  (window as any).__testWS = ws;
  console.log('[WebSocket Test] WebSocket instance available as window.__testWS');
}

// Test utility to simulate messages
export function simulateWebSocketMessage(type: string, data: any): void {
  const message = {
    type,
    data,
    timestamp: new Date().toISOString()
  };

  console.log('[WebSocket Test] Simulating message:', message);

  // If using the WebSocket manager
  const { wsManager } = require('../services/websocket');
  if (wsManager && wsManager.getState().connected) {
    // This would normally come from the server
    console.warn('[WebSocket Test] Cannot simulate server messages directly');
    console.log('[WebSocket Test] Use the server API to trigger real events');
  }
}

// Export to window for browser console access
if (typeof window !== 'undefined') {
  (window as any).testWebSocket = testWebSocketConnection;
  (window as any).simulateWSMessage = simulateWebSocketMessage;
  console.log('[WebSocket Test] Test functions available:');
  console.log('  - window.testWebSocket(taskId?)');
  console.log('  - window.simulateWSMessage(type, data)');
}