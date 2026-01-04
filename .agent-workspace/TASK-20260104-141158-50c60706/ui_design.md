# Claude Orchestrator Dashboard UI/UX Design Specification

## Overview
A real-time web dashboard for monitoring and controlling the Claude Orchestrator MCP system, providing visualization of tasks, phases, agents, and their outputs.

## Design Principles
1. **Real-time First**: All data updates live without refresh
2. **Information Hierarchy**: Progressive disclosure from overview to details
3. **Status at a Glance**: Color-coded visual indicators for immediate understanding
4. **Responsive**: Works on desktop and tablet viewports
5. **Dark Mode Default**: Easier on eyes for extended monitoring sessions

## Color Scheme

### Status Colors (8-State Phase Machine)
```
PENDING:         #6B7280 (Gray)
ACTIVE:          #3B82F6 (Blue)
AWAITING_REVIEW: #F59E0B (Amber)
UNDER_REVIEW:    #8B5CF6 (Purple)
APPROVED:        #10B981 (Green)
REJECTED:        #EF4444 (Red)
REVISING:        #F97316 (Orange)
ESCALATED:       #DC2626 (Dark Red)
```

### Agent Status Colors
```
running/working: #3B82F6 (Blue)
completed:       #10B981 (Green)
blocked:         #F59E0B (Amber)
failed/error:    #EF4444 (Red)
terminated:      #6B7280 (Gray)
```

### Background & UI Colors
```
Background:      #0F172A (Dark slate)
Surface:         #1E293B (Lighter slate)
Border:          #334155 (Slate border)
Text Primary:    #F1F5F9 (Light gray)
Text Secondary:  #94A3B8 (Medium gray)
Accent:          #3B82F6 (Blue)
```

## Layout Structure

