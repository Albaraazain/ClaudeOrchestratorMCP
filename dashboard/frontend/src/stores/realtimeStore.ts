/**
 * Zustand Store for Real-Time Data
 * Manages WebSocket updates and real-time state
 */

import { create } from 'zustand';
import { devtools } from 'zustand/middleware';
import type { WebSocketMessage } from '../services/websocket';

export interface TaskUpdate {
  taskId: string;
  status?: string;
  phase?: string;
  progress?: number;
  message?: string;
  timestamp: string;
}

export interface AgentUpdate {
  agentId: string;
  taskId?: string;
  status?: string;
  progress?: number;
  message?: string;
  timestamp: string;
}

export interface LogEntry {
  agentId: string;
  taskId?: string;
  content: string;
  level?: 'debug' | 'info' | 'warning' | 'error';
  timestamp: string;
}

export interface Finding {
  agentId: string;
  taskId: string;
  findingType: 'issue' | 'solution' | 'insight' | 'recommendation';
  severity: 'low' | 'medium' | 'high' | 'critical';
  message: string;
  data?: any;
  timestamp: string;
}

export interface RealtimeState {
  // Task updates indexed by task ID
  taskUpdates: Map<string, TaskUpdate[]>;

  // Agent updates indexed by agent ID
  agentUpdates: Map<string, AgentUpdate[]>;

  // Recent log entries (limited to last 1000)
  recentLogs: LogEntry[];

  // Findings reported by agents
  findings: Finding[];

  // Flash indicators for UI highlighting
  flashingTasks: Set<string>;
  flashingAgents: Set<string>;

  // Connection status
  isConnected: boolean;
  lastUpdateTime: string | null;

  // Actions
  addTaskUpdate: (update: TaskUpdate) => void;
  addAgentUpdate: (update: AgentUpdate) => void;
  addLogEntry: (entry: LogEntry) => void;
  addFinding: (finding: Finding) => void;

  processWebSocketMessage: (message: WebSocketMessage) => void;

  flashTask: (taskId: string) => void;
  flashAgent: (agentId: string) => void;
  clearFlash: (type: 'task' | 'agent', id: string) => void;

  setConnectionStatus: (connected: boolean) => void;

  clearOldData: () => void;
  reset: () => void;
}

const MAX_LOGS = 1000;
const MAX_UPDATES_PER_ITEM = 100;
const FLASH_DURATION = 2000; // 2 seconds

