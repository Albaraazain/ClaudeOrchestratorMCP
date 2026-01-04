import React, { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { LogViewer, AgentStatusBadge, ProgressBar } from '../components';
import { useAgentLogs, useAgentDetails } from '../hooks/useAgentLogs';
import { AgentFinding, AgentProgress } from '../types/agent';
import { formatDuration, getSeverityColor, getFindingIcon, getStatusColor } from '../utils/formatters';

export const AgentDetail: React.FC = () => {
  const { taskId, agentId } = useParams<{ taskId: string; agentId: string }>();
  const [activeTab, setActiveTab] = useState<'logs' | 'findings' | 'progress'>('logs');

  // Fetch agent details and logs
  const { agent, findings, progress, isLoading: detailsLoading, error: detailsError } = useAgentDetails({
    taskId: taskId || '',
    agentId: agentId || '',
    enabled: !!(taskId && agentId)
  });

  const { logs, isLoading: logsLoading, error: logsError, metadata } = useAgentLogs({
    taskId: taskId || '',
    agentId: agentId || '',
    enabled: !!(taskId && agentId) && activeTab === 'logs'
  });

  if (!taskId || !agentId) {
    return (
      <div className="min-h-screen bg-gray-900 text-gray-100 p-8">
        <div className="max-w-7xl mx-auto">
          <div className="text-center py-12">
            <h2 className="text-2xl font-bold text-red-400">Invalid Agent Details</h2>
            <p className="text-gray-400 mt-2">Missing task ID or agent ID</p>
            <Link to="/" className="mt-4 inline-block px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-md">
              Back to Dashboard
            </Link>
          </div>
        </div>
      </div>
    );
  }

  if (detailsLoading) {
    return (
      <div className="min-h-screen bg-gray-900 text-gray-100 p-8">
        <div className="max-w-7xl mx-auto">
          <div className="text-center py-12">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto"></div>
            <p className="text-gray-400 mt-4">Loading agent details...</p>
          </div>
        </div>
      </div>
    );
  }

  if (detailsError || !agent) {
    return (
      <div className="min-h-screen bg-gray-900 text-gray-100 p-8">
        <div className="max-w-7xl mx-auto">
          <div className="text-center py-12">
            <h2 className="text-2xl font-bold text-red-400">Error Loading Agent</h2>
            <p className="text-gray-400 mt-2">{detailsError || 'Agent not found'}</p>
            <Link to="/" className="mt-4 inline-block px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-md">
              Back to Dashboard
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100">
      {/* Header */}
      <div className="bg-gray-800 border-b border-gray-700 px-8 py-6">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center space-x-4 mb-2">
                <Link to="/" className="text-blue-400 hover:text-blue-300">
                  ← Back to Dashboard
                </Link>
                {agent.parent && (
                  <Link
                    to={`/agent/${taskId}/${agent.parent}`}
                    className="text-gray-400 hover:text-gray-300"
                  >
                    Parent: {agent.parent}
                  </Link>
                )}
              </div>

              <h1 className="text-2xl font-bold text-gray-100">{agent.agent_id}</h1>
              <p className="text-gray-400 mt-1">{agent.agent_type}</p>
            </div>

            <div className="text-right">
              <AgentStatusBadge status={agent.status} showIcon />
              <div className="text-gray-400 text-sm mt-2">
                Phase {agent.phase_index !== undefined ? agent.phase_index + 1 : 'N/A'}
              </div>
            </div>
          </div>

          {/* Progress Bar and Stats */}
          <div className="mt-6 grid grid-cols-1 md:grid-cols-4 gap-4">
            {/* Progress Bar */}
            <div className="md:col-span-2">
              <ProgressBar
                progress={agent.progress}
                color={agent.status === 'completed' ? 'green' : agent.status === 'blocked' ? 'orange' : 'blue'}
                animated
              />
            </div>

            {/* Duration */}
            <div className="bg-gray-800/50 rounded-lg p-3">
              <div className="text-xs text-gray-400 mb-1">Duration</div>
              <div className="text-lg font-semibold text-gray-100">
                {formatDuration(agent.start_time, agent.end_time)}
              </div>
            </div>

            {/* Process Info */}
            <div className="bg-gray-800/50 rounded-lg p-3">
              <div className="text-xs text-gray-400 mb-1">Process</div>
              <div className="text-sm text-gray-300">
                {agent.cursor_pid ? `PID: ${agent.cursor_pid}` :
                 agent.claude_pid ? `PID: ${agent.claude_pid}` :
                 agent.tmux_session ? `tmux: ${agent.tmux_session}` : 'N/A'}
              </div>
            </div>
          </div>

          {/* Latest message */}
          {agent.message && (
            <div className="mt-4 p-3 bg-gray-800/50 rounded-lg">
              <div className="text-xs text-gray-400 mb-1">Latest Message</div>
              <p className="text-gray-200">{agent.message}</p>
            </div>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-gray-800 border-b border-gray-700 px-8">
        <div className="max-w-7xl mx-auto">
          <div className="flex space-x-8">
            <button
              onClick={() => setActiveTab('logs')}
              className={`py-3 px-1 border-b-2 transition-colors ${
                activeTab === 'logs'
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              Live Logs
              {metadata && (
                <span className="ml-2 text-xs bg-gray-700 px-2 py-1 rounded-full">
                  {metadata.total_lines}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('findings')}
              className={`py-3 px-1 border-b-2 transition-colors ${
                activeTab === 'findings'
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              Findings
              {findings.length > 0 && (
                <span className="ml-2 text-xs bg-gray-700 px-2 py-1 rounded-full">
                  {findings.length}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('progress')}
              className={`py-3 px-1 border-b-2 transition-colors ${
                activeTab === 'progress'
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              Progress History
              {progress.length > 0 && (
                <span className="ml-2 text-xs bg-gray-700 px-2 py-1 rounded-full">
                  {progress.length}
                </span>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="p-8">
        <div className="max-w-7xl mx-auto">
          {/* Logs Tab */}
          {activeTab === 'logs' && (
            <div className="h-[calc(100vh-400px)]">
              {logsError ? (
                <div className="text-center py-12">
                  <p className="text-red-400">Error loading logs: {logsError}</p>
                </div>
              ) : (
                <LogViewer logs={logs} className="h-full" />
              )}
            </div>
          )}

          {/* Findings Tab */}
          {activeTab === 'findings' && (
            <div className="space-y-4">
              {findings.length === 0 ? (
                <div className="text-center py-12">
                  <p className="text-gray-500">No findings reported yet</p>
                </div>
              ) : (
                findings.map((finding: AgentFinding, index: number) => (
                  <div
                    key={`${finding.timestamp}-${index}`}
                    className={`border rounded-lg p-4 ${getSeverityColor(finding.severity)}`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex items-start space-x-3">
                        <span className="text-2xl">{getFindingIcon(finding.finding_type)}</span>
                        <div className="flex-1">
                          <div className="flex items-center space-x-3 mb-2">
                            <span className="font-semibold uppercase text-sm">
                              {finding.finding_type}
                            </span>
                            <span className="text-xs px-2 py-1 bg-gray-800 rounded">
                              {finding.severity}
                            </span>
                          </div>
                          <p className="text-gray-200">{finding.message}</p>
                          {finding.data && Object.keys(finding.data).length > 0 && (
                            <pre className="mt-3 p-3 bg-gray-900 rounded text-xs overflow-x-auto">
                              {JSON.stringify(finding.data, null, 2)}
                            </pre>
                          )}
                        </div>
                      </div>
                      <span className="text-xs text-gray-500">
                        {new Date(finding.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {/* Progress Tab */}
          {activeTab === 'progress' && (
            <div className="space-y-2">
              {progress.length === 0 ? (
                <div className="text-center py-12">
                  <p className="text-gray-500">No progress updates yet</p>
                </div>
              ) : (
                <div className="relative">
                  {/* Timeline line */}
                  <div className="absolute left-8 top-0 bottom-0 w-0.5 bg-gray-700"></div>

                  {progress.map((update: AgentProgress, index: number) => (
                    <div key={`${update.timestamp}-${index}`} className="relative flex items-start">
                      {/* Timeline dot */}
                      <div className={`absolute left-7 w-3 h-3 rounded-full border-2 border-gray-700 ${
                        update.status === 'completed' ? 'bg-green-500' :
                        update.status === 'working' ? 'bg-blue-500' :
                        update.status === 'blocked' ? 'bg-orange-500' :
                        update.status === 'failed' ? 'bg-red-500' :
                        'bg-gray-500'
                      }`}></div>

                      {/* Content */}
                      <div className="ml-16 pb-6 flex-1">
                        <div className="bg-gray-800 rounded-lg p-4">
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center space-x-3">
                              <span className={`px-2 py-1 rounded text-xs font-semibold ${getStatusColor(update.status)}`}>
                                {update.status}
                              </span>
                              <span className="text-sm text-gray-400">
                                {update.progress}% complete
                              </span>
                            </div>
                            <span className="text-xs text-gray-500">
                              {new Date(update.timestamp).toLocaleString()}
                            </span>
                          </div>
                          <p className="text-gray-200">{update.message}</p>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};