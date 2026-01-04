import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import TaskDetail from './pages/TaskDetail';
import { Dashboard } from './pages/Dashboard';
import { AgentDetail } from './pages/AgentDetail';
import './index.css';

function App() {
  return (
    <Router>
      <div className="min-h-screen bg-gray-50">
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
      </div>
    </Router>
  );
}

export default App
