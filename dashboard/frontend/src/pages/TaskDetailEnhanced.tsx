/**
 * Enhanced Task Detail Page with Real-Time Updates
 * Uses the centralized WebSocket service and real-time store
 */

import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { format } from 'date-fns';
import axios from 'axios';
import PhaseTimeline from '../components/PhaseTimeline';
import AgentTree from '../components/AgentTree';
import { useTaskUpdates } from '../hooks/useWebSocket';
import { useRealtimeStore } from '../stores/realtimeStore';

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
  claude_pid?: number;
  cursor_pid?: number;
}

interface TaskDetails {
  task_id: string;
  task_description: string;
  created_at: string;
  workspace: string;
  workspace_base: string;
  client_cwd: string;
  status: 'INITIALIZED' | 'ACTIVE' | 'COMPLETED' | 'FAILED';
  priority: 'P0' | 'P1' | 'P2' | 'P3' | 'P4';
  phases: Phase[];
  current_phase_index: number;
  agents: Agent[];
  agent_hierarchy: { [key: string]: string[] };
  total_spawned: number;
  active_count: number;
  completed_count: number;
}

const TaskDetailEnhanced: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const [task, setTask] = useState<TaskDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPhase, setSelectedPhase] = useState<number | null>(null);

  // Use the enhanced WebSocket hook
  const { connected, taskUpdates } = useTaskUpdates(taskId);

  // Access real-time store for flashing indicators
  const { flashingTasks, flashingAgents, processWebSocketMessage } = useRealtimeStore();

  // Fetch initial task details
  useEffect(() => {
    if (!taskId) return;

    const fetchTask = async () => {
      try {
        setLoading(true);
        const response = await axios.get<TaskDetails>(`http://localhost:8000/api/tasks/${taskId}`);
        setTask(response.data);
        setError(null);
      } catch (err) {
        console.error('Failed to fetch task:', err);
        setError('Failed to load task details');
      } finally {
        setLoading(false);
      }
    };

    fetchTask();
  }, [taskId]);

  // Process WebSocket updates
  useEffect(() => {
    taskUpdates.forEach(message => {
      // Process through the store for side effects
      processWebSocketMessage(message);

      // Update local state based on message type
      if (message.type === 'task_update' && message.data.task_id === taskId) {
        setTask(prev => ({
          ...prev!,
          ...message.data
        }));
      } else if (message.type === 'agent_update' && message.data.task_id === taskId) {
        setTask(prev => {
          if (!prev) return prev;
          const updatedAgents = prev.agents.map(agent =>
            agent.id === message.data.agent_id
              ? { ...agent, ...message.data }
              : agent
          );
          return { ...prev, agents: updatedAgents };
        });
      } else if (message.type === 'phase_change' && message.data.task_id === taskId) {
        setTask(prev => {
          if (!prev) return prev;
          const phaseIndex = message.data.phase_index;
          const updatedPhases = [...prev.phases];
          if (updatedPhases[phaseIndex]) {
            updatedPhases[phaseIndex] = {
              ...updatedPhases[phaseIndex],
              status: message.data.new_status
            };
          }
          return {
            ...prev,
            phases: updatedPhases,
            current_phase_index: message.data.current_phase_index || prev.current_phase_index
          };
        });
      }
    });
  }, [taskUpdates, taskId, processWebSocketMessage]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error || !task) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-red-600">{error || 'Task not found'}</div>
      </div>
    );
  }

  // Filter agents by selected phase
  const filteredAgents = selectedPhase !== null
    ? task.agents.filter(agent => agent.phase_index === selectedPhase)
    : task.agents;

  // Get status color
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'ACTIVE':
      case 'running':
      case 'working':
        return 'text-blue-600 bg-blue-50';
      case 'COMPLETED':
      case 'completed':
        return 'text-green-600 bg-green-50';
      case 'FAILED':
      case 'failed':
      case 'error':
        return 'text-red-600 bg-red-50';
      case 'blocked':
        return 'text-yellow-600 bg-yellow-50';
      default:
        return 'text-gray-600 bg-gray-50';
    }
  };

  const isTaskFlashing = flashingTasks.has(taskId!);

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Connection Status Indicator */}
        <div className="flex justify-end">
          <div className={`text-sm ${connected ? 'text-green-600' : 'text-red-600'}`}>
            {connected ? '● Real-time updates active' : '○ Connecting...'}
          </div>
        </div>

        {/* Task Header */}
        <div className={`bg-white rounded-lg shadow p-6 transition-all duration-300 ${
          isTaskFlashing ? 'ring-2 ring-yellow-400 task-flash' : ''
        }`}>
          <div className="flex justify-between items-start">
            <div className="flex-1">
              <h1 className="text-2xl font-bold text-gray-900 mb-2">
                {task.task_id}
              </h1>
              <p className="text-gray-600 mb-4">{task.task_description}</p>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                  <span className="text-gray-500">Status:</span>
                  <span className={`ml-2 px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(task.status)}`}>
                    {task.status}
                  </span>
                </div>
                <div>
                  <span className="text-gray-500">Priority:</span>
                  <span className="ml-2 font-medium">{task.priority}</span>
                </div>
                <div>
                  <span className="text-gray-500">Created:</span>
                  <span className="ml-2">{format(new Date(task.created_at), 'MMM dd, HH:mm')}</span>
                </div>
                <div>
                  <span className="text-gray-500">Workspace:</span>
                  <span className="ml-2 font-mono text-xs">{task.workspace_base}</span>
                </div>
              </div>
            </div>

            {/* Stats */}
            <div className="ml-6 text-right">
              <div className="text-3xl font-bold text-gray-900">
                {Math.round((task.completed_count / Math.max(task.total_spawned, 1)) * 100)}%
              </div>
              <div className="text-sm text-gray-500">Overall Progress</div>
              <div className="mt-2 space-y-1 text-sm">
                <div>
                  <span className="text-gray-500">Total Agents:</span>
                  <span className="ml-2 font-medium">{task.total_spawned}</span>
                </div>
                <div>
                  <span className="text-gray-500">Active:</span>
                  <span className="ml-2 font-medium text-blue-600">{task.active_count}</span>
                </div>
                <div>
                  <span className="text-gray-500">Completed:</span>
                  <span className="ml-2 font-medium text-green-600">{task.completed_count}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Phase Timeline */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold mb-4">Phase Timeline</h2>
          <PhaseTimeline
            phases={task.phases}
            currentPhaseIndex={task.current_phase_index}
            onPhaseClick={setSelectedPhase}
            selectedPhase={selectedPhase}
          />
        </div>

        {/* Agent Tree with Flashing */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-semibold">
              Agents
              {selectedPhase !== null && (
                <span className="ml-2 text-sm text-gray-500">
                  (Phase {selectedPhase + 1}: {task.phases[selectedPhase]?.name})
                </span>
              )}
            </h2>
            {selectedPhase !== null && (
              <button
                onClick={() => setSelectedPhase(null)}
                className="text-sm text-blue-600 hover:text-blue-700"
              >
                Show all agents
              </button>
            )}
          </div>

          {/* Enhanced Agent Tree with flashing support */}
          <div className="space-y-2">
            {filteredAgents.map(agent => (
              <div
                key={agent.id}
                className={`p-3 border rounded transition-all duration-300 ${
                  flashingAgents.has(agent.id) ? 'agent-flash ring-2 ring-yellow-400' : ''
                }`}
                style={{ marginLeft: `${agent.depth * 20}px` }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-1 rounded text-xs font-medium ${getStatusColor(agent.status)}`}>
                      {agent.status}
                    </span>
                    <span className="font-mono text-sm">{agent.type}</span>
                    <span className="text-gray-500 text-xs">({agent.id})</span>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-sm text-gray-500">
                      Progress: {agent.progress}%
                    </div>
                    <div className="w-32 bg-gray-200 rounded-full h-2">
                      <div
                        className="bg-blue-600 h-2 rounded-full transition-all duration-500"
                        style={{ width: `${agent.progress}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};

export default TaskDetailEnhanced;