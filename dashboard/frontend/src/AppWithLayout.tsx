import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Layout } from './components/Layout';
import { Dashboard } from './pages/Dashboard';
import TaskDetail from './pages/TaskDetail';
import AgentDetail from './pages/AgentDetail';
import './index.css';

// Create a query client for React Query
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5000,
    },
  },
});

function AppWithLayout() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <Routes>
          {/* Layout wrapper for all routes */}
          <Route path="/" element={<Layout />}>
            {/* Main Dashboard */}
            <Route index element={<Dashboard />} />

            {/* Task Detail Page */}
            <Route path="task/:taskId" element={<TaskDetail />} />

            {/* Agent Detail Page */}
            <Route path="task/:taskId/agent/:agentId" element={<AgentDetail />} />
          </Route>

          {/* Default redirect */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Router>
    </QueryClientProvider>
  );
}

export default AppWithLayout;