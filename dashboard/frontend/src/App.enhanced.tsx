/**
 * Enhanced App Component with WebSocket Integration
 * Example of how to integrate WebSocket real-time updates
 */

import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import WebSocketProvider from './providers/WebSocketProvider';
import Dashboard from './pages/Dashboard';
import TaskDetailEnhanced from './pages/TaskDetailEnhanced';
import AgentDetail from './pages/AgentDetail';
import Layout from './components/Layout';
import './App.css';

function App() {
  return (
    <Router>
      <WebSocketProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/task/:taskId" element={<TaskDetailEnhanced />} />
            <Route path="/agent/:agentId" element={<AgentDetail />} />
          </Routes>
        </Layout>
      </WebSocketProvider>
    </Router>
  );
}

export default App;