### 1. Main Dashboard View

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Claude Orchestrator Dashboard                    [Search] [Filter] [⚙️] │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ Active Tasks (3)                                    Auto-refresh │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ TASK-20260104-141158 ● P1                           ▶ Expand     │  │
│  │ Build Web Dashboard UI                                            │  │
│  │                                                                   │  │
│  │ Phase Progress:                                                   │  │
│  │ [Investigation] → [Backend] → [Frontend] → [Testing]              │  │
│  │      ✓ ACTIVE      PENDING     PENDING      PENDING               │  │
│  │                                                                   │  │
│  │ Agents: 5 active | 0 completed | 0 failed                        │  │
│  │ ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ 20% overall            │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ TASK-20260104-135422 ● P2                           ▶ Expand     │  │
│  │ Fix authentication bug                                             │  │
│  │                                                                   │  │
│  │ Phase Progress:                                                   │  │
│  │ [Analysis] → [Implementation] → [Testing]                         │  │
│  │   APPROVED      ✓ ACTIVE        PENDING                           │  │
│  │                                                                   │  │
│  │ Agents: 3 active | 2 completed | 0 failed                        │  │
│  │ ████████████████░░░░░░░░░░░░░░░░░░░░░░░░░ 40% overall            │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ TASK-20260104-130155 ● P0                           ▶ Expand     │  │
│  │ Security audit and fixes                                          │  │
│  │                                                                   │  │
│  │ Phase Progress:                                                   │  │
│  │ [Audit] → [Fixes] → [Validation] → [Documentation]                │  │
│  │ APPROVED  APPROVED  UNDER_REVIEW     PENDING                      │  │
│  │                                                                   │  │
│  │ Agents: 2 active | 8 completed | 1 failed                        │  │
│  │ ████████████████████████████░░░░░░░░░░░░ 75% overall             │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2. Task Detail View

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ← Back to Dashboard         TASK-20260104-141158                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  Build Web Dashboard UI for Claude Orchestrator                          │
│  Priority: P1 | Created: 2026-01-04 14:11:58 | Workspace: ...           │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │                        Phase Timeline                              │  │
│  │                                                                   │  │
│  │     Investigation          Backend           Frontend          Testing│
│  │     ════════════►      ═══════════►      ═══════════►    ═══════════►│
│  │     [ACTIVE]           [PENDING]          [PENDING]        [PENDING] │
│  │     5 agents           0 agents           0 agents          0 agents │
│  │     Started: 14:11     Est: 15:30         Est: 16:00       Est: 17:00│
│  │                                                                   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ Current Phase: Investigation (ACTIVE)                    [Submit Review]│
│  │                                                                   │  │
│  │ Expected Deliverables:                                            │  │
│  │ • FastAPI backend server                                          │  │
│  │ • React frontend dashboard                                        │  │
│  │ • WebSocket real-time streaming                                   │  │
│  │                                                                   │  │
│  │ Success Criteria:                                                  │  │
│  │ ✓ Dashboard displays all tasks                                    │  │
│  │ ⧗ Agent status updates real-time                                  │  │
│  │ ⧗ Log streaming works                                            │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ Active Agents (5)                                    [Kill All]   │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ data_structure_analyzer-141232 ● working              [View][Kill]│  │
│  │ Type: data_structure_analyzer | Parent: orchestrator              │  │
│  │ Progress: ████░░░░░░░░ 15%                                       │  │
│  │ Last: Found 21 MCP tools, examining workspace...                  │  │
│  │ tmux: agent_data_structure_analyzer-141232-a35bb6 [Attach]       │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ architecture_designer-141234 ● working                [View][Kill]│  │
│  │ Type: architecture_designer | Parent: orchestrator                │  │
│  │ Progress: ██████░░░░░░ 25%                                       │  │
│  │ Last: Designing dashboard stack with FastAPI + React...           │  │
│  │ tmux: agent_architecture_designer-141234-ddf6af [Attach]          │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  [Show More Agents ▼]                                                    │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### 3. Agent Detail View

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ← Back to Task          ui_ux_designer-141239-2b6fd7                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  Agent Information                                                        │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ Type: ui_ux_designer                                              │  │
│  │ Status: ● working                                                 │  │
│  │ Parent: orchestrator                                              │  │
│  │ Phase: Investigation (1/4)                                        │  │
│  │ Started: 2026-01-04 14:12:41                                     │  │
│  │ Progress: ██████░░░░░░ 25%                                       │  │
│  │ tmux Session: agent_ui_ux_designer-141239-2b6fd7                 │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ Controls                                                          │  │
│  │ [Attach tmux] [Kill Agent] [Download Logs] [View Findings]       │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ Live Log Stream                              [⏸ Pause] [Clear]   │  │
│  │ ┌─────────────────────────────────────────────────────────────┐ │  │
│  │ │ [14:12:55] Starting UI/UX design - analyzing structure      │ │  │
│  │ │ [14:13:48] Analyzed data structures and phase machine      │ │  │
│  │ │ [14:13:49] Creating comprehensive UI/UX design mockups     │ │  │
│  │ │ [14:14:02] Designing main dashboard view layout            │ │  │
│  │ │ [14:14:15] Created task card component specification       │ │  │
│  │ │ [14:14:28] Designing phase timeline visualization          │ │  │
│  │ │ [14:14:41] Working on agent status indicators...           │ │  │
│  │ │ ▊                                                          │ │  │
│  │ └─────────────────────────────────────────────────────────────┘ │  │
│  │                                      Auto-scroll enabled ✓       │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ Progress History                                                  │  │
│  │                                                                   │  │
│  │ Time     Status    Progress  Message                             │  │
│  │ 14:12:55 working   0%        Starting UI/UX design               │  │
│  │ 14:13:48 working   25%       Analyzed data structures            │  │
│  │ 14:14:02 working   40%       Creating mockups                    │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ Findings (0)                                          [Refresh]  │  │
│  │                                                                   │  │
│  │ No findings reported yet                                         │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

## Component Specifications

### 1. Task Card Component
```jsx
<TaskCard>
  - Header: Task ID, Priority badge, Expand/Collapse button
  - Description: Task title/description
  - Phase Timeline: Visual phase progression with status colors
  - Agent Summary: Active/Completed/Failed counts
  - Progress Bar: Overall task progress percentage
  - Quick Actions: View Details, Kill All Agents
</TaskCard>
```

### 2. Phase Timeline Component
```jsx
<PhaseTimeline>
  - Horizontal timeline with arrows between phases
  - Color-coded phase status badges
  - Agent count per phase
  - Estimated/actual times
  - Click to jump to phase details
</PhaseTimeline>
```

### 3. Agent Card Component
```jsx
<AgentCard>
  - Status indicator (pulsing for active)
  - Agent type and ID
  - Parent relationship
  - Progress bar with percentage
  - Last update message (truncated)
  - Action buttons: View, Attach, Kill
</AgentCard>
```

### 4. Log Stream Component
```jsx
<LogStream>
  - Virtual scrolling for performance
  - Timestamp prefixes
  - Color-coded by log level
  - Search/filter capability
  - Pause/Resume streaming
  - Copy to clipboard
  - Download full log
</LogStream>
```

