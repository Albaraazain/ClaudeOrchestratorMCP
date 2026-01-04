/**
 * Connection Status Component
 * Shows WebSocket connection state and last update time
 */

import React, { useEffect, useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import { useRealtimeStore } from '../stores/realtimeStore';

export const ConnectionStatus: React.FC = () => {
  const { connected, connecting, error, reconnectAttempts } = useWebSocket();
  const { lastUpdateTime } = useRealtimeStore();
  const [timeSinceUpdate, setTimeSinceUpdate] = useState<string>('');

  // Update time since last update
  useEffect(() => {
    if (!lastUpdateTime) return;

    const updateTime = () => {
      const now = new Date();
      const last = new Date(lastUpdateTime);
      const diff = Math.floor((now.getTime() - last.getTime()) / 1000);

      if (diff < 60) {
        setTimeSinceUpdate(`${diff}s ago`);
      } else if (diff < 3600) {
        setTimeSinceUpdate(`${Math.floor(diff / 60)}m ago`);
      } else {
        setTimeSinceUpdate(`${Math.floor(diff / 3600)}h ago`);
      }
    };

    updateTime();
    const interval = setInterval(updateTime, 1000);

    return () => clearInterval(interval);
  }, [lastUpdateTime]);

  // Determine status color and icon
  const getStatusIndicator = () => {
    if (connecting) {
      return {
        color: '#FFA500',
        icon: '⟳',
        text: 'Connecting...'
      };
    }

    if (connected) {
      return {
        color: '#00FF00',
        icon: '●',
        text: 'Connected'
      };
    }

    if (error) {
      return {
        color: '#FF0000',
        icon: '✕',
        text: 'Disconnected'
      };
    }

    return {
      color: '#808080',
      icon: '○',
      text: 'Not connected'
    };
  };

  const status = getStatusIndicator();

  return (
    <div style={styles.container}>
      <div style={styles.status}>
        <span style={{ ...styles.indicator, color: status.color }}>
          {status.icon}
        </span>
        <span style={styles.text}>{status.text}</span>

        {reconnectAttempts > 0 && (
          <span style={styles.reconnect}>
            (Attempt {reconnectAttempts}/5)
          </span>
        )}
      </div>

      {lastUpdateTime && (
        <div style={styles.update}>
          <span style={styles.updateText}>Last update: {timeSinceUpdate}</span>
        </div>
      )}

      {error && (
        <div style={styles.error}>
          <span style={styles.errorText}>{error}</span>
        </div>
      )}
    </div>
  );
};

const styles: { [key: string]: React.CSSProperties } = {
  container: {
    position: 'fixed',
    bottom: 20,
    right: 20,
    backgroundColor: 'rgba(0, 0, 0, 0.8)',
    color: 'white',
    padding: '10px 15px',
    borderRadius: '8px',
    fontSize: '12px',
    fontFamily: 'monospace',
    zIndex: 1000,
    minWidth: '200px',
    boxShadow: '0 2px 10px rgba(0, 0, 0, 0.3)'
  },
  status: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    marginBottom: '4px'
  },
  indicator: {
    fontSize: '14px',
    animation: 'pulse 2s infinite'
  },
  text: {
    fontWeight: 'bold'
  },
  reconnect: {
    opacity: 0.7,
    fontSize: '11px'
  },
  update: {
    marginTop: '4px',
    paddingTop: '4px',
    borderTop: '1px solid rgba(255, 255, 255, 0.2)'
  },
  updateText: {
    opacity: 0.8,
    fontSize: '11px'
  },
  error: {
    marginTop: '4px',
    paddingTop: '4px',
    borderTop: '1px solid rgba(255, 0, 0, 0.3)'
  },
  errorText: {
    color: '#FF6B6B',
    fontSize: '11px'
  }
};

// Add CSS animation for pulse effect
const styleSheet = document.createElement('style');
styleSheet.textContent = `
  @keyframes pulse {
    0% { opacity: 1; }
    50% { opacity: 0.5; }
    100% { opacity: 1; }
  }

  @keyframes flash {
    0% { background-color: rgba(255, 255, 0, 0.3); }
    50% { background-color: rgba(255, 255, 0, 0.1); }
    100% { background-color: transparent; }
  }

  .task-flash {
    animation: flash 0.5s ease-in-out 3;
  }

  .agent-flash {
    animation: flash 0.5s ease-in-out 3;
  }
`;
document.head.appendChild(styleSheet);

export default ConnectionStatus;