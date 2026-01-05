import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Copy, Search, ArrowDownCircle, X } from 'lucide-react';

type LogEntry = {
  timestamp: string;
  type: string;
  content: string;
  metadata?: Record<string, any>;
};

interface LogViewerProps {
  logs: LogEntry[];
  className?: string;
}

export const LogViewer: React.FC<LogViewerProps> = ({ logs, className = '' }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');

  const filteredLogs = useMemo(() => {
    if (!searchTerm) return logs;
    const term = searchTerm.toLowerCase();
    return logs.filter((log) => {
      return (
        log.content.toLowerCase().includes(term) ||
        log.type.toLowerCase().includes(term)
      );
    });
  }, [logs, searchTerm]);

  useEffect(() => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    setIsAtBottom(scrollHeight - scrollTop - clientHeight < 50);
  }, [filteredLogs.length]);

  const getLogTypeColor = (type: LogEntry['type']) => {
    switch (type) {
      case 'assistant': return 'text-cyan-400 font-bold';
      case 'user': return 'text-green-400';
      case 'tool_call': return 'text-sky-400 font-bold';
      case 'tool_result': return 'text-emerald-400';
      case 'error': return 'text-red-400 font-bold';
      case 'system': return 'text-amber-400';
      default: return 'text-gray-400';
    }
  };

  const handleCopy = async (content: string) => {
    try {
      await navigator.clipboard.writeText(content);
    } catch (e) {
      // Clipboard can fail on insecure contexts or denied permissions; fail silently.
      console.warn('Failed to copy to clipboard', e);
    }
  };

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'auto') => {
    if (!containerRef.current) return;
    containerRef.current.scrollTo({ top: containerRef.current.scrollHeight, behavior });
  }, []);

  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    const isNearBottom = scrollHeight - scrollTop - clientHeight < 50;
    setIsAtBottom(isNearBottom);
  };

  const formatTimestamp = (timestamp: string) => {
    try {
      const date = new Date(timestamp);
      return date.toLocaleTimeString('en-US', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        fractionalSecondDigits: 3
      });
    } catch (e) {
      return timestamp;
    }
  };

  const formatContent = (content: string) => {
    if (content.includes('```')) {
      return content.split('```').map((part, index) => {
        if (index % 2 === 1) {
          const [lang, ...code] = part.split('\n');
          return (
            <div key={index} className="bg-black/50 border border-gray-700 rounded my-2 overflow-hidden">
              <div className="bg-white/5 px-2 py-1 text-xs text-gray-400 select-none border-b border-gray-700 flex justify-between">
                <span>{lang || 'code'}</span>
                <button onClick={() => handleCopy(code.join('\n'))} className="hover:text-white"><Copy className="w-3 h-3" /></button>
              </div>
              <pre className="p-3 overflow-x-auto text-sm">
                <code className={`language-${lang || 'plaintext'}`}>
                  {code.join('\n')}
                </code>
              </pre>
            </div>
          );
        }
        return <span key={index}>{part}</span>;
      });
    }
    return content;
  };

  return (
    <div className={`flex flex-col h-full min-h-0 bg-[#0d1117] border border-gray-800 rounded-xl overflow-hidden shadow-inner ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800 bg-gray-900/50">
        <div className="flex items-center gap-3">
           <div className="flex items-center gap-2 text-gray-400 text-xs font-mono">
              <span className="w-2 h-2 rounded-full bg-success animate-pulse"></span>
              Live Connection
           </div>
           <div className="h-4 w-px bg-gray-700"></div>
           <span className="text-xs text-gray-400 font-mono">
             {filteredLogs.length} lines
           </span>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
             <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500" />
             <input
               type="text"
               placeholder="Grep logs..."
               value={searchTerm}
               onChange={(e) => setSearchTerm(e.target.value)}
               className="pl-8 pr-3 py-1.5 bg-black/20 border border-gray-700 rounded-md text-xs text-white placeholder-gray-500 focus:outline-none focus:border-sky-500/50 transition-all w-48"
             />
             {searchTerm && (
               <button
                 type="button"
                 onClick={() => setSearchTerm('')}
                 className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white transition-colors"
                 title="Clear search"
               >
                 <X className="w-3.5 h-3.5" />
               </button>
             )}
          </div>

          <button
            type="button"
            onClick={() => scrollToBottom('auto')}
            disabled={isAtBottom}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all border ${
              isAtBottom
                ? 'bg-transparent text-gray-600 border-gray-700 cursor-not-allowed'
                : 'bg-transparent text-gray-400 border-gray-600 hover:text-white hover:border-gray-500'
            }`}
          >
            <ArrowDownCircle className="w-3.5 h-3.5" />
            Bottom
          </button>
        </div>
      </div>

      {/* Log container */}
      <div className="relative flex-1 min-h-0">
        <div
          ref={containerRef}
          onScroll={handleScroll}
          className="h-full overflow-y-auto p-4 space-y-1 font-mono text-sm leading-relaxed"
        >
          {filteredLogs.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-gray-500">
              <Search className="w-12 h-12 mb-2" />
              <p>{searchTerm ? 'No matches found' : 'Waiting for logs...'}</p>
            </div>
          ) : (
            filteredLogs.map((log, index) => (
              <div
                key={`${log.timestamp}-${index}`}
                className="group hover:bg-white/5 rounded px-2 py-0.5 transition-colors -mx-2 flex items-start gap-3"
              >
                <span className="text-gray-500 text-xs whitespace-nowrap pt-1 select-none w-20 text-right">
                  {formatTimestamp(log.timestamp)}
                </span>

                <span className={`text-xs font-bold uppercase w-16 pt-1 select-none text-right ${getLogTypeColor(log.type)}`}>
                  {log.type}
                </span>

                <div className="flex-1 text-gray-200 break-words whitespace-pre-wrap min-w-0">
                  {formatContent(log.content)}

                  {log.metadata && Object.keys(log.metadata).length > 0 && (
                    <div className="mt-1 p-2 bg-white/5 rounded border border-white/5 text-xs text-gray-400 font-mono overflow-x-auto">
                      {JSON.stringify(log.metadata, null, 2)}
                    </div>
                  )}
                </div>

                <button
                  onClick={() => handleCopy(log.content)}
                  className="opacity-0 group-hover:opacity-100 p-1 hover:bg-white/10 rounded text-gray-500 hover:text-white transition-all"
                  title="Copy line"
                >
                  <Copy className="w-3.5 h-3.5" />
                </button>
              </div>
            ))
          )}
        </div>

        {!isAtBottom && (
          <button
            type="button"
            onClick={() => {
              scrollToBottom('auto');
            }}
            className="absolute bottom-4 right-4 px-3 py-2 rounded-lg bg-primary/90 hover:bg-primary text-white text-xs font-medium shadow-lg shadow-black/30 border border-white/10"
            title="Scroll to bottom"
          >
            ↓ Bottom
          </button>
        )}
      </div>
    </div>
  );
};
