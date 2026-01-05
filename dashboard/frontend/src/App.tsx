import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import TaskDetail from './pages/TaskDetail';
import Dashboard from './pages/Dashboard';
import { AgentDetail } from './pages/AgentDetail';
import Layout from './components/Layout';
import './index.css';

function App() {
  return (
    <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Layout>
        <Routes>
          {/* Main Dashboard - Task List */}
          <Route path="/" element={<Dashboard />} />

          {/* Task Detail Page */}
          <Route path="/tasks/:taskId" element={<TaskDetail />} />

          {/* Agent Detail Page */}
          <Route path="/tasks/:taskId/agents/:agentId" element={<AgentDetail />} />

          {/* Agent Logs Page */}
          <Route path="/tasks/:taskId/agents/:agentId/logs" element={<AgentDetail showLogs={true} />} />

          {/* Default redirect */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </Router>
  );
}

export default App
