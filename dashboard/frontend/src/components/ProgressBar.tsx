import React from 'react';

interface ProgressBarProps {
  progress: number;
  showLabel?: boolean;
  className?: string;
  height?: string;
  animated?: boolean;
  color?: 'blue' | 'green' | 'orange' | 'red' | 'sky';
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  progress,
  showLabel = true,
  className = '',
  height = 'h-3',
  animated = true,
  color = 'blue'
}) => {
  const colorMap = {
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    orange: 'bg-orange-500',
    red: 'bg-red-500',
    sky: 'bg-sky-500'
  };

  const progressColor = colorMap[color];

  return (
    <div className={className}>
      {showLabel && (
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-gray-400">Progress</span>
          <span className="text-sm font-semibold text-gray-300">{progress}%</span>
        </div>
      )}
      <div className={`w-full bg-gray-700 rounded-full ${height} overflow-hidden`}>
        <div
          className={`${progressColor} ${height} rounded-full ${
            animated ? 'transition-all duration-500' : ''
          }`}
          style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
        >
          {animated && progress < 100 && progress > 0 && (
            <div className="h-full bg-white/10 animate-pulse"></div>
          )}
        </div>
      </div>
    </div>
  );
};