// Task and Agent types for the orchestrator dashboard
// All types in one file to avoid module resolution issues

export interface Agent {
  agent_id: string;
  agent_type?: string;
  type?: string;
  status: 'pending' | 'starting' | 'running' | 'working' | 'blocked' | 'completed' | 'failed' | 'terminated' | 'error';
  progress: number;
  message?: string;
  parent?: string | null;
  children?: string[];
  cursor_pid?: number | null;
  claude_pid?: number | null;
  start_time?: string;
  end_time?: string | null;
  created_at?: string;
  updated_at?: string;
  phase_index?: number;
  tmux_session?: string;
  model?: string;
  findings?: Finding[];
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

export interface Task {
  task_id: string;
  description: string;
  priority?: string;
  status: string; // API returns 'INITIALIZED', 'ACTIVE', 'COMPLETED', etc.
  created_at: string;
  updated_at?: string;
  phases?: Phase[];
  agents?: Agent[];
  current_phase?: Phase | null; // From list API
  current_phase_index?: number;
  agent_count?: number; // From list API
  active_agents?: number; // From list API
  progress?: number; // From list API
  error?: string;
}

export interface Phase {
  name: string;
  description?: string;
  status: 'PENDING' | 'ACTIVE' | 'AWAITING_REVIEW' | 'UNDER_REVIEW' | 'APPROVED' | 'REJECTED' | 'REVISING' | 'ESCALATED';
  agents?: Agent[];
  review_data?: ReviewData;
}

export interface ReviewData {
  review_id?: string;
  reviewer_agents?: string[];
  verdicts_received?: number;
  verdicts_required?: number;
  findings?: Finding[];
  summary?: string;
}

export interface Finding {
  finding_type: 'issue' | 'solution' | 'insight' | 'recommendation' | 'blocker';
  severity: 'low' | 'medium' | 'high' | 'critical';
  message: string;
  timestamp: string;
  agent_id?: string;
  data?: Record<string, any>;
}

export interface LogMessage {
  timestamp: string;
  level: 'debug' | 'info' | 'warning' | 'error';
  message: string;
  agent_id?: string;
  task_id?: string;
  data?: any;
}
