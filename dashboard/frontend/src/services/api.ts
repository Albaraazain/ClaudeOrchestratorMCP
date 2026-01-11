// API service for communicating with the FastAPI backend

import type { Task, Agent, Finding, LogMessage } from '../types';
import { getBackendUrl, getWsUrl, isTauri, waitForBackend } from '../lib/tauri';

// Default URLs for web mode
const DEFAULT_API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const DEFAULT_WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000';

class ApiService {
  private baseUrl: string;
  private wsBaseUrl: string;
  private initialized: boolean = false;

  constructor() {
    this.baseUrl = DEFAULT_API_URL;
    this.wsBaseUrl = DEFAULT_WS_URL;
  }

  /**
   * Initialize the API service.
   * In Tauri mode, waits for backend sidecar and gets dynamic URLs.
   * Call this before making any API requests.
   */
  async initialize(): Promise<void> {
    if (this.initialized) return;

    console.log('[API] Initializing...', { isTauri: isTauri() });

    if (isTauri()) {
      console.log('[API] Waiting for Tauri backend...');
      const ready = await waitForBackend(30000);
      if (!ready) {
        throw new Error('Backend failed to start within 30 seconds');
      }

      this.baseUrl = await getBackendUrl();
      this.wsBaseUrl = await getWsUrl();
      console.log('[API] Tauri backend URLs:', { api: this.baseUrl, ws: this.wsBaseUrl });
    }

    this.initialized = true;
    console.log('[API] Initialized:', { api: this.baseUrl, ws: this.wsBaseUrl });
  }

  /**
   * Ensure initialized before making requests.
   */
  private async ensureInitialized(): Promise<void> {
    if (!this.initialized) {
      await this.initialize();
    }
  }

  // Helper method for fetch with error handling
  private async fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
    await this.ensureInitialized();
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
  async getTasks(options?: { since?: string; status?: string; project?: string; limit?: number }): Promise<Task[]> {
    const params = new URLSearchParams();
    // Default to 'all' to show all tasks, not just today's
    params.set('since', options?.since ?? 'all');
    if (options?.status) params.set('status', options.status);
    if (options?.project) params.set('project', options.project);
    if (options?.limit) params.set('limit', options.limit.toString());
    return this.fetchJson<Task[]>(`/api/tasks?${params.toString()}`);
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

  async getAgentFindings(taskId: string, agentId: string, limit: number = 100): Promise<Finding[]> {
    return this.fetchJson<Finding[]>(`/api/agents/${taskId}/${agentId}/findings?limit=${limit}`);
  }

  async getAgentOutput(taskId: string, agentId: string): Promise<string> {
    await this.ensureInitialized();
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
  async connectToLogs(taskId: string, onMessage: (message: LogMessage) => void, onError?: (error: Event) => void): Promise<WebSocket> {
    await this.ensureInitialized();
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

  // Get base URLs (for components that need direct access)
  getUrls(): { api: string; ws: string } {
    return { api: this.baseUrl, ws: this.wsBaseUrl };
  }

  // tmux session endpoint
  async attachToTmux(sessionName: string): Promise<{ url: string }> {
    return this.fetchJson<{ url: string }>(`/api/tmux/attach/${sessionName}`);
  }
}

export const apiService = new ApiService();
