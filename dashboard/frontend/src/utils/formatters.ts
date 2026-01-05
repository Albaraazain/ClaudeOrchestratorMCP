// Utility functions for formatting data

export const formatTimestamp = (timestamp: string): string => {
  const date = new Date(timestamp);
  return date.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
};

export const formatDuration = (startTime?: string, endTime?: string | null): string => {
  if (!startTime) return 'N/A';

  const start = new Date(startTime).getTime();
  const end = endTime ? new Date(endTime).getTime() : Date.now();
  const duration = end - start;

  const hours = Math.floor(duration / 3600000);
  const minutes = Math.floor((duration % 3600000) / 60000);
  const seconds = Math.floor((duration % 60000) / 1000);

  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}s`;
  } else if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  } else {
    return `${seconds}s`;
  }
};

export const formatBytes = (bytes: number): string => {
  if (bytes === 0) return '0 Bytes';

  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
};

export const getStatusColor = (status: string): string => {
  const statusMap: Record<string, string> = {
    completed: 'text-green-400 bg-green-900/30',
    working: 'text-blue-400 bg-blue-900/30',
    running: 'text-cyan-400 bg-cyan-900/30',
    blocked: 'text-orange-400 bg-orange-900/30',
    failed: 'text-red-400 bg-red-900/30',
    error: 'text-red-400 bg-red-900/30',
    pending: 'text-gray-400 bg-gray-900/30',
  };

  return statusMap[status.toLowerCase()] || 'text-gray-400 bg-gray-900/30';
};

export const getSeverityColor = (severity: string): string => {
  const severityMap: Record<string, string> = {
    critical: 'text-red-500 bg-red-900/20 border-red-700',
    high: 'text-orange-500 bg-orange-900/20 border-orange-700',
    medium: 'text-yellow-500 bg-yellow-900/20 border-yellow-700',
    low: 'text-blue-500 bg-blue-900/20 border-blue-700',
  };

  return severityMap[severity.toLowerCase()] || 'text-gray-500 bg-gray-900/20 border-gray-700';
};

export const getFindingIcon = (type: string): string => {
  const iconMap: Record<string, string> = {
    issue: '⚠️',
    solution: '✅',
    insight: '💡',
    recommendation: '📝',
    blocker: '🚫',
  };

  return iconMap[type.toLowerCase()] || '📌';
};

export const getLogTypeColor = (type: string): string => {
  const typeMap: Record<string, string> = {
    assistant: 'text-blue-400',
    tool_call: 'text-sky-400',
    tool_result: 'text-green-400',
    error: 'text-red-400',
    system: 'text-gray-400',
  };

  return typeMap[type.toLowerCase()] || 'text-gray-300';
};