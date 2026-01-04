// Main layout component with header, sidebar, and content area

import React from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useTaskStore } from '../stores/taskStore';

export const Layout: React.FC = () => {
  const { tasks } = useTaskStore();
  const location = useLocation();

  const isActiveLink = (path: string) => {
    return location.pathname === path ? 'bg-blue-700' : 'hover:bg-gray-700';
  };

  return (
    <div className="min-h-screen bg-gray-900 text-gray-100">
      {/* Header */}
      <header className="bg-gray-800 border-b border-gray-700">
        <div className="px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <h1 className="text-2xl font-bold text-white">Orchestrator Dashboard</h1>
            <div className="flex items-center space-x-4">
              <span className="text-sm text-gray-400">
                Tasks: {tasks.length}
              </span>
              <span className="text-sm text-gray-400">
                Active: {tasks.filter(t => t.status === 'active').length}
              </span>
            </div>
          </div>
        </div>
      </header>

      <div className="flex h-[calc(100vh-64px)]">
        {/* Sidebar */}
        <nav className="w-64 bg-gray-800 border-r border-gray-700 overflow-y-auto">
          <div className="p-4">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
              Navigation
            </h2>
            <ul className="space-y-2">
              <li>
                <Link
                  to="/"
                  className={`block px-3 py-2 rounded-md text-sm font-medium text-gray-300 ${isActiveLink('/')}`}
                >
                  Dashboard
                </Link>
              </li>
            </ul>

            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mt-6 mb-3">
              Recent Tasks
            </h2>
            <ul className="space-y-2">
              {tasks.slice(0, 5).map((task) => (
                <li key={task.task_id}>
                  <Link
                    to={`/task/${task.task_id}`}
                    className={`block px-3 py-2 rounded-md text-sm text-gray-300 ${
                      location.pathname === `/task/${task.task_id}` ? 'bg-blue-700' : 'hover:bg-gray-700'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="truncate">{task.description}</span>
                      <StatusBadge status={task.status} />
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </nav>

        {/* Main Content */}
        <main className="flex-1 overflow-y-auto">
          <div className="p-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
};

// Status badge component
const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const statusColors = {
    pending: 'bg-gray-500',
    active: 'bg-blue-500',
    completed: 'bg-green-500',
    failed: 'bg-red-500',
    PENDING: 'bg-gray-500',
    ACTIVE: 'bg-blue-500',
    AWAITING_REVIEW: 'bg-yellow-500',
    UNDER_REVIEW: 'bg-yellow-600',
    APPROVED: 'bg-green-500',
    REJECTED: 'bg-red-500',
    REVISING: 'bg-orange-500',
    ESCALATED: 'bg-purple-500',
  };

  const color = statusColors[status as keyof typeof statusColors] || 'bg-gray-500';

  return (
    <span className={`inline-block px-2 py-1 text-xs rounded-full ${color} text-white`}>
      {status}
    </span>
  );
};