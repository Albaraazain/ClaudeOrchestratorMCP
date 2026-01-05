import React from 'react';
import { format } from 'date-fns';
import clsx from 'clsx';

interface Phase {
  id: string;
  order: number;
  name: string;
  description?: string;
  status: 'PENDING' | 'ACTIVE' | 'AWAITING_REVIEW' | 'UNDER_REVIEW' |
          'APPROVED' | 'REJECTED' | 'REVISING' | 'ESCALATED';
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

interface PhaseTimelineProps {
  phases: Phase[];
  currentPhaseIndex: number;
  onPhaseClick?: (index: number) => void;
  selectedPhase?: number | null;
}

const PhaseTimeline: React.FC<PhaseTimelineProps> = ({
  phases,
  currentPhaseIndex,
  onPhaseClick,
  selectedPhase
}) => {
  const getPhaseIcon = (status: Phase['status']) => {
    switch (status) {
      case 'APPROVED':
        return (
          <svg className="w-5 h-5 text-green-600" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
          </svg>
        );
      case 'REJECTED':
        return (
          <svg className="w-5 h-5 text-red-600" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
          </svg>
        );
      case 'ACTIVE':
        return (
          <div className="w-3 h-3 bg-blue-600 rounded-full animate-pulse"></div>
        );
      case 'UNDER_REVIEW':
      case 'AWAITING_REVIEW':
        return (
          <svg className="w-5 h-5 text-yellow-600" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
          </svg>
        );
      default:
        return <div className="w-3 h-3 bg-gray-300 rounded-full"></div>;
    }
  };

  const getPhaseColors = (status: Phase['status'], isSelected: boolean) => {
    const baseClasses = 'relative flex flex-col items-center p-4 cursor-pointer transition-all';

    let statusClasses = '';
    switch (status) {
      case 'ACTIVE':
        statusClasses = 'bg-blue-50 border-blue-500';
        break;
      case 'APPROVED':
        statusClasses = 'bg-green-50 border-green-500';
        break;
      case 'REJECTED':
        statusClasses = 'bg-red-50 border-red-500';
        break;
      case 'AWAITING_REVIEW':
      case 'UNDER_REVIEW':
        statusClasses = 'bg-yellow-50 border-yellow-500';
        break;
      case 'REVISING':
        statusClasses = 'bg-orange-50 border-orange-500';
        break;
      case 'ESCALATED':
        statusClasses = 'bg-sky-50 border-sky-500';
        break;
      default:
        statusClasses = 'bg-gray-50 border-gray-300';
    }

    const selectedClasses = isSelected ? 'ring-2 ring-blue-500 ring-offset-2' : '';
    const borderStyle = status === 'PENDING' ? 'border-dashed' : 'border-solid';

    return clsx(baseClasses, statusClasses, selectedClasses, 'border-2', borderStyle, 'rounded-lg');
  };

  const getConnectorClass = (phase: Phase, nextPhase?: Phase) => {
    if (!nextPhase) return 'bg-gray-300';

    if (phase.status === 'APPROVED') {
      return 'bg-green-500';
    } else if (nextPhase.status !== 'PENDING') {
      return 'bg-blue-500';
    }
    return 'bg-gray-300';
  };

  return (
    <div className="relative">
      <div className="flex overflow-x-auto pb-4">
        {phases.map((phase, index) => (
          <div key={phase.id} className="flex items-center">
            {/* Phase Node */}
            <div
              className={getPhaseColors(phase.status, selectedPhase === index)}
              onClick={() => onPhaseClick?.(index)}
              style={{ minWidth: '160px' }}
            >
              {/* Icon */}
              <div className="mb-2">
                {getPhaseIcon(phase.status)}
              </div>

              {/* Phase Name */}
              <div className="text-sm font-medium text-gray-900 text-center">
                {phase.name}
              </div>

              {/* Phase Order */}
              <div className="text-xs text-gray-500 mt-1">
                Phase {phase.order + 1}
              </div>

              {/* Status Badge */}
              <div className={clsx(
                'mt-2 px-2 py-1 text-xs rounded-full font-medium',
                phase.status === 'ACTIVE' && 'bg-blue-100 text-blue-700',
                phase.status === 'APPROVED' && 'bg-green-100 text-green-700',
                phase.status === 'REJECTED' && 'bg-red-100 text-red-700',
                phase.status === 'PENDING' && 'bg-gray-100 text-gray-700',
                phase.status === 'AWAITING_REVIEW' && 'bg-yellow-100 text-yellow-700',
                phase.status === 'UNDER_REVIEW' && 'bg-yellow-100 text-yellow-700',
                phase.status === 'REVISING' && 'bg-orange-100 text-orange-700',
                phase.status === 'ESCALATED' && 'bg-sky-100 text-sky-700'
              )}>
                {phase.status}
              </div>

              {/* Timing Info */}
              {phase.started_at && (
                <div className="text-xs text-gray-400 mt-2">
                  Started: {format(new Date(phase.started_at), 'HH:mm')}
                </div>
              )}
              {phase.completed_at && (
                <div className="text-xs text-gray-400">
                  Completed: {format(new Date(phase.completed_at), 'HH:mm')}
                </div>
              )}

              {/* Description Tooltip */}
              {phase.description && (
                <div className="absolute -bottom-8 left-1/2 transform -translate-x-1/2 hidden group-hover:block">
                  <div className="bg-gray-800 text-white text-xs rounded px-2 py-1 whitespace-nowrap">
                    {phase.description}
                  </div>
                </div>
              )}
            </div>

            {/* Connector Line */}
            {index < phases.length - 1 && (
              <div className="relative w-12">
                <div className={clsx(
                  'absolute top-1/2 w-full h-1 transform -translate-y-1/2',
                  getConnectorClass(phase, phases[index + 1])
                )}>
                  {/* Arrow */}
                  <svg
                    className="absolute right-0 top-1/2 transform -translate-y-1/2 w-3 h-3 text-current"
                    fill="currentColor"
                    viewBox="0 0 12 12"
                  >
                    <path d="M0 5h8.5L5.5 2l1.5-1.5L12 6l-5 5L5.5 9.5 8.5 7H0z" />
                  </svg>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Legend */}
      <div className="mt-6 flex flex-wrap gap-4 text-xs">
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 bg-gray-300 rounded-full"></div>
          <span className="text-gray-600">Pending</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 bg-blue-600 rounded-full animate-pulse"></div>
          <span className="text-gray-600">Active</span>
        </div>
        <div className="flex items-center gap-1">
          <svg className="w-4 h-4 text-yellow-600" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" />
          </svg>
          <span className="text-gray-600">Under Review</span>
        </div>
        <div className="flex items-center gap-1">
          <svg className="w-4 h-4 text-green-600" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
          </svg>
          <span className="text-gray-600">Approved</span>
        </div>
        <div className="flex items-center gap-1">
          <svg className="w-4 h-4 text-red-600" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clipRule="evenodd" />
          </svg>
          <span className="text-gray-600">Rejected</span>
        </div>
      </div>
    </div>
  );
};

export default PhaseTimeline;