### 5. Status Badge Component
```jsx
<StatusBadge>
  - Colored background based on status
  - Optional pulsing animation for active states
  - Tooltip with status details
</StatusBadge>
```

## Interaction Patterns

### 1. Real-time Updates
- WebSocket connection for live updates
- Optimistic UI updates with rollback on error
- Smooth animations for status changes
- Progress bars animate smoothly
- New log lines slide in from bottom

### 2. Progressive Disclosure
- Task cards expand to show more agents
- Agent cards expand to show full details
- Log viewer can toggle between summary and full
- Findings can be filtered by type/severity

### 3. Bulk Actions
- Select multiple agents for bulk kill
- Select multiple tasks for filtering
- Bulk download logs from multiple agents

### 4. Keyboard Shortcuts
```
Space:     Pause/Resume log streaming
Ctrl+F:    Focus search
Ctrl+K:    Command palette
Escape:    Close modals/return to parent view
R:         Refresh current view
T:         Toggle between tasks
```

### 5. Responsive Breakpoints
```css
Desktop:   1280px+ (Full layout with sidebars)
Laptop:    1024px-1279px (Condensed sidebars)
Tablet:    768px-1023px (Stack panels vertically)
Mobile:    <768px (Not supported - monitoring only)
```

## Technical Implementation Notes

### Frontend Stack
- **Framework**: React 18+ with TypeScript
- **State Management**: Zustand for simplicity
- **Styling**: Tailwind CSS for rapid development
- **Real-time**: Socket.io-client for WebSocket
- **Routing**: React Router v6
- **Data Fetching**: TanStack Query (React Query)
- **Virtualization**: react-window for log streams
- **Charts**: Recharts for metrics visualization

### Backend Requirements
- WebSocket endpoint for real-time updates
- REST endpoints for:
  - GET /api/tasks (list all tasks)
  - GET /api/tasks/{id} (task details)
  - GET /api/agents/{id}/logs (stream logs)
  - POST /api/agents/{id}/control (kill/pause)
  - GET /api/phases/{id} (phase details)

### WebSocket Events
```javascript
// Server → Client
socket.emit('task:created', taskData)
socket.emit('task:updated', taskData)
socket.emit('agent:status', agentData)
socket.emit('agent:progress', progressData)
socket.emit('agent:log', logLine)
socket.emit('phase:transition', phaseData)

// Client → Server
socket.emit('subscribe:task', taskId)
socket.emit('subscribe:agent', agentId)
socket.emit('unsubscribe:task', taskId)
socket.emit('control:agent', {agentId, action})
```

## Accessibility Considerations

1. **ARIA Labels**: All interactive elements have proper labels
2. **Keyboard Navigation**: Full keyboard support for all actions
3. **Screen Reader**: Status changes announced via aria-live regions
4. **Color Contrast**: WCAG AA compliant color combinations
5. **Focus Indicators**: Clear visible focus states
6. **Reduced Motion**: Respect prefers-reduced-motion

## Performance Optimizations

1. **Virtual Scrolling**: For log streams and large lists
2. **Debounced Search**: 300ms debounce on search inputs
3. **Lazy Loading**: Load agent details on demand
4. **Memoization**: React.memo for expensive components
5. **WebSocket Reconnection**: Automatic reconnect with backoff
6. **Local Caching**: Cache task/agent data for offline viewing

## Error States

1. **Connection Lost**: Banner with reconnection status
2. **Agent Crashed**: Red badge with error details
3. **Phase Blocked**: Orange warning with resolution steps
4. **Load Failure**: Retry button with error message
5. **Permission Denied**: Lock icon with access request

## Future Enhancements

1. **Metrics Dashboard**: CPU, memory, execution time charts
2. **Agent Collaboration Graph**: Visualize agent interactions
3. **Command Palette**: Quick actions via Cmd+K
4. **Saved Filters**: Save and share view configurations
5. **Export Reports**: Generate PDF/CSV reports
6. **Mobile App**: Native mobile monitoring app
7. **Notifications**: Browser/desktop notifications for events
8. **Dark/Light Theme Toggle**: User preference persistence

## Conclusion

This UI design provides a comprehensive, real-time monitoring solution for the Claude Orchestrator system. The focus on information hierarchy, status visualization, and live updates ensures operators can effectively monitor and control multiple concurrent agent tasks. The progressive disclosure pattern prevents information overload while maintaining quick access to detailed information when needed.