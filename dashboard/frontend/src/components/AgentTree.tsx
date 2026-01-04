import React, { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { format } from 'date-fns';
import clsx from 'clsx';

interface Agent {
  id: string;
  type: string;
  tmux_session: string;
  parent: string;
  depth: number;
  phase_index: number;
  status: 'running' | 'working' | 'blocked' | 'completed' | 'failed' | 'error';
  started_at: string;
  completed_at?: string;
  progress: number;
  last_update: string;
  prompt: string;
}

interface AgentTreeProps {
  agents: Agent[];
  hierarchy: { [key: string]: string[] };
  taskId: string;
}

interface TreeNode {
  agent: Agent;
  children: TreeNode[];
  isExpanded: boolean;
}

const AgentTree: React.FC<AgentTreeProps> = ({ agents, hierarchy, taskId }) => {
  const navigate = useNavigate();
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set(['orchestrator']));

  // Build tree structure
  const tree = useMemo(() => {
    const agentMap = new Map<string, Agent>();
    agents.forEach(agent => agentMap.set(agent.id, agent));

    const buildNode = (agentId: string): TreeNode | null => {
      const agent = agentMap.get(agentId);
      if (!agent) return null;

      const children = (hierarchy[agentId] || [])
        .map(childId => buildNode(childId))
        .filter((node): node is TreeNode => node !== null);

      return {
        agent,
        children,
        isExpanded: expandedNodes.has(agentId)
      };
    };

    // Find root agents (those with parent = 'orchestrator')
    const roots = agents
      .filter(agent => agent.parent === 'orchestrator')
      .map(agent => buildNode(agent.id))
      .filter((node): node is TreeNode => node !== null);

    return roots;
  }, [agents, hierarchy, expandedNodes]);

  const toggleNode = (agentId: string) => {
    setExpandedNodes(prev => {
      const newSet = new Set(prev);
      if (newSet.has(agentId)) {
        newSet.delete(agentId);
      } else {
        newSet.add(agentId);
      }
      return newSet;
    });
  };

  const handleAgentClick = (agentId: string) => {
    navigate(`/tasks/${taskId}/agents/${agentId}`);
  };

  const getStatusIcon = (status: Agent['status']) => {
    switch (status) {
      case 'running':
      case 'working':
        return (
          <div className="w-2 h-2 bg-blue-600 rounded-full animate-pulse"></div>
        );
      case 'completed':
        return (
          <svg className="w-4 h-4 text-green-600" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
          </svg>
        );
      case 'failed':
      case 'error':
        return (
          <svg className="w-4 h-4 text-red-600" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
        );
      case 'blocked':
        return (
          <svg className="w-4 h-4 text-yellow-600" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
          </svg>
        );
      default:
        return <div className="w-2 h-2 bg-gray-400 rounded-full"></div>;
    }
  };

  const getStatusColor = (status: Agent['status']) => {
    switch (status) {
      case 'running':
      case 'working':
        return 'bg-blue-50 border-blue-200';
      case 'completed':
        return 'bg-green-50 border-green-200';
      case 'failed':
      case 'error':
        return 'bg-red-50 border-red-200';
      case 'blocked':
        return 'bg-yellow-50 border-yellow-200';
      default:
        return 'bg-gray-50 border-gray-200';
    }
  };

  const renderNode = (node: TreeNode, level: number = 0): JSX.Element => {
    const { agent, children } = node;
    const hasChildren = children.length > 0;
    const isExpanded = expandedNodes.has(agent.id);

    return (
      <div key={agent.id} className="relative">
        {/* Connection line for child nodes */}
        {level > 0 && (
          <div
            className="absolute left-0 top-0 w-6 h-6 border-l-2 border-b-2 border-gray-300"
            style={{
              left: `${(level - 1) * 24}px`,
              top: '-12px'
            }}
          />
        )}

        {/* Agent Node */}
        <div
          className={clsx(
            'flex items-center gap-3 p-3 rounded-lg border transition-all hover:shadow-md',
            getStatusColor(agent.status),
            'cursor-pointer'
          )}
          style={{ marginLeft: `${level * 24}px` }}
        >
          {/* Expand/Collapse Button */}
          {hasChildren && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                toggleNode(agent.id);
              }}
              className="w-5 h-5 flex items-center justify-center rounded hover:bg-gray-200"
            >
              <svg
                className={clsx(
                  'w-3 h-3 text-gray-600 transition-transform',
                  isExpanded && 'rotate-90'
                )}
                fill="currentColor"
                viewBox="0 0 20 20"
              >
                <path fillRule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clipRule="evenodd" />
              </svg>
            </button>
          )}
          {!hasChildren && <div className="w-5" />}

          {/* Status Icon */}
          <div className="flex-shrink-0">
            {getStatusIcon(agent.status)}
          </div>

          {/* Agent Info */}
          <div
            className="flex-1 min-w-0"
            onClick={() => handleAgentClick(agent.id)}
          >
            <div className="flex items-center gap-2">
              <span className="font-medium text-sm text-gray-900">
                {agent.type}
              </span>
              <span className="text-xs text-gray-500 font-mono">
                {agent.id}
              </span>
            </div>

            {/* Prompt Preview */}
            <div className="text-xs text-gray-600 truncate mt-1">
              {agent.prompt}
            </div>

            {/* Progress Bar */}
            <div className="mt-2">
              <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
                <span>{agent.status}</span>
                <span>{agent.progress}%</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-1.5">
                <div
                  className={clsx(
                    'h-1.5 rounded-full transition-all',
                    agent.status === 'completed' && 'bg-green-600',
                    (agent.status === 'running' || agent.status === 'working') && 'bg-blue-600',
                    (agent.status === 'failed' || agent.status === 'error') && 'bg-red-600',
                    agent.status === 'blocked' && 'bg-yellow-600'
                  )}
                  style={{ width: `${agent.progress}%` }}
                />
              </div>
            </div>

            {/* Timing Info */}
            <div className="flex gap-4 mt-2 text-xs text-gray-500">
              <span>
                Started: {format(new Date(agent.started_at), 'HH:mm:ss')}
              </span>
              {agent.completed_at && (
                <span>
                  Completed: {format(new Date(agent.completed_at), 'HH:mm:ss')}
                </span>
              )}
              <span>
                Updated: {format(new Date(agent.last_update), 'HH:mm:ss')}
              </span>
            </div>

            {/* Additional Info */}
            <div className="flex gap-4 mt-1 text-xs">
              <span className="text-gray-500">
                Phase: <span className="font-medium">{agent.phase_index + 1}</span>
              </span>
              <span className="text-gray-500">
                Depth: <span className="font-medium">{agent.depth}</span>
              </span>
              <span className="text-gray-500">
                Session: <span className="font-mono">{agent.tmux_session}</span>
              </span>
            </div>
          </div>

          {/* Action Buttons */}
          <div className="flex gap-2">
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleAgentClick(agent.id);
              }}
              className="p-1 rounded hover:bg-gray-200"
              title="View Details"
            >
              <svg className="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                // Navigate to logs view
                navigate(`/tasks/${taskId}/agents/${agent.id}/logs`);
              }}
              className="p-1 rounded hover:bg-gray-200"
              title="View Logs"
            >
              <svg className="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </button>
          </div>
        </div>

        {/* Render Children */}
        {hasChildren && isExpanded && (
          <div className="relative mt-3">
            {/* Vertical connection line for multiple children */}
            {children.length > 1 && (
              <div
                className="absolute left-0 top-0 bottom-0 w-px bg-gray-300"
                style={{ left: `${level * 24 + 12}px` }}
              />
            )}
            {children.map(child => renderNode(child, level + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-3">
      {tree.length === 0 ? (
        <div className="text-center py-8 text-gray-500">
          No agents spawned yet
        </div>
      ) : (
        tree.map(node => renderNode(node))
      )}
    </div>
  );
};

export default AgentTree;