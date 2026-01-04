import React, { useRef, useEffect, useState } from 'react';
import { LogEntry } from '../types/agent';

interface LogViewerProps {
  logs: LogEntry[];
  className?: string;
}

export const LogViewer: React.FC<LogViewerProps> = ({ logs, className = '' }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [filteredLogs, setFilteredLogs] = useState<LogEntry[]>(logs);

  // Filter logs based on search term
  useEffect(() => {
    if (!searchTerm) {
      setFilteredLogs(logs);
    } else {
      const term = searchTerm.toLowerCase();
      setFilteredLogs(logs.filter(log =>
        log.content.toLowerCase().includes(term) ||
        log.type.toLowerCase().includes(term)
      ));
    }
  }, [logs, searchTerm]);

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [filteredLogs, autoScroll]);

  const getLogTypeColor = (type: LogEntry['type']) => {
    switch (type) {
      case 'assistant':
        return 'text-blue-400';
      case 'tool_call':
        return 'text-purple-400';
      case 'tool_result':
        return 'text-green-400';
      case 'error':
        return 'text-red-400';
      case 'system':
        return 'text-gray-400';
      default:
        return 'text-gray-300';
    }
  };

  const handleCopy = (content: string) => {
    navigator.clipboard.writeText(content);
    // Could add a toast notification here
  };

  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    // Check if user is near the bottom (within 50px)
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 50;
    setAutoScroll(isNearBottom);
  };

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      fractionalSecondDigits: 3
    });
  };

  const formatContent = (content: string) => {
    // Detect and format code blocks
    if (content.includes('```')) {
      return content.split('```').map((part, index) => {
        if (index % 2 === 1) {
          // This is a code block
          const [lang, ...code] = part.split('\n');
          return (
            <pre key={index} className="bg-gray-900 p-2 rounded mt-1 mb-1 overflow-x-auto">
              <code className={`language-${lang || 'plaintext'}`}>
                {code.join('\n')}
              </code>
            </pre>
          );
        }
        return <span key={index}>{part}</span>;
      });
    }
    return content;
  };

  return (
    <div className={`flex flex-col h-full bg-gray-800 rounded-lg ${className}`}>
      {/* Header with search and controls */}
      <div className="flex items-center justify-between p-4 border-b border-gray-700">
        <div className="flex items-center space-x-4">
          <h3 className="text-lg font-semibold text-gray-100">Live Logs</h3>
          <span className="text-sm text-gray-400">
            {filteredLogs.length} entries
          </span>
        </div>

        <div className="flex items-center space-x-4">
          <input
            type="text"
            placeholder="Search logs..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="px-3 py-1 bg-gray-700 text-gray-100 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          />

          <button
            onClick={() => setAutoScroll(!autoScroll)}
            className={`px-3 py-1 rounded-md transition-colors ${
              autoScroll
                ? 'bg-blue-600 text-white hover:bg-blue-700'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            {autoScroll ? 'Auto-scroll ON' : 'Auto-scroll OFF'}
          </button>
        </div>
      </div>

      {/* Log container */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-4 space-y-2 font-mono text-sm"
      >
        {filteredLogs.length === 0 ? (
          <div className="text-gray-500 text-center py-8">
            {searchTerm ? 'No logs match your search' : 'No logs available'}
          </div>
        ) : (
          filteredLogs.map((log, index) => (
            <div
              key={`${log.timestamp}-${index}`}
              className="group hover:bg-gray-750 rounded p-2 transition-colors"
            >
              <div className="flex items-start space-x-2">
                {/* Timestamp */}
                <span className="text-gray-500 text-xs whitespace-nowrap">
                  {formatTimestamp(log.timestamp)}
                </span>

                {/* Type badge */}
                <span className={`text-xs font-semibold uppercase ${getLogTypeColor(log.type)}`}>
                  [{log.type}]
                </span>

                {/* Content */}
                <div className="flex-1 text-gray-200 break-words whitespace-pre-wrap">
                  {formatContent(log.content)}
                </div>

                {/* Copy button (shown on hover) */}
                <button
                  onClick={() => handleCopy(log.content)}
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-gray-700 rounded"
                  title="Copy log entry"
                >
                  <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                  </svg>
                </button>
              </div>

              {/* Metadata if present */}
              {log.metadata && Object.keys(log.metadata).length > 0 && (
                <div className="mt-1 ml-20 text-xs text-gray-500">
                  {Object.entries(log.metadata).map(([key, value]) => (
                    <span key={key} className="mr-4">
                      {key}: <span className="text-gray-400">{JSON.stringify(value)}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
};