# Claude Orchestrator Dashboard Architecture

## Executive Summary

A real-time web dashboard for visualizing and controlling Claude Orchestrator tasks, phases, agents, and tmux sessions. Built with a Python FastAPI backend leveraging existing orchestrator modules and a React frontend with WebSocket real-time updates.

## Stack Decisions & Rationale

### Backend: FastAPI + WebSockets
**Decision:** FastAPI with uvicorn

**Rationale:**
- Native async support aligns with existing async orchestrator code
- Built-in WebSocket support for real-time updates
- Auto-generated OpenAPI documentation
- Minimal dependencies (fastapi, uvicorn, python-multipart)
- Direct integration with existing orchestrator modules
- JSON file watching for real-time updates without polling

**Rejected Alternatives:**
- Flask: Lacks native async and WebSocket support
- Direct file reading: No real-time capabilities
- Django: Too heavyweight for this use case

### Real-time Communication: WebSockets
**Decision:** WebSockets via FastAPI

**Rationale:**
- Bi-directional communication for tmux control
- Low latency for log streaming
- Efficient for high-frequency updates
- Native browser support

**Rejected Alternatives:**
- SSE: One-way only, no tmux control
- Polling: Inefficient for real-time logs
- GraphQL subscriptions: Unnecessary complexity

### Frontend: React + Vite
**Decision:** React with Vite bundler

**Rationale:**
- Component-based architecture for complex UI
- Rich ecosystem for data visualization (recharts, react-flow)
- Virtual scrolling for large log outputs
- Hot module replacement for development
- TypeScript support for type safety

**Rejected Alternatives:**
- Vue/Svelte: Less ecosystem support for our needs
- Plain HTML/JS: Too complex for state management
- Next.js: Server-side rendering not needed

### CSS: Tailwind CSS
**Decision:** Tailwind CSS with shadcn/ui components

**Rationale:**
- Rapid prototyping with utility classes
- Dark mode support out of the box
- shadcn/ui provides accessible components
- Consistent design system

### Data Storage: Existing JSON Files
**Decision:** Read from existing .agent-workspace JSON files

**Rationale:**
- No database needed - leverage existing file structure
- File watchers for real-time updates
- Zero migration effort
- Maintains compatibility with MCP server

## Directory Structure

```
/Users/albaraa/Developer/Projects/ClaudeOrchestratorMCP/
├── orchestrator/           # Existing Python modules (no changes)
├── dashboard/
│   ├── backend/
│   │   ├── main.py        # FastAPI app entry point
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── tasks.py       # Task endpoints
│   │   │   │   ├── agents.py      # Agent endpoints
│   │   │   │   ├── phases.py      # Phase endpoints
│   │   │   │   ├── tmux.py        # Tmux control endpoints
│   │   │   │   └── logs.py        # Log streaming endpoints
│   │   │   └── websocket/
│   │   │       ├── manager.py     # WebSocket connection manager
│   │   │       └── handlers.py    # WebSocket event handlers
│   │   ├── services/
│   │   │   ├── workspace.py       # Workspace file reading
│   │   │   ├── watcher.py         # File system watcher
│   │   │   ├── tmux_service.py    # Tmux integration
│   │   │   └── log_streamer.py    # Log file streaming
│   │   ├── models/
│   │   │   └── schemas.py         # Pydantic models
│   │   └── requirements.txt
│   │
│   └── frontend/
│       ├── src/
│       │   ├── components/
│       │   │   ├── TaskList/      # Task list view
│       │   │   ├── PhaseFlow/     # Phase state machine viz
│       │   │   ├── AgentGrid/     # Agent status grid
│       │   │   ├── LogViewer/     # Real-time log viewer
│       │   │   ├── TmuxControl/   # Tmux session control
│       │   │   └── Dashboard/     # Main dashboard layout
│       │   ├── hooks/
│       │   │   ├── useWebSocket.ts
│       │   │   └── useTaskData.ts
│       │   ├── services/
│       │   │   └── api.ts         # API client
│       │   ├── store/
│       │   │   └── orchestrator.ts # Zustand state
│       │   ├── App.tsx
│       │   └── main.tsx
│       ├── package.json
│       ├── vite.config.ts
│       └── tailwind.config.js
```

## API Endpoint Design

### REST Endpoints

```python
# Task Management
GET    /api/tasks                 # List all tasks
GET    /api/tasks/{task_id}       # Get task details
GET    /api/tasks/{task_id}/registry  # Get full registry

# Agent Management
GET    /api/agents/{task_id}      # List agents for task
GET    /api/agents/{task_id}/{agent_id}  # Get agent details
GET    /api/agents/{task_id}/{agent_id}/output  # Get agent output

# Phase Management
GET    /api/phases/{task_id}      # Get phases for task
POST   /api/phases/{task_id}/advance  # Advance to next phase
POST   /api/phases/{task_id}/review   # Submit for review

# Tmux Control
GET    /api/tmux/sessions         # List tmux sessions
GET    /api/tmux/{session_name}/output  # Get session output
POST   /api/tmux/{session_name}/attach  # Attach to session
POST   /api/tmux/{session_name}/send    # Send command

# Log Streaming
GET    /api/logs/{task_id}/{agent_id}/stream  # Stream logs (SSE)
```

