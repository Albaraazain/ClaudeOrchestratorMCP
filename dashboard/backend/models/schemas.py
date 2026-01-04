"""Pydantic models for the Claude Orchestrator Dashboard API."""

from datetime import datetime
from typing import Dict, List, Optional, Any, Literal
from pydantic import BaseModel, Field


# Phase schemas
class PhaseData(BaseModel):
    """Phase information."""
    id: str
    order: int
    name: str
    description: Optional[str] = None
    status: Literal[
        "PENDING", "ACTIVE", "AWAITING_REVIEW", "UNDER_REVIEW",
        "APPROVED", "REJECTED", "REVISING", "ESCALATED"
    ]
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# Agent schemas
class TrackedFiles(BaseModel):
    """Tracked files for an agent."""
    prompt_file: Optional[str] = None
    log_file: Optional[str] = None
    progress_file: Optional[str] = None
    findings_file: Optional[str] = None
    deploy_log: Optional[str] = None


class AgentData(BaseModel):
    """Agent information."""
    id: str
    type: str
    tmux_session: str
    parent: str = "orchestrator"
    depth: int = 1
    phase_index: int = 0
    status: Literal["running", "working", "blocked", "completed", "failed", "error", "terminated", "reviewing"]
    started_at: datetime
    completed_at: Optional[datetime] = None
    progress: int = Field(ge=0, le=100)
    last_update: datetime
    prompt: str = Field(description="First 200 chars of agent prompt")
    claude_pid: Optional[int] = None
    cursor_pid: Optional[int] = None
    tracked_files: TrackedFiles


class AgentProgress(BaseModel):
    """Agent progress update."""
    timestamp: datetime
    agent_id: str
    status: str
    message: str
    progress: int = Field(ge=0, le=100)


class AgentFinding(BaseModel):
    """Agent finding/discovery."""
    timestamp: datetime
    agent_id: str
    finding_type: Literal["issue", "solution", "insight", "recommendation"]
    severity: Literal["low", "medium", "high", "critical"]
    message: str
    data: Optional[Dict[str, Any]] = None


# Review schemas
class ReviewData(BaseModel):
    """Review information."""
    review_id: str
    phase_index: int
    status: Literal["pending", "in_progress", "completed", "aborted"]
    started_at: datetime
    reviewer_count: int
    verdicts_submitted: int
    final_verdict: Optional[Literal["approved", "rejected", "needs_revision"]] = None


# Task schemas
class TaskContext(BaseModel):
    """Task context information."""
    expected_deliverables: Optional[List[str]] = []
    success_criteria: Optional[List[str]] = []
    relevant_files: Optional[List[str]] = []


class TaskSummary(BaseModel):
    """Task summary for list view."""
    task_id: str
    description: str
    created_at: datetime
    status: Literal["INITIALIZED", "ACTIVE", "COMPLETED", "FAILED"]
    current_phase: Optional[PhaseData] = None
    agent_count: int
    active_agents: int
    progress: int = Field(ge=0, le=100)


class TaskDetail(BaseModel):
    """Complete task details."""
    task_id: str
    task_description: str
    created_at: datetime
    workspace: str
    workspace_base: str
    client_cwd: str
    status: Literal["INITIALIZED", "ACTIVE", "COMPLETED", "FAILED"]
    priority: Literal["P0", "P1", "P2", "P3", "P4"]
    phases: List[PhaseData]
    current_phase_index: int
    agents: List[AgentData]
    agent_hierarchy: Dict[str, List[str]]
    max_agents: int = 45
    max_depth: int = 5
    max_concurrent: int = 20
    total_spawned: int
    active_count: int
    completed_count: int
    reviews: List[ReviewData]
    task_context: TaskContext


# Log schemas
class LogEntry(BaseModel):
    """Log entry from agent stream."""
    timestamp: datetime
    type: Literal["system", "user", "assistant", "tool_call", "tool_result"]
    content: Optional[str] = None
    subtype: Optional[str] = None
    tool_name: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None
    result: Optional[Any] = None


class LogChunk(BaseModel):
    """Log chunk for streaming."""
    agent_id: str
    content: str
    timestamp: datetime
    sequence: int


# Tmux schemas
class TmuxSession(BaseModel):
    """Tmux session information."""
    name: str
    created: datetime
    windows: int
    panes: int
    attached: bool
    pid: Optional[int] = None
    agent_id: Optional[str] = None


class TmuxOutput(BaseModel):
    """Tmux pane output."""
    session_name: str
    content: str
    timestamp: datetime
    lines_captured: int


# WebSocket messages
class WSMessage(BaseModel):
    """Base WebSocket message."""
    type: str
    timestamp: datetime = Field(default_factory=datetime.now)


class WSSubscribe(WSMessage):
    """Subscribe to updates."""
    type: Literal["subscribe"] = "subscribe"
    target: Literal["task", "agent", "logs", "tmux"]
    id: str


class WSUnsubscribe(WSMessage):
    """Unsubscribe from updates."""
    type: Literal["unsubscribe"] = "unsubscribe"
    target: str
    id: str


class WSTaskUpdate(WSMessage):
    """Task update event."""
    type: Literal["task_update"] = "task_update"
    task_id: str
    data: TaskDetail


class WSAgentUpdate(WSMessage):
    """Agent update event."""
    type: Literal["agent_update"] = "agent_update"
    agent_id: str
    task_id: str
    data: AgentData


class WSPhaseChange(WSMessage):
    """Phase change event."""
    type: Literal["phase_change"] = "phase_change"
    task_id: str
    phase: PhaseData


class WSLogChunk(WSMessage):
    """Log chunk event."""
    type: Literal["log_chunk"] = "log_chunk"
    agent_id: str
    content: str


class WSTmuxOutput(WSMessage):
    """Tmux output event."""
    type: Literal["tmux_output"] = "tmux_output"
    session: str
    content: str


class WSFindingReported(WSMessage):
    """Finding reported event."""
    type: Literal["finding_reported"] = "finding_reported"
    agent_id: str
    finding: AgentFinding


# API Response models
class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    version: str = "1.0.0"
    uptime: float
    timestamp: datetime