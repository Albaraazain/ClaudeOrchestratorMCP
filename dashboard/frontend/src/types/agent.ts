// Agent related type definitions

export interface Agent {
  agent_id: string;
  agent_type: string;
  status: 'pending' | 'running' | 'working' | 'blocked' | 'completed' | 'failed' | 'error';
  progress: number;
  message: string;
  parent: string | null;
  children?: string[];
  cursor_pid?: number | null;
  claude_pid?: number | null;
  start_time?: string;
  end_time?: string | null;
  phase_index?: number;
  tmux_session?: string;
}

export interface AgentFinding {
  timestamp: string;
  agent_id: string;
  finding_type: 'issue' | 'solution' | 'insight' | 'recommendation' | 'blocker';
  severity: 'low' | 'medium' | 'high' | 'critical';
  message: string;
  data?: Record<string, any>;
}

export interface AgentProgress {
  timestamp: string;
  status: string;
  message: string;
  progress: number;
}

export interface LogEntry {
  timestamp: string;
  type: 'assistant' | 'tool_call' | 'tool_result' | 'error' | 'system';
  content: string;
  metadata?: {
    tool?: string;
    error?: string;
    [key: string]: any;
  };
}

export interface AgentLogsResponse {
  success: boolean;
  logs: LogEntry[];
  metadata: {
    total_lines: number;
    file_size: number;
    last_modified: string;
  };
}

export interface AgentDetailResponse {
  agent: Agent;
  findings: AgentFinding[];
  progress: AgentProgress[];
  logs: LogEntry[];
}