export const useRealtimeStore = create<RealtimeState>()(
  devtools(
    (set, get) => ({
      taskUpdates: new Map(),
      agentUpdates: new Map(),
      recentLogs: [],
      findings: [],
      flashingTasks: new Set(),
      flashingAgents: new Set(),
      isConnected: false,
      lastUpdateTime: null,

      addTaskUpdate: (update) =>
        set((state) => {
          const updates = state.taskUpdates.get(update.taskId) || [];
          updates.push(update);

          // Keep only last MAX_UPDATES_PER_ITEM
          if (updates.length > MAX_UPDATES_PER_ITEM) {
            updates.shift();
          }

          const newTaskUpdates = new Map(state.taskUpdates);
          newTaskUpdates.set(update.taskId, updates);

          // Flash the task
          get().flashTask(update.taskId);

          return {
            taskUpdates: newTaskUpdates,
            lastUpdateTime: new Date().toISOString()
          };
        }),

      addAgentUpdate: (update) =>
        set((state) => {
          const updates = state.agentUpdates.get(update.agentId) || [];
          updates.push(update);

          // Keep only last MAX_UPDATES_PER_ITEM
          if (updates.length > MAX_UPDATES_PER_ITEM) {
            updates.shift();
          }

          const newAgentUpdates = new Map(state.agentUpdates);
          newAgentUpdates.set(update.agentId, updates);

          // Flash the agent
          get().flashAgent(update.agentId);

          return {
            agentUpdates: newAgentUpdates,
            lastUpdateTime: new Date().toISOString()
          };
        }),

      addLogEntry: (entry) =>
        set((state) => {
          const newLogs = [...state.recentLogs, entry];

          // Keep only last MAX_LOGS
          if (newLogs.length > MAX_LOGS) {
            newLogs.shift();
          }

          return {
            recentLogs: newLogs,
            lastUpdateTime: new Date().toISOString()
          };
        }),

      addFinding: (finding) =>
        set((state) => ({
          findings: [...state.findings, finding],
          lastUpdateTime: new Date().toISOString()
        })),

      processWebSocketMessage: (message) => {
        const timestamp = message.timestamp || new Date().toISOString();

        switch (message.type) {
          case 'task_update':
            get().addTaskUpdate({
              taskId: message.data.task_id,
              status: message.data.status,
              phase: message.data.phase,
              progress: message.data.progress,
              message: message.data.message,
              timestamp
            });
            break;

          case 'phase_change':
            get().addTaskUpdate({
              taskId: message.data.task_id,
              phase: message.data.new_phase,
              message: `Phase changed to ${message.data.new_phase}`,
              timestamp
            });
            break;

          case 'agent_update':
            get().addAgentUpdate({
              agentId: message.data.agent_id,
              taskId: message.data.task_id,
              status: message.data.status,
              progress: message.data.progress,
              message: message.data.message,
              timestamp
            });
            break;

          case 'log_entry':
            get().addLogEntry({
              agentId: message.data.agent_id,
              taskId: message.data.task_id,
              content: message.data.content,
              level: message.data.level,
              timestamp
            });
            break;

          case 'finding':
            get().addFinding({
              agentId: message.data.agent_id,
              taskId: message.data.task_id,
              findingType: message.data.finding_type,
              severity: message.data.severity,
              message: message.data.message,
              data: message.data.data,
              timestamp
            });
            break;
        }
      },

      flashTask: (taskId) =>
        set((state) => {
          const newFlashing = new Set(state.flashingTasks);
          newFlashing.add(taskId);

          // Auto-clear after duration
          setTimeout(() => {
            get().clearFlash('task', taskId);
          }, FLASH_DURATION);

          return { flashingTasks: newFlashing };
        }),

      flashAgent: (agentId) =>
        set((state) => {
          const newFlashing = new Set(state.flashingAgents);
          newFlashing.add(agentId);

          // Auto-clear after duration
          setTimeout(() => {
            get().clearFlash('agent', agentId);
          }, FLASH_DURATION);

          return { flashingAgents: newFlashing };
        }),

      clearFlash: (type, id) =>
        set((state) => {
          if (type === 'task') {
            const newFlashing = new Set(state.flashingTasks);
            newFlashing.delete(id);
            return { flashingTasks: newFlashing };
          } else {
            const newFlashing = new Set(state.flashingAgents);
            newFlashing.delete(id);
            return { flashingAgents: newFlashing };
          }
        }),

      setConnectionStatus: (connected) =>
        set({
          isConnected: connected,
          lastUpdateTime: new Date().toISOString()
        }),

      clearOldData: () =>
        set((state) => {
          const cutoffTime = new Date();
          cutoffTime.setHours(cutoffTime.getHours() - 1); // Keep last hour
          const cutoff = cutoffTime.toISOString();

          // Filter old logs
          const recentLogs = state.recentLogs.filter(
            log => log.timestamp > cutoff
          );

          // Filter old findings
          const findings = state.findings.filter(
            finding => finding.timestamp > cutoff
          );

          return {
            recentLogs,
            findings
          };
        }),

      reset: () =>
        set({
          taskUpdates: new Map(),
          agentUpdates: new Map(),
          recentLogs: [],
          findings: [],
          flashingTasks: new Set(),
          flashingAgents: new Set(),
          isConnected: false,
          lastUpdateTime: null
        })
    }),
    {
      name: 'realtime-store'
    }
  )
);