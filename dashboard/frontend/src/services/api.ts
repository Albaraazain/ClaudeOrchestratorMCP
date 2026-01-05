// API service for communicating with the FastAPI backend

import type { Task, Agent, Finding, LogMessage } from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const WS_BASE_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000';

class ApiService {
  private baseUrl: string;
  private wsBaseUrl: string;

  constructor() {
    this.baseUrl = API_BASE_URL;
    this.wsBaseUrl = WS_BASE_URL;
  }

  // Helper method for fetch with error handling
  private async fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
    const response = await fetch(`${this.baseUrl}${url}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }

    return response.json();
  }

  // Task endpoints
  async getTasks(): Promise<Task[]> {
    return this.fetchJson<Task[]>('/api/tasks');
  }

  async getTask(taskId: string): Promise<Task> {
    return this.fetchJson<Task>(`/api/tasks/${taskId}`);
  }

  async createTask(task: Partial<Task>): Promise<Task> {
    return this.fetchJson<Task>('/api/tasks', {
      method: 'POST',
      body: JSON.stringify(task),
    });
  }

  async updateTask(taskId: string, task: Partial<Task>): Promise<Task> {
    return this.fetchJson<Task>(`/api/tasks/${taskId}`, {
      method: 'PUT',
      body: JSON.stringify(task),
    });
  }

  // Agent endpoints
  async getAgents(taskId: string): Promise<Agent[]> {
    return this.fetchJson<Agent[]>(`/api/agents/${taskId}`);
  }

  async getAgent(taskId: string, agentId: string): Promise<Agent> {
    return this.fetchJson<Agent>(`/api/agents/${taskId}/${agentId}`);
  }

  async getAgentOutput(taskId: string, agentId: string): Promise<string> {
    const response = await fetch(`${this.baseUrl}/api/agents/${taskId}/${agentId}/output`);
    if (!response.ok) {
      throw new Error(`API Error: ${response.status} ${response.statusText}`);
    }
    return response.text();
  }

  async terminateAgent(taskId: string, agentId: string): Promise<void> {
    await this.fetchJson<void>(`/api/agents/${taskId}/${agentId}/terminate`, {
      method: 'POST',
    });
  }

  // Findings endpoints
  async getFindings(taskId: string): Promise<Finding[]> {
    return this.fetchJson<Finding[]>(`/api/findings/${taskId}`);
  }

  // WebSocket connection for real-time logs
  connectToLogs(taskId: string, onMessage: (message: LogMessage) => void, onError?: (error: Event) => void): WebSocket {
    const ws = new WebSocket(`${this.wsBaseUrl}/ws/${taskId}`);

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as LogMessage;
        onMessage(message);
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };

    ws.onerror = (event) => {
      console.error('WebSocket error:', event);
      if (onError) onError(event);
    };

    ws.onclose = () => {
      console.log('WebSocket connection closed');
    };

    return ws;
  }

  // tmux session endpoint
  async attachToTmux(sessionName: string): Promise<{ url: string }> {
    return this.fetchJson<{ url: string }>(`/api/tmux/attach/${sessionName}`);
  }
}

export const apiService = new ApiService();
