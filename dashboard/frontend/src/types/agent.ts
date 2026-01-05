// Re-export all agent-related types from index.ts
// This file exists for backward compatibility with imports that use './types/agent'
export type { Agent, AgentFinding, AgentProgress, LogEntry, AgentLogsResponse, AgentDetailResponse } from './index';
