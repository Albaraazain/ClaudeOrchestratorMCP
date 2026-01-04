import React from 'react';
import { getStatusColor } from '../utils/formatters';

interface AgentStatusBadgeProps {
  status: string;
  className?: string;
  showIcon?: boolean;
}

export const AgentStatusBadge: React.FC<AgentStatusBadgeProps> = ({
  status,
  className = '',
  showIcon = false
}) => {
  const getStatusIcon = (status: string): string => {
    const iconMap: Record<string, string> = {
      completed: '✓',
      working: '⚡',
      running: '▶',
      blocked: '⏸',
      failed: '✗',
      error: '!',
      pending: '◷',
    };

    return iconMap[status.toLowerCase()] || '•';
  };

  return (
    <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-semibold ${getStatusColor(status)} ${className}`}>
      {showIcon && (
        <span className="mr-1">{getStatusIcon(status)}</span>
      )}
      {status.toUpperCase()}
    </span>
  );
};