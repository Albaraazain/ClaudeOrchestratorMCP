import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Task } from '../types';
import { apiService } from '../services/api';
import {
  Activity,
  Circle,
  CheckCircle,
  XCircle,
  Clock,
  AlertCircle,
  Users,
  ChevronRight,
  RefreshCw
} from 'lucide-react';

const TaskListPage: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetchTasks();
    // Refresh tasks every 5 seconds
    const interval = setInterval(fetchTasks, 5000);
    return () => clearInterval(interval);
  }, []);

  const fetchTasks = async () => {
    try {
      const fetchedTasks = await apiService.getTasks();
      setTasks(fetchedTasks);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch tasks');
    } finally {
      setLoading(false);
    }
  };

  const getStatusColor = (status: string): string => {
    switch (status) {
      case 'completed':
        return 'text-green-500';
      case 'failed':
        return 'text-red-500';
      case 'active':
        return 'text-blue-500';
      default:
        return 'text-gray-500';
    }
  };

  const getPhaseStatusColor = (status: string): string => {
    switch (status) {
      case 'APPROVED':
        return 'bg-green-100 text-green-800';
      case 'REJECTED':
        return 'bg-red-100 text-red-800';
      case 'ACTIVE':
        return 'bg-blue-100 text-blue-800';
      case 'AWAITING_REVIEW':
      case 'UNDER_REVIEW':
        return 'bg-yellow-100 text-yellow-800';
      case 'REVISING':
        return 'bg-orange-100 text-orange-800';
      case 'ESCALATED':
        return 'bg-purple-100 text-purple-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="w-5 h-5" />;
      case 'failed':
        return <XCircle className="w-5 h-5" />;
      case 'active':
        return <Activity className="w-5 h-5" />;
      default:
        return <Circle className="w-5 h-5" />;
    }
  };

  const formatTimestamp = (timestamp: string): string => {
    const date = new Date(timestamp);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const truncateTaskId = (taskId: string): string => {
    const parts = taskId.split('-');
    if (parts.length >= 3) {
      return `${parts[0]}-...-${parts[parts.length - 1]}`;
    }
    return taskId;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="flex items-center space-x-2 text-gray-600">
          <RefreshCw className="w-5 h-5 animate-spin" />
          <span>Loading tasks...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gray-50">
        <div className="flex items-center space-x-2 text-red-600">
          <AlertCircle className="w-5 h-5" />
          <span>{error}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-bold text-gray-900">
              Claude Orchestrator Dashboard
            </h1>
            <button
              onClick={fetchTasks}
              className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
              <span>Refresh</span>
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {tasks.length === 0 ? (
          <div className="text-center py-16 bg-white rounded-lg shadow">
            <p className="text-gray-500">No tasks found</p>
          </div>
        ) : (
          <div className="grid gap-4">
            {tasks.map((task) => (
              <div
                key={task.task_id}
                className="bg-white rounded-lg shadow hover:shadow-lg transition-shadow cursor-pointer"
                onClick={() => navigate(`/tasks/${task.task_id}`)}
              >
                <div className="p-6">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center space-x-2 mb-2">
                        <span className={`${getStatusColor(task.status)} flex items-center`}>
                          {getStatusIcon(task.status)}
                        </span>
                        <span className="text-sm font-mono text-gray-500">
                          {truncateTaskId(task.task_id)}
                        </span>
                      </div>

                      <h3 className="text-lg font-semibold text-gray-900 mb-2">
                        {task.description}
                      </h3>

                      <div className="flex flex-wrap items-center gap-4 text-sm">
                        {task.phases && (
                          <>
                            <div className="flex items-center space-x-1">
                              <Activity className="w-4 h-4 text-gray-400" />
                              <span className="text-gray-600">
                                Phase {task.phases.current_index + 1}/{task.phases.total}
                              </span>
                            </div>

                            <div className={`px-2 py-1 rounded-full text-xs font-medium ${
                              task.phases.all_phases && task.phases.all_phases[task.phases.current_index]
                                ? getPhaseStatusColor(task.phases.all_phases[task.phases.current_index].status)
                                : 'bg-gray-100 text-gray-800'
                            }`}>
                              {task.phases.all_phases && task.phases.all_phases[task.phases.current_index]?.name}
                              {task.phases.all_phases && task.phases.all_phases[task.phases.current_index]?.status &&
                                ` - ${task.phases.all_phases[task.phases.current_index].status}`}
                            </div>
                          </>
                        )}

                        {task.agents && (
                          <div className="flex items-center space-x-1">
                            <Users className="w-4 h-4 text-gray-400" />
                            <span className="text-gray-600">
                              {task.agents.agents_list.filter(a => a.status === 'running' || a.status === 'starting').length} active / {task.agents.total_spawned} total agents
                            </span>
                          </div>
                        )}

                        <div className="flex items-center space-x-1">
                          <Clock className="w-4 h-4 text-gray-400" />
                          <span className="text-gray-600">
                            {formatTimestamp(task.created_at)}
                          </span>
                        </div>
                      </div>

                      {task.phases?.all_phases && (
                        <div className="mt-4">
                          <div className="flex items-center space-x-2">
                            {task.phases.all_phases.map((phase, index) => (
                              <div
                                key={index}
                                className={`flex-1 h-2 rounded-full ${
                                  phase.status === 'APPROVED'
                                    ? 'bg-green-500'
                                    : phase.status === 'REJECTED'
                                    ? 'bg-red-500'
                                    : phase.status === 'ACTIVE' || phase.status === 'AWAITING_REVIEW' || phase.status === 'UNDER_REVIEW'
                                    ? 'bg-blue-500'
                                    : phase.status === 'REVISING'
                                    ? 'bg-orange-500'
                                    : phase.status === 'ESCALATED'
                                    ? 'bg-purple-500'
                                    : 'bg-gray-300'
                                }`}
                                title={`${phase.name}: ${phase.status}`}
                              />
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    <ChevronRight className="w-5 h-5 text-gray-400 ml-4" />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
};

export default TaskListPage;