### WebSocket Events

```typescript
// Client -> Server Events
interface ClientEvents {
  subscribe: {
    type: 'subscribe';
    target: 'task' | 'agent' | 'logs';
    id: string;
  };
  unsubscribe: {
    type: 'unsubscribe';
    target: string;
    id: string;
  };
  tmux_command: {
    type: 'tmux_command';
    session: string;
    command: string;
  };
}

// Server -> Client Events
interface ServerEvents {
  task_update: {
    type: 'task_update';
    task_id: string;
    data: TaskData;
  };
  agent_update: {
    type: 'agent_update';
    agent_id: string;
    data: AgentData;
  };
  phase_change: {
    type: 'phase_change';
    task_id: string;
    phase: PhaseData;
  };
  log_chunk: {
    type: 'log_chunk';
    agent_id: string;
    content: string;
    timestamp: string;
  };
  tmux_output: {
    type: 'tmux_output';
    session: string;
    content: string;
  };
  finding_reported: {
    type: 'finding_reported';
    agent_id: string;
    finding: FindingData;
  };
}
```

## Component Hierarchy

```
Dashboard
├── Header
│   ├── TaskSelector
│   ├── GlobalStats
│   └── ConnectionStatus
│
├── MainView (Router)
│   ├── TaskOverview
│   │   ├── TaskList
│   │   │   └── TaskCard (status, progress, agents)
│   │   └── TaskFilters
│   │
│   ├── TaskDetail
│   │   ├── PhaseFlow (visual state machine)
│   │   ├── AgentGrid
│   │   │   └── AgentCard (status, progress, findings)
│   │   ├── FindingsPanel
│   │   └── TaskActions (advance, review, kill)
│   │
│   ├── AgentDetail
│   │   ├── AgentHeader (status, progress)
│   │   ├── LogViewer (virtualized, searchable)
│   │   ├── FindingsList
│   │   └── TmuxControl (if applicable)
│   │
│   └── TmuxManager
│       ├── SessionList
│       ├── SessionViewer (terminal emulator)
│       └── CommandInput
│
└── Sidebar
    ├── Navigation
    ├── RecentTasks
    └── SystemHealth
```

## Real-time Update Flow

1. **File System Watcher**:
   - Watch `.agent-workspace/` directory for changes
   - Detect JSON file modifications (registry, progress, findings)

2. **WebSocket Broadcasting**:
   - On file change, parse updated data
   - Broadcast to subscribed clients
   - Maintain client subscription registry

3. **Log Streaming**:
   - Tail agent log files
   - Stream new lines via WebSocket
   - Buffer for reconnection recovery

4. **Tmux Integration**:
   - Poll tmux capture-pane periodically
   - Stream output to subscribed clients
   - Handle command injection securely

## Performance Considerations

1. **Virtual Scrolling**: React Window for log viewer (handles 100k+ lines)
2. **Debouncing**: File watcher events debounced to prevent floods
3. **Pagination**: Task/agent lists paginated (50 items default)
4. **Selective Subscription**: Clients only receive updates for subscribed entities
5. **Connection Pooling**: Reuse tmux connections
6. **Caching**: In-memory cache for frequently accessed registries

## Security Considerations

1. **Input Validation**: Pydantic models for all inputs
2. **Path Traversal Prevention**: Validate all file paths
3. **Command Injection Prevention**: Escape tmux commands
4. **Rate Limiting**: Limit WebSocket message frequency
5. **CORS**: Configure for local development only

## Implementation Phases

### Phase 1: Backend Foundation
- FastAPI setup with existing orchestrator integration
- File reading services
- Basic REST endpoints
- WebSocket infrastructure

### Phase 2: Frontend Scaffold
- React + Vite setup
- Component structure
- Routing
- WebSocket hook

### Phase 3: Core Features
- Task list and detail views
- Agent grid with status
- Phase visualization
- Basic log viewer

### Phase 4: Real-time & Polish
- File watching
- Log streaming
- Tmux control
- Error handling
- Dark mode

## Dependencies

### Backend
```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
websockets==12.0
watchdog==3.0.0
pydantic==2.5.0
python-multipart==0.0.6
```

### Frontend
```json
{
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.20.0",
    "zustand": "^4.4.7",
    "react-window": "^1.8.10",
    "recharts": "^2.10.0",
    "react-flow-renderer": "^10.3.17",
    "@radix-ui/react-*": "latest",
    "tailwindcss": "^3.3.0",
    "lucide-react": "^0.294.0",
    "socket.io-client": "^4.5.4"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.2.0",
    "vite": "^5.0.0",
    "typescript": "^5.3.0"
  }
}
```

## Success Metrics

1. **Real-time Updates**: < 100ms latency for status changes
2. **Log Streaming**: Handle 1000 lines/second without lag
3. **Scalability**: Support 100+ concurrent agents
4. **Reliability**: Auto-reconnect on connection loss
5. **Usability**: One-click task creation and management