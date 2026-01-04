// Zustand store for task and agent state management

import { create } from 'zustand';
import { Task, Agent, Finding, LogMessage } from '../types';
import { apiService } from '../services/api';

interface TaskStore {
  // State
  tasks: Task[];
  selectedTask: Task | null;
  selectedAgent: Agent | null;
  agents: Agent[];
  findings: Finding[];
  logs: LogMessage[];
  loading: boolean;
  error: string | null;

  // Actions
  fetchTasks: () => Promise<void>;
  fetchTask: (taskId: string) => Promise<void>;
  fetchAgents: (taskId: string) => Promise<void>;
  fetchFindings: (taskId: string) => Promise<void>;
  selectTask: (task: Task | null) => void;
  selectAgent: (agent: Agent | null) => void;
  addLog: (log: LogMessage) => void;
  clearLogs: () => void;
  setError: (error: string | null) => void;
}

export const useTaskStore = create<TaskStore>((set, get) => ({
  // Initial state
  tasks: [],
  selectedTask: null,
  selectedAgent: null,
  agents: [],
  findings: [],
  logs: [],
  loading: false,
  error: null,

  // Actions
  fetchTasks: async () => {
    set({ loading: true, error: null });
    try {
      const tasks = await apiService.getTasks();
      set({ tasks, loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch tasks',
        loading: false
      });
    }
  },

  fetchTask: async (taskId: string) => {
    set({ loading: true, error: null });
    try {
      const task = await apiService.getTask(taskId);
      set({ selectedTask: task, loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch task',
        loading: false
      });
    }
  },

  fetchAgents: async (taskId: string) => {
    set({ loading: true, error: null });
    try {
      const agents = await apiService.getAgents(taskId);
      set({ agents, loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to fetch agents',
        loading: false
      });
    }
  },

  fetchFindings: async (taskId: string) => {
    try {
      const findings = await apiService.getFindings(taskId);
      set({ findings });
    } catch (error) {
      console.error('Failed to fetch findings:', error);
    }
  },

  selectTask: (task: Task | null) => {
    set({ selectedTask: task, selectedAgent: null });
    if (task) {
      // Fetch related data when a task is selected
      get().fetchAgents(task.task_id);
      get().fetchFindings(task.task_id);
    }
  },

  selectAgent: (agent: Agent | null) => {
    set({ selectedAgent: agent });
  },

  addLog: (log: LogMessage) => {
    set((state) => ({
      logs: [...state.logs, log].slice(-1000) // Keep last 1000 logs
    }));
  },

  clearLogs: () => {
    set({ logs: [] });
  },

  setError: (error: string | null) => {
    set({ error });
  }
}));