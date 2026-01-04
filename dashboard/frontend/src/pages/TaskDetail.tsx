import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { format } from 'date-fns';
import axios from 'axios';
import PhaseTimeline from '../components/PhaseTimeline';
import AgentTree from '../components/AgentTree';

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

const TaskDetail: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const [task, setTask] = useState<TaskDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPhase, setSelectedPhase] = useState<number | null>(null);
  const [wsConnection, setWsConnection] = useState<WebSocket | null>(null);

  // Fetch task details
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

  // Setup WebSocket for real-time updates
  useEffect(() => {
    if (!taskId) return;

    const ws = new WebSocket('ws://localhost:8000/ws');

    ws.onopen = () => {
      console.log('WebSocket connected');
      // Subscribe to task updates
      ws.send(JSON.stringify({
        type: 'subscribe',
        target: 'task',
        id: taskId
      }));
    };

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);

      if (message.type === 'task_update' && message.task_id === taskId) {
        setTask(message.data);
      } else if (message.type === 'agent_update' && message.task_id === taskId) {
        setTask(prev => {
          if (!prev) return prev;
          const updatedAgents = prev.agents.map(agent =>
            agent.id === message.data.id ? message.data : agent
          );
          return { ...prev, agents: updatedAgents };
        });
      } else if (message.type === 'phase_change' && message.task_id === taskId) {
        setTask(prev => {
          if (!prev) return prev;
          const updatedPhases = prev.phases.map(phase =>
            phase.id === message.phase.id ? message.phase : phase
          );
          return { ...prev, phases: updatedPhases };
        });
      }
    };

    ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };

    setWsConnection(ws);

    return () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: 'unsubscribe',
          target: 'task',
          id: taskId
        }));
        ws.close();
      }
    };
  }, [taskId]);

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

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Task Header */}
        <div className="bg-white rounded-lg shadow p-6">
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

        {/* Agent Tree */}
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
          <AgentTree
            agents={filteredAgents}
            hierarchy={task.agent_hierarchy}
            taskId={task.task_id}
          />
        </div>
      </div>
    </div>
  );
};

export default TaskDetail;