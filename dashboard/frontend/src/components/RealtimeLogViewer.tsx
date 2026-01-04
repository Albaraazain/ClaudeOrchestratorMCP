/**
 * Real-Time Log Viewer Component
 * Streams logs from agents in real-time
 */

import React, { useRef, useEffect, useState } from 'react';
import { useAgentUpdates } from '../hooks/useWebSocket';

interface RealtimeLogViewerProps {
  agentId: string;
  maxLines?: number;
  autoScroll?: boolean;
  showTimestamps?: boolean;
  className?: string;
}

export const RealtimeLogViewer: React.FC<RealtimeLogViewerProps> = ({
  agentId,
  maxLines = 500,
  autoScroll = true,
  showTimestamps = true,
  className = ''
}) => {
  const { connected, logEntries, agentUpdates } = useAgentUpdates(agentId);
  const [filter, setFilter] = useState('');
  const [logLevel, setLogLevel] = useState<'all' | 'debug' | 'info' | 'warning' | 'error'>('all');
  const containerRef = useRef<HTMLDivElement>(null);
  const shouldScrollRef = useRef(autoScroll);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (shouldScrollRef.current && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [logEntries]);

  // Handle manual scroll to detect if user wants auto-scroll
  const handleScroll = () => {
    if (!containerRef.current) return;

    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 10;

    shouldScrollRef.current = isAtBottom;
  };

  // Filter logs based on search and level
  const filteredLogs = logEntries
    .filter(log => {
      if (filter && !log.toLowerCase().includes(filter.toLowerCase())) {
        return false;
      }
      // In a real implementation, you'd parse log level from content
      return true;
    })
    .slice(-maxLines);

  // Get latest agent status
  const latestStatus = agentUpdates[agentUpdates.length - 1];

  return (
    <div className={`flex flex-col h-full bg-gray-900 text-gray-100 rounded-lg ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between p-3 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center gap-3">
          <h3 className="font-mono text-sm font-semibold">
            {agentId}
          </h3>
          <span className={`text-xs px-2 py-1 rounded ${
            connected ? 'bg-green-600' : 'bg-red-600'
          }`}>
            {connected ? 'LIVE' : 'OFFLINE'}
          </span>
          {latestStatus && (
            <span className="text-xs text-gray-400">
              Status: {latestStatus.data.status} | Progress: {latestStatus.data.progress}%
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Log Level Filter */}
          <select
            value={logLevel}
            onChange={(e) => setLogLevel(e.target.value as any)}
            className="px-2 py-1 text-xs bg-gray-700 border border-gray-600 rounded focus:outline-none focus:border-blue-500"
          >
            <option value="all">All</option>
            <option value="debug">Debug</option>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="error">Error</option>
          </select>

          {/* Search Filter */}
          <input
            type="text"
            placeholder="Filter logs..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="px-2 py-1 text-xs bg-gray-700 border border-gray-600 rounded w-32 focus:outline-none focus:border-blue-500"
          />

          {/* Clear Button */}
          <button
            onClick={() => {
              // In a real implementation, you'd clear logs from state
              setFilter('');
            }}
            className="px-2 py-1 text-xs bg-gray-700 hover:bg-gray-600 border border-gray-600 rounded"
          >
            Clear
          </button>

          {/* Auto-scroll Toggle */}
          <button
            onClick={() => {
              shouldScrollRef.current = !shouldScrollRef.current;
            }}
            className={`px-2 py-1 text-xs border border-gray-600 rounded ${
              shouldScrollRef.current
                ? 'bg-blue-600 hover:bg-blue-700'
                : 'bg-gray-700 hover:bg-gray-600'
            }`}
          >
            Auto-scroll
          </button>
        </div>
      </div>

      {/* Log Content */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-3 font-mono text-xs leading-relaxed"
        style={{ minHeight: '200px' }}
      >
        {filteredLogs.length === 0 ? (
          <div className="text-gray-500 text-center py-8">
            {connected ? 'Waiting for logs...' : 'Not connected'}
          </div>
        ) : (
          <div className="space-y-1">
            {filteredLogs.map((log, index) => (
              <LogLine
                key={index}
                content={log}
                showTimestamp={showTimestamps}
                index={index}
              />
            ))}
          </div>
        )}

        {/* Scroll to Bottom Button */}
        {!shouldScrollRef.current && filteredLogs.length > 0 && (
          <button
            onClick={() => {
              if (containerRef.current) {
                containerRef.current.scrollTop = containerRef.current.scrollHeight;
                shouldScrollRef.current = true;
              }
            }}
            className="fixed bottom-4 right-4 px-3 py-2 bg-blue-600 hover:bg-blue-700 text-white text-xs rounded-lg shadow-lg"
          >
            ↓ Scroll to bottom
          </button>
        )}
      </div>

      {/* Status Bar */}
      <div className="px-3 py-2 bg-gray-800 border-t border-gray-700 text-xs text-gray-400">
        <div className="flex justify-between">
          <span>{filteredLogs.length} lines</span>
          <span>{connected ? 'Streaming live' : 'Disconnected'}</span>
        </div>
      </div>
    </div>
  );
};

// Log line component with syntax highlighting
const LogLine: React.FC<{
  content: string;
  showTimestamp: boolean;
  index: number;
}> = ({ content, showTimestamp, index }) => {
  // Simple log level detection and coloring
  const getLogColor = (line: string): string => {
    const lowerLine = line.toLowerCase();
    if (lowerLine.includes('[error]') || lowerLine.includes('error:')) {
      return 'text-red-400';
    }
    if (lowerLine.includes('[warn]') || lowerLine.includes('warning:')) {
      return 'text-yellow-400';
    }
    if (lowerLine.includes('[info]') || lowerLine.includes('info:')) {
      return 'text-blue-400';
    }
    if (lowerLine.includes('[debug]') || lowerLine.includes('debug:')) {
      return 'text-gray-500';
    }
    if (lowerLine.includes('[success]') || lowerLine.includes('✓')) {
      return 'text-green-400';
    }
    return 'text-gray-300';
  };

  const color = getLogColor(content);

  return (
    <div className="flex gap-2 hover:bg-gray-800 px-1 py-0.5 rounded">
      <span className="text-gray-600 select-none w-12 text-right">
        {String(index + 1).padStart(4, '0')}
      </span>
      {showTimestamp && (
        <span className="text-gray-600">
          {new Date().toLocaleTimeString('en-US', { hour12: false })}
        </span>
      )}
      <span className={`flex-1 break-all ${color}`}>{content}</span>
    </div>
  );
};

export default RealtimeLogViewer;