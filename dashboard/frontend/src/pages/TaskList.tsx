import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { format } from 'date-fns';
import axios from 'axios';

interface Phase {
  id: string;
  order: number;
  name: string;
  status: string;
}

interface TaskSummary {
  task_id: string;
  description: string;
  created_at: string;
  status: 'INITIALIZED' | 'ACTIVE' | 'COMPLETED' | 'FAILED';
  current_phase?: Phase;
  agent_count: number;
  active_agents: number;
  progress: number;
}

const TaskList: React.FC = () => {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wsConnection, setWsConnection] = useState<WebSocket | null>(null);

  // Fetch tasks
  useEffect(() => {
    const fetchTasks = async () => {
      try {
        setLoading(true);
        const response = await axios.get<TaskSummary[]>(`${import.meta.env.VITE_API_URL || 'http://localhost:8765'}/api/tasks`);
        setTasks(response.data);
        setError(null);
      } catch (err) {
        console.error('Failed to fetch tasks:', err);
        setError('Failed to load tasks');
      } finally {
        setLoading(false);
      }
    };

    fetchTasks();
  }, []);

  // Setup WebSocket for real-time updates
  useEffect(() => {
    const ws = new WebSocket(`${import.meta.env.VITE_WS_URL || 'ws://localhost:8765'}/ws`);

    ws.onopen = () => {
      console.log('WebSocket connected');
      // Subscribe to all task updates
      ws.send(JSON.stringify({
        type: 'subscribe',
        target: 'tasks',
        id: 'all'
      }));
    };

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);

      if (message.type === 'task_update') {
        setTasks(prev => {
          const index = prev.findIndex(t => t.task_id === message.data.task_id);
          if (index >= 0) {
            const updated = [...prev];
            updated[index] = message.data;
            return updated;
          } else {
            return [...prev, message.data];
          }
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
          target: 'tasks',
          id: 'all'
        }));
        ws.close();
      }
    };
  }, []);

  const handleTaskClick = (taskId: string) => {
    navigate(`/tasks/${taskId}`);
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'ACTIVE':
        return 'text-blue-600 bg-blue-50';
      case 'COMPLETED':
        return 'text-green-600 bg-green-50';
      case 'FAILED':
        return 'text-red-600 bg-red-50';
      default:
        return 'text-gray-600 bg-gray-50';
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-red-600">{error}</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">Claude Orchestrator Dashboard</h1>
          <p className="text-gray-600 mt-2">Monitor and manage orchestrator tasks and agents</p>
        </div>

        {/* Tasks Grid */}
        {tasks.length === 0 ? (
          <div className="bg-white rounded-lg shadow p-8 text-center">
            <p className="text-gray-500">No tasks found</p>
          </div>
        ) : (
          <div className="grid gap-4">
            {tasks.map(task => (
              <div
                key={task.task_id}
                onClick={() => handleTaskClick(task.task_id)}
                className="bg-white rounded-lg shadow hover:shadow-lg transition-shadow cursor-pointer p-6"
              >
                <div className="flex justify-between items-start">
                  <div className="flex-1">
                    {/* Task Header */}
                    <div className="flex items-center gap-3 mb-2">
                      <h2 className="text-lg font-semibold text-gray-900">
                        {task.task_id}
                      </h2>
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(task.status)}`}>
                        {task.status}
                      </span>
                    </div>

                    {/* Description */}
                    <p className="text-gray-600 mb-3">{task.description}</p>

                    {/* Current Phase */}
                    {task.current_phase && (
                      <div className="mb-3">
                        <span className="text-sm text-gray-500">Current Phase: </span>
                        <span className="text-sm font-medium text-gray-900">
                          {task.current_phase.name}
                        </span>
                        <span className={`ml-2 px-2 py-0.5 rounded text-xs ${
                          task.current_phase.status === 'ACTIVE' ? 'bg-blue-100 text-blue-700' :
                          task.current_phase.status === 'APPROVED' ? 'bg-green-100 text-green-700' :
                          'bg-gray-100 text-gray-700'
                        }`}>
                          {task.current_phase.status}
                        </span>
                      </div>
                    )}

                    {/* Progress Bar */}
                    <div className="mb-3">
                      <div className="flex justify-between text-xs text-gray-500 mb-1">
                        <span>Progress</span>
                        <span>{task.progress}%</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-2">
                        <div
                          className="bg-blue-600 h-2 rounded-full transition-all"
                          style={{ width: `${task.progress}%` }}
                        />
                      </div>
                    </div>

                    {/* Meta Info */}
                    <div className="flex gap-4 text-sm text-gray-500">
                      <span>Created: {format(new Date(task.created_at), 'MMM dd, HH:mm')}</span>
                      <span>Agents: {task.active_agents}/{task.agent_count}</span>
                    </div>
                  </div>

                  {/* Quick Stats */}
                  <div className="ml-6 text-right">
                    <div className="text-2xl font-bold text-gray-900">{task.agent_count}</div>
                    <div className="text-sm text-gray-500">Total Agents</div>
                    <div className="mt-2">
                      <div className="text-lg font-semibold text-blue-600">{task.active_agents}</div>
                      <div className="text-xs text-gray-500">Active</div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default TaskList;