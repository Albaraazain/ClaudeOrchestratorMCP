import { useState, useEffect, useCallback } from 'react';
import { LogEntry, AgentLogsResponse } from '../types/agent';

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

  const fetchLogs = useCallback(async () => {
    if (!taskId || !agentId) {
      console.warn('Missing taskId or agentId for fetching logs');
      return;
    }

    try {
      setIsLoading(true);
      setError(null);

      const response = await fetch(`http://localhost:8000/api/agents/${taskId}/${agentId}/logs`);

      if (!response.ok) {
        throw new Error(`Failed to fetch logs: ${response.statusText}`);
      }

      const data: AgentLogsResponse = await response.json();

      if (data.success) {
        // Process logs to ensure they have proper structure
        const processedLogs = data.logs.map(log => ({
          ...log,
          timestamp: log.timestamp || new Date().toISOString(),
          type: log.type || 'system',
          content: log.content || ''
        }));

        setLogs(processedLogs);
        setMetadata(data.metadata);
      } else {
        throw new Error('Failed to fetch logs');
      }
    } catch (err) {
      console.error('Error fetching agent logs:', err);
      setError(err instanceof Error ? err.message : 'Failed to fetch logs');
    } finally {
      setIsLoading(false);
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
  const [agent, setAgent] = useState(null);
  const [findings, setFindings] = useState([]);
  const [progress, setProgress] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchDetails = useCallback(async () => {
    if (!taskId || !agentId) return;

    try {
      setIsLoading(true);
      setError(null);

      const response = await fetch(`http://localhost:8000/api/agents/${taskId}/${agentId}`);

      if (!response.ok) {
        throw new Error(`Failed to fetch agent details: ${response.statusText}`);
      }

      const data = await response.json();

      if (data.success) {
        setAgent(data.agent);
        setFindings(data.findings || []);
        setProgress(data.progress || []);
      }
    } catch (err) {
      console.error('Error fetching agent details:', err);
      setError(err instanceof Error ? err.message : 'Failed to fetch details');
    } finally {
      setIsLoading(false);
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