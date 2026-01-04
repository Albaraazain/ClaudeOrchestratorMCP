// Task and Agent types for the orchestrator dashboard

export interface Task {
  task_id: string;
  description: string;
  priority: string;
  status: 'pending' | 'active' | 'completed' | 'failed';
  created_at: string;
  updated_at: string;
  phases: Phase[];
  agents: Agent[];
  current_phase_index?: number;
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

export interface Agent {
  agent_id: string;
  type: string;
  status: 'pending' | 'starting' | 'running' | 'completed' | 'failed' | 'terminated';
  progress: number;
  message?: string;
  created_at: string;
  updated_at: string;
  parent?: string;
  phase_index?: number;
  tmux_session?: string;
  model?: string;
  findings?: Finding[];
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