import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { Task } from '../types';
import { apiService } from '../services/api';
import {
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  AlertCircle,
  Users,
  ChevronRight,
  RefreshCw,
  Plus,
  Search,
  Filter
} from 'lucide-react';

const Dashboard: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const navigate = useNavigate();

  useEffect(() => {
    fetchTasks();
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

  const getStatusColor = (status: string) => {
    switch (status.toLowerCase()) {
      case 'completed': return 'text-success bg-success/10 border-success/20';
      case 'failed': return 'text-error bg-error/10 border-error/20';
      case 'active': return 'text-primary bg-primary/10 border-primary/20';
      default: return 'text-textMuted bg-surfaceHighlight/50 border-surfaceHighlight';
    }
  };

  const filteredTasks = tasks.filter(task => 
    task.description.toLowerCase().includes(searchTerm.toLowerCase()) ||
    task.task_id.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-8">
      {/* Header Section */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-text tracking-tight">Mission Control</h1>
          <p className="text-textMuted mt-1">Manage and monitor your AI agent operations</p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={fetchTasks}
            className="p-2.5 rounded-lg bg-surface border border-surfaceHighlight text-textMuted hover:text-text hover:border-primary/50 transition-all"
          >
            <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button className="flex items-center gap-2 px-4 py-2.5 bg-primary hover:bg-primary/90 text-white rounded-lg font-medium transition-all shadow-lg shadow-primary/25">
            <Plus className="w-5 h-5" />
            <span>New Task</span>
          </button>
        </div>
      </div>

      {/* Search & Filter Bar */}
      <div className="flex flex-col md:flex-row gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-textMuted" />
          <input
            type="text"
            placeholder="Search tasks..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full pl-10 pr-4 py-3 bg-surface border border-surfaceHighlight rounded-xl text-text placeholder-textMuted focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/50 transition-all"
          />
        </div>
        <button className="flex items-center gap-2 px-4 py-3 bg-surface border border-surfaceHighlight rounded-xl text-textMuted hover:text-text transition-all">
          <Filter className="w-5 h-5" />
          <span>Filter</span>
        </button>
      </div>

      {/* Stats Overview */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
            { label: 'Active Tasks', value: tasks.filter(t => t.active_agents && t.active_agents > 0).length, color: 'text-primary' },
            { label: 'Total Agents', value: tasks.reduce((acc, t) => acc + (t.agent_count || 0), 0), color: 'text-secondary' },
            { label: 'Avg Progress', value: `${Math.round(tasks.reduce((acc, t) => acc + (t.progress || 0), 0) / Math.max(tasks.length, 1))}%`, color: 'text-success' },
        ].map((stat, i) => (
            <div key={i} className="bg-surface/50 border border-surfaceHighlight rounded-xl p-4 flex items-center justify-between">
                <span className="text-textMuted">{stat.label}</span>
                <span className={`text-2xl font-bold ${stat.color}`}>{stat.value}</span>
            </div>
        ))}
      </div>

      {/* Task Grid */}
      {loading && tasks.length === 0 ? (
        <div className="flex justify-center py-20">
          <RefreshCw className="w-8 h-8 text-primary animate-spin" />
        </div>
      ) : filteredTasks.length === 0 ? (
        <div className="text-center py-20 bg-surface/60 border border-surfaceHighlight border-dashed rounded-2xl">
          <div className="w-16 h-16 bg-surfaceHighlight/50 rounded-full flex items-center justify-center mx-auto mb-4">
            <Search className="w-8 h-8 text-textMuted" />
          </div>
          <h3 className="text-lg font-medium text-text">No tasks found</h3>
          <p className="text-textMuted">Try adjusting your search or create a new task</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
          {filteredTasks.map((task) => (
            <div
              key={task.task_id}
              onClick={() => navigate(`/tasks/${task.task_id}`)}
              className="group relative bg-surface hover:bg-surfaceHighlight/10 border border-surfaceHighlight hover:border-primary/50 rounded-2xl p-6 transition-all duration-300 cursor-pointer hover:-translate-y-1 hover:shadow-xl hover:shadow-primary/5"
            >
              {/* Card Header */}
              <div className="flex justify-between items-start mb-4">
                <div className={`px-2.5 py-1 rounded-full text-xs font-medium border ${getStatusColor(task.status)}`}>
                  {task.status.toUpperCase()}
                </div>
                <span className="text-xs font-mono text-textMuted bg-surfaceHighlight/30 px-2 py-1 rounded">
                  {task.task_id.split('-').slice(0, 2).join('-')}
                </span>
              </div>

              {/* Content */}
              <h3 className="text-lg font-semibold text-text mb-2 line-clamp-2 group-hover:text-primary transition-colors">
                {task.description}
              </h3>

              {/* Progress Bar */}
              <div className="w-full h-1.5 bg-surfaceHighlight rounded-full mb-4 overflow-hidden">
                <div
                    className="h-full bg-gradient-to-r from-primary to-secondary rounded-full transition-all duration-500"
                    style={{ width: `${task.progress || 0}%` }}
                />
              </div>

              {/* Footer Info */}
              <div className="flex items-center justify-between text-sm text-textMuted">
                <div className="flex items-center gap-4">
                  <div className="flex items-center gap-1.5">
                    <Activity className="w-4 h-4" />
                    <span>Phase {(task.current_phase_index ?? 0) + 1}/{task.phases?.length || 1}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Users className="w-4 h-4" />
                    <span>{task.active_agents || 0}/{task.agent_count || 0}</span>
                  </div>
                </div>
                <ChevronRight className="w-5 h-5 text-surfaceHighlight group-hover:text-primary transition-colors transform group-hover:translate-x-1" />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default Dashboard;