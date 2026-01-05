import { useState, useEffect, useCallback, useRef } from 'react';

export interface LogEntry {
  timestamp: string;
  type: string;
  content: string;
  subtype?: string;
  tool_name?: string;
  parameters?: Record<string, any>;
  result?: any;
  metadata?: Record<string, any>;
}

export interface AgentLogsMetadata {
  total_lines: number;
  file_size: number;
  last_modified: string;
}

export interface AgentLogsResponse {
  success: boolean;
  logs: LogEntry[];
  metadata: AgentLogsMetadata;
}

export interface Agent {
  id: string;
  type: string;
  tmux_session: string;
  parent: string;
  depth: number;
  phase_index: number;
  status: string;
  started_at: string;
  completed_at?: string | null;
  progress: number;
  last_update: string;
  prompt: string;
  claude_pid?: number | null;
  cursor_pid?: number | null;
}

export interface AgentFinding {
  timestamp: string;
  agent_id: string;
  finding_type: string;
  severity: string;
  message: string;
  data?: Record<string, any>;
}

export interface AgentProgress {
  timestamp: string;
  agent_id: string;
  status: string;
  message: string;
  progress: number;
}

interface UseAgentLogsOptions {
  taskId: string;
  agentId: string;
  pollInterval?: number; // in milliseconds
  enabled?: boolean;
}

interface UseAgentLogsReturn {
  logs: LogEntry[];
  isLoading: boolean;
  error: string | null;
  refetch: () => void;
  metadata: AgentLogsResponse['metadata'] | null;
}

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

export const useAgentLogs = ({
  taskId,
  agentId,
  pollInterval = 2000, // Default 2 seconds
  enabled = true
}: UseAgentLogsOptions): UseAgentLogsReturn => {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metadata, setMetadata] = useState<AgentLogsResponse['metadata'] | null>(null);
  const hasLoadedOnceRef = useRef(false);

  const fetchLogs = useCallback(async () => {
    if (!taskId || !agentId) {
      console.warn('Missing taskId or agentId for fetching logs');
      return;
    }

    const isInitialLoad = !hasLoadedOnceRef.current;
    try {
      if (isInitialLoad) setIsLoading(true);
      setError(null);

      const response = await fetch(`${API_BASE_URL}/api/agents/${taskId}/${agentId}/logs`);

      if (!response.ok) {
        throw new Error(`Failed to fetch logs: ${response.statusText}`);
      }

      const data: unknown = await response.json();

      // Backend currently returns either:
      // 1) a raw array of log entries, or
      // 2) a wrapped { success, logs, metadata } payload.
      let rawLogs: LogEntry[] = [];
      let metadata: AgentLogsResponse['metadata'] | null = null;

      if (Array.isArray(data)) {
        rawLogs = data as LogEntry[];
      } else if (data && typeof data === 'object') {
        const obj = data as Partial<AgentLogsResponse> & { logs?: unknown };
        if (Array.isArray(obj.logs)) rawLogs = obj.logs as LogEntry[];
        if (obj.metadata) metadata = obj.metadata as AgentLogsResponse['metadata'];
      }

      // Process logs to ensure they have proper structure
      const processedLogs = rawLogs.map((log) => ({
        ...log,
        timestamp: log.timestamp || new Date().toISOString(),
        type: log.type || 'system',
        content: log.content || ''
      }));

      setLogs(processedLogs);
      setMetadata(metadata);
      hasLoadedOnceRef.current = true;
    } catch (err) {
      console.error('Error fetching agent logs:', err);
      setError(err instanceof Error ? err.message : 'Failed to fetch logs');
    } finally {
      if (isInitialLoad) setIsLoading(false);
    }
  }, [taskId, agentId]);

  // Initial fetch and polling setup
  useEffect(() => {
    if (!enabled) return;

    // Initial fetch
    fetchLogs();

    // Set up polling
    const intervalId = setInterval(() => {
      fetchLogs();
    }, pollInterval);

    // Cleanup
    return () => {
      clearInterval(intervalId);
    };
  }, [fetchLogs, pollInterval, enabled]);

  return {
    logs,
    isLoading,
    error,
    refetch: fetchLogs,
    metadata
  };
};

// Hook for fetching agent details (including status, findings, progress)
interface UseAgentDetailsOptions {
  taskId: string;
  agentId: string;
  pollInterval?: number;
  enabled?: boolean;
}

export const useAgentDetails = ({
  taskId,
  agentId,
  pollInterval = 5000, // Default 5 seconds for status updates
  enabled = true
}: UseAgentDetailsOptions) => {
  const [agent, setAgent] = useState<Agent | null>(null);
  const [findings, setFindings] = useState<AgentFinding[]>([]);
  const [progress, setProgress] = useState<AgentProgress[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasLoadedOnceRef = useRef(false);

  const fetchDetails = useCallback(async () => {
    if (!taskId || !agentId) return;

    const isInitialLoad = !hasLoadedOnceRef.current;
    try {
      if (isInitialLoad) setIsLoading(true);
      setError(null);

      const [agentRes, findingsRes, progressRes] = await Promise.all([
        fetch(`${API_BASE_URL}/api/agents/${taskId}/${agentId}`),
        fetch(`${API_BASE_URL}/api/agents/${taskId}/${agentId}/findings?limit=200`),
        fetch(`${API_BASE_URL}/api/agents/${taskId}/${agentId}/progress?limit=500`)
      ]);

      if (!agentRes.ok) {
        throw new Error(`Failed to fetch agent details: ${agentRes.statusText}`);
      }
      if (!findingsRes.ok) {
        throw new Error(`Failed to fetch agent findings: ${findingsRes.statusText}`);
      }
      if (!progressRes.ok) {
        throw new Error(`Failed to fetch agent progress: ${progressRes.statusText}`);
      }

      const agentData: Agent = await agentRes.json();
      const findingsData: AgentFinding[] = await findingsRes.json();
      const progressData: AgentProgress[] = await progressRes.json();

      setAgent(agentData);
      setFindings(findingsData || []);
      setProgress(progressData || []);
      hasLoadedOnceRef.current = true;
    } catch (err) {
      console.error('Error fetching agent details:', err);
      setError(err instanceof Error ? err.message : 'Failed to fetch details');
    } finally {
      if (isInitialLoad) setIsLoading(false);
    }
  }, [taskId, agentId]);

  useEffect(() => {
    if (!enabled) return;

    fetchDetails();

    const intervalId = setInterval(() => {
      fetchDetails();
    }, pollInterval);

    return () => {
      clearInterval(intervalId);
    };
  }, [fetchDetails, pollInterval, enabled]);

  return {
    agent,
    findings,
    progress,
    isLoading,
    error,
    refetch: fetchDetails
  };
};
