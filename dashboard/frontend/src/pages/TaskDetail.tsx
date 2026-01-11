import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { format } from 'date-fns';
import axios from 'axios';
import {
  Activity,
  CheckCircle2,
  Clock,
  Code2,
  Terminal,
  Cpu,
  GitBranch,
  AlertCircle,
  PlayCircle,
  StopCircle,
  ChevronRight,
  LayoutList,
  LayoutGrid,
  Server,
  ShieldCheck
} from 'lucide-react';
import clsx from 'clsx';

// Types (mirrored from index.ts for convenience/safety)
interface Phase {
  id: string;
  order: number;
  name: string;
  description?: string;
  status: 'PENDING' | 'ACTIVE' | 'AWAITING_REVIEW' | 'UNDER_REVIEW' |
          'APPROVED' | 'REJECTED' | 'REVISING' | 'ESCALATED';
  created_at: string;
  started_at?: string;
  completed_at?: string;
}

interface Agent {
  id: string;
  type: string;
  tmux_session: string;
  parent: string;
  depth: number;
  phase_index: number;
  status: string;
  started_at: string;
  completed_at?: string;
  progress: number;
  last_update: string;
  prompt: string;
}

interface TaskDetails {
  task_id: string;
  task_description: string;
  created_at: string;
  workspace_base: string;
  status: string;
  priority: string;
  phases: Phase[];
  current_phase_index: number;
  agents: Agent[];
  agent_hierarchy: { [key: string]: string[] };
  total_spawned: number;
  active_count: number;
  completed_count: number;
}

const TaskDetail: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [task, setTask] = useState<TaskDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedPhase, setSelectedPhase] = useState<number | null>(null);

  useEffect(() => {
    if (!taskId) return;
    const fetchTask = async () => {
      try {
        setLoading(true);
        // Assuming API is at port 8000
        const response = await axios.get<TaskDetails>(`http://localhost:8000/api/tasks/${taskId}`);
        setTask(response.data);
        setError(null);
      } catch (err) {
        console.error('Failed to fetch task:', err);
        setError('Failed to load task details');
      } finally {
        setLoading(false);
      }
    };
    fetchTask();
    const interval = setInterval(fetchTask, 3000); // Polling
    return () => clearInterval(interval);
  }, [taskId]);

  if (loading && !task) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  if (error || !task) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-error">
        <AlertCircle className="w-12 h-12 mb-4" />
        <span className="text-lg">{error || 'Task not found'}</span>
      </div>
    );
  }

  // Helper to identify reviewer agents
  const isReviewerAgent = (agent: Agent) => agent.type.startsWith('reviewer-') || agent.phase_index === -1;

  // Separate reviewers from regular agents
  const regularAgents = task.agents.filter(a => !isReviewerAgent(a));
  const reviewerAgents = task.agents.filter(a => isReviewerAgent(a));

  // Filter regular agents if a phase is selected
  const visibleAgents = selectedPhase !== null
    ? regularAgents.filter(a => a.phase_index === selectedPhase)
    : regularAgents;

  // Sorting: Active first, then by date
  const sortedAgents = [...visibleAgents].sort((a, b) => {
    const statusScore = (s: string) =>
      ['running', 'working'].includes(s) ? 2 : ['failed', 'error'].includes(s) ? 1 : 0;
    return statusScore(b.status) - statusScore(a.status) ||
           new Date(b.started_at).getTime() - new Date(a.started_at).getTime();
  });

  // Sort reviewers the same way
  const sortedReviewers = [...reviewerAgents].sort((a, b) => {
    const statusScore = (s: string) =>
      ['running', 'working'].includes(s) ? 2 : ['failed', 'error'].includes(s) ? 1 : 0;
    return statusScore(b.status) - statusScore(a.status) ||
           new Date(b.started_at).getTime() - new Date(a.started_at).getTime();
  });

  return (
    <div className="h-[calc(100vh-4rem)] flex flex-col gap-6">
      {/* Top Bar: Task Context */}
      <div className="flex-shrink-0 bg-surface border border-surfaceHighlight rounded-xl p-6 shadow-xl">
        <div className="flex justify-between items-start">
          <div>
            <div className="flex items-center gap-3 mb-2">
               <h1 className="text-2xl font-bold text-text tracking-tight">{task.task_id}</h1>
               <span className={clsx(
                 "px-2.5 py-0.5 rounded-full text-xs font-medium border",
                 task.status === 'ACTIVE' ? "bg-primary/10 text-primary border-primary/20" : "bg-surfaceHighlight/50 text-textMuted border-surfaceHighlight"
               )}>
                 {task.priority}
               </span>
            </div>
            <p className="text-textMuted max-w-3xl">{task.task_description}</p>
          </div>
          <div className="flex items-center gap-6">
            <button 
              onClick={() => navigate(`/tasks/${task.task_id}/board`)}
              className="flex items-center gap-2 px-4 py-2 bg-primary/10 text-primary hover:bg-primary/20 rounded-lg transition-colors font-medium border border-primary/20"
            >
                <LayoutGrid className="w-4 h-4" />
                Board View
            </button>
            <div className="flex gap-8 text-right">
               <div>
                  <div className="text-3xl font-bold text-text">{task.active_count}</div>
                  <div className="text-xs text-textMuted uppercase tracking-wider">Active Agents</div>
               </div>
               <div>
                  <div className="text-3xl font-bold text-secondary">
                    {task.agents.length > 0
                      ? Math.round(task.agents.reduce((sum, a) => sum + a.progress, 0) / task.agents.length)
                      : 0}%
                  </div>
                  <div className="text-xs text-textMuted uppercase tracking-wider">Avg Progress</div>
               </div>
            </div>
          </div>
        </div>
      </div>

      {/* Main Split Content */}
      <div className="flex-1 min-h-0 flex gap-6 overflow-hidden">
        
        {/* LEFT PANE: Phases Timeline */}
        <div className="w-80 flex-shrink-0 flex flex-col bg-surface border border-surfaceHighlight rounded-xl overflow-hidden shadow-lg">
           <div className="p-4 border-b border-surfaceHighlight bg-surfaceHighlight/10 flex items-center justify-between">
              <h2 className="font-semibold text-text flex items-center gap-2">
                 <GitBranch className="w-4 h-4 text-primary" />
                 Execution Phases
              </h2>
           </div>
           <div className="flex-1 overflow-y-auto p-4 space-y-6">
              {task.phases.map((phase, idx) => {
                 const isActive = task.current_phase_index === idx;
                 const isCompleted = phase.status === 'APPROVED' || idx < task.current_phase_index;
                 const isSelected = selectedPhase === idx;

                 return (
                    <div 
                      key={phase.id} 
                      onClick={() => setSelectedPhase(isSelected ? null : idx)}
                      className={clsx(
                        "relative pl-8 transition-all cursor-pointer group",
                        isSelected ? "opacity-100" : (selectedPhase !== null ? "opacity-40 hover:opacity-70" : "opacity-100")
                      )}
                    >
                       {/* Timeline Line */}
                       {idx !== task.phases.length - 1 && (
                          <div className="absolute left-[11px] top-6 bottom-[-24px] w-0.5 bg-surfaceHighlight" />
                       )}
                       
                       {/* Status Dot */}
                       <div className={clsx(
                          "absolute left-0 top-1 w-6 h-6 rounded-full border-2 flex items-center justify-center z-10 transition-colors",
                          isActive ? "border-primary bg-primary/20 animate-pulse-slow" : 
                          isCompleted ? "border-success bg-success/20" : "border-surfaceHighlight bg-surface"
                       )}>
                          {isCompleted ? <CheckCircle2 className="w-3 h-3 text-success" /> : 
                           isActive ? <Activity className="w-3 h-3 text-primary" /> : 
                           <div className="w-2 h-2 rounded-full bg-surfaceHighlight" />}
                       </div>

                       {/* Content */}
                       <div className={clsx(
                          "p-3 rounded-lg border transition-all",
                          isSelected ? "bg-primary/5 border-primary/50" : "bg-transparent border-transparent hover:bg-surfaceHighlight/20"
                       )}>
                          <div className="text-sm font-medium text-text mb-0.5">{phase.name}</div>
                          <div className="text-xs text-textMuted flex items-center gap-2">
                             <span className={clsx(
                                "uppercase font-bold tracking-wider",
                                phase.status === 'ACTIVE' ? "text-primary" :
                                phase.status === 'APPROVED' ? "text-success" :
                                phase.status === 'REJECTED' ? "text-error" : "text-textMuted"
                             )}>{phase.status}</span>
                             {phase.started_at && <span>• {format(new Date(phase.started_at), 'HH:mm')}</span>}
                          </div>
                       </div>
                    </div>
                 );
              })}
           </div>
        </div>

        {/* RIGHT PANE: Agent Console */}
        <div className="flex-1 flex flex-col bg-surface border border-surfaceHighlight rounded-xl overflow-hidden shadow-lg">
           <div className="p-4 border-b border-surfaceHighlight bg-surfaceHighlight/10 flex items-center justify-between">
              <h2 className="font-semibold text-text flex items-center gap-2">
                 <Terminal className="w-4 h-4 text-secondary" />
                 Agent Operations
                 {selectedPhase !== null && <span className="text-textMuted text-xs font-normal ml-2">(Filtered by Phase {selectedPhase + 1})</span>}
              </h2>
              {selectedPhase !== null && (
                 <button onClick={() => setSelectedPhase(null)} className="text-xs text-primary hover:text-primary/80">Clear Filter</button>
              )}
           </div>

           {/* Agent List */}
           <div className="flex-1 overflow-y-auto p-4 space-y-6">
              {/* Reviewer Agents Section */}
              {sortedReviewers.length > 0 && (
                 <div>
                    <div className="flex items-center gap-2 mb-3">
                       <ShieldCheck className="w-4 h-4 text-secondary" />
                       <h3 className="text-sm font-medium text-text">Reviewers</h3>
                       <span className="px-1.5 py-0.5 rounded-full bg-secondary/10 text-secondary text-xs font-medium">{sortedReviewers.length}</span>
                    </div>
                    <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                       {sortedReviewers.map(agent => {
                          const isActive = ['running', 'working', 'blocked'].includes(agent.status);
                          const isCompleted = agent.status === 'completed';
                          const isFailed = ['failed', 'error', 'terminated'].includes(agent.status);

                          return (
                          <div
                            key={agent.id}
                            onClick={() => navigate(`/tasks/${task.task_id}/agents/${agent.id}`)}
                            className={clsx(
                              "group relative rounded-lg p-3 cursor-pointer transition-all duration-300",
                              isActive && "bg-gradient-to-r from-secondary/5 to-secondary/10 border-2 border-secondary/30 shadow-md shadow-secondary/10 hover:shadow-lg hover:border-secondary/50",
                              isCompleted && "bg-success/5 border border-success/20 opacity-70 hover:opacity-100",
                              isFailed && "bg-error/5 border border-error/30",
                              !isActive && !isCompleted && !isFailed && "bg-white border border-surfaceHighlight hover:border-secondary/40 hover:shadow-md"
                            )}
                          >
                             {/* Active pulse */}
                             {isActive && (
                               <div className="absolute -top-1 -right-1 w-2.5 h-2.5">
                                 <span className="absolute inline-flex h-full w-full rounded-full bg-secondary opacity-75 animate-ping" />
                                 <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-secondary" />
                               </div>
                             )}

                             {/* Completed badge */}
                             {isCompleted && (
                               <div className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-success rounded-full flex items-center justify-center shadow-sm">
                                 <CheckCircle2 className="w-3 h-3 text-white" />
                               </div>
                             )}

                             <div className="flex justify-between items-start mb-2">
                                <div className="flex items-center gap-2">
                                   <div className={clsx(
                                      "w-6 h-6 rounded-full flex items-center justify-center",
                                      isActive ? "bg-secondary/20" :
                                      isCompleted ? "bg-success/20" :
                                      isFailed ? "bg-error/20" : "bg-surfaceHighlight"
                                   )}>
                                      <ShieldCheck className={clsx(
                                         "w-3.5 h-3.5",
                                         isActive ? "text-secondary animate-pulse" :
                                         isCompleted ? "text-success" :
                                         isFailed ? "text-error" : "text-textMuted"
                                      )} />
                                   </div>
                                   <div>
                                      <span className={clsx(
                                        "font-mono text-xs font-medium",
                                        isActive ? "text-secondary" :
                                        isCompleted ? "text-success/80" : "text-text"
                                      )}>Reviewer</span>
                                      <span className="font-mono text-xs text-textMuted ml-1">#{agent.id.split('-').pop()?.substring(0,6)}</span>
                                   </div>
                                </div>
                                <span className={clsx(
                                   "px-2 py-0.5 rounded-full text-xs font-semibold uppercase",
                                   isActive ? "bg-secondary/10 text-secondary" :
                                   isCompleted ? "bg-success/10 text-success" :
                                   isFailed ? "bg-error/10 text-error" : "bg-surfaceHighlight text-textMuted"
                                )}>{agent.status}</span>
                             </div>
                             <div className={clsx(
                               "flex items-center justify-between text-xs font-mono",
                               isCompleted ? "text-textMuted/50" : "text-textMuted"
                             )}>
                                <span>Phase review</span>
                                <span className={isActive ? "text-secondary font-semibold" : ""}>{format(new Date(agent.last_update), 'HH:mm:ss')}</span>
                             </div>
                          </div>
                       )})}
                    </div>
                 </div>
              )}

              {/* Work Agents Section */}
              {sortedAgents.length === 0 && sortedReviewers.length === 0 ? (
                 <div className="h-full flex flex-col items-center justify-center text-textMuted">
                    <Cpu className="w-12 h-12 mb-4 opacity-20" />
                    <p>No agents deployed yet</p>
                 </div>
              ) : sortedAgents.length > 0 && (
                 <div>
                    {sortedReviewers.length > 0 && (
                       <div className="flex items-center gap-2 mb-3">
                          <Cpu className="w-4 h-4 text-primary" />
                          <h3 className="text-sm font-semibold text-primary uppercase tracking-wider">Work Agents</h3>
                          <span className="text-xs text-textMuted">({sortedAgents.length})</span>
                       </div>
                    )}
                    <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                       {sortedAgents.map(agent => {
                          const isActive = ['running', 'working', 'blocked'].includes(agent.status);
                          const isCompleted = agent.status === 'completed';
                          const isFailed = ['failed', 'error', 'terminated'].includes(agent.status);

                          return (
                          <div
                            key={agent.id}
                            onClick={() => navigate(`/tasks/${task.task_id}/agents/${agent.id}`)}
                            className={clsx(
                              "group relative rounded-xl p-4 cursor-pointer transition-all duration-300",
                              // Active: clean with glowing green border
                              isActive && "bg-white border border-emerald-400/60 shadow-[0_0_15px_rgba(16,185,129,0.15)] hover:shadow-[0_0_25px_rgba(16,185,129,0.25)] hover:border-emerald-400",
                              // Completed: subtle success tint, muted
                              isCompleted && "bg-gradient-to-br from-success/5 to-success/10 border border-success/20 opacity-75 hover:opacity-100 hover:shadow-md",
                              // Failed: error tint
                              isFailed && "bg-gradient-to-br from-error/5 to-error/10 border border-error/30 hover:shadow-md hover:shadow-error/10",
                              // Default/other
                              !isActive && !isCompleted && !isFailed && "bg-white border border-surfaceHighlight hover:border-primary/30 hover:shadow-md"
                            )}
                          >
                             {/* Active indicator pulse ring */}
                             {isActive && (
                               <div className="absolute -top-1 -right-1 w-3 h-3">
                                 <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75 animate-ping" />
                                 <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500" />
                               </div>
                             )}

                             {/* Completed checkmark badge */}
                             {isCompleted && (
                               <div className="absolute -top-2 -right-2 w-6 h-6 bg-success rounded-full flex items-center justify-center shadow-sm">
                                 <CheckCircle2 className="w-4 h-4 text-white" />
                               </div>
                             )}

                             {/* Failed X badge */}
                             {isFailed && (
                               <div className="absolute -top-2 -right-2 w-6 h-6 bg-error rounded-full flex items-center justify-center shadow-sm">
                                 <AlertCircle className="w-4 h-4 text-white" />
                               </div>
                             )}

                             <div className="flex justify-between items-start mb-3">
                                <div className="flex items-center gap-2">
                                   <div className={clsx(
                                      "w-2.5 h-2.5 rounded-full ring-2 ring-offset-1",
                                      isActive ? "bg-emerald-500 ring-emerald-300 animate-pulse" :
                                      isCompleted ? "bg-success ring-success/30" :
                                      isFailed ? "bg-error ring-error/30" : "bg-textMuted ring-textMuted/30"
                                   )} />
                                   <span className={clsx(
                                     "font-mono text-sm font-bold",
                                     isActive ? "text-emerald-600" :
                                     isCompleted ? "text-success/80" :
                                     isFailed ? "text-error/80" : "text-textMuted"
                                   )}>{agent.type}</span>
                                </div>
                                <div className="flex items-center gap-2">
                                   <span className={clsx(
                                      "px-2 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wide",
                                      isActive ? "bg-emerald-50 text-emerald-600" :
                                      isCompleted ? "bg-success/10 text-success" :
                                      isFailed ? "bg-error/10 text-error" : "bg-surfaceHighlight text-textMuted"
                                   )}>{agent.status}</span>
                                   <ChevronRight className={clsx(
                                     "w-4 h-4 transition-colors",
                                     isActive ? "text-emerald-400 group-hover:text-emerald-600" : "text-surfaceHighlight group-hover:text-textMuted"
                                   )} />
                                </div>
                             </div>

                             <div className={clsx(
                               "font-mono text-xs mb-3 line-clamp-2 min-h-[2.5em]",
                               isCompleted ? "text-textMuted/60" : "text-textMuted"
                             )}>
                                {agent.prompt || "No prompt available"}
                             </div>

                             {/* Progress Bar - more prominent for active */}
                             <div className={clsx(
                               "w-full rounded-full overflow-hidden mb-3",
                               isActive ? "h-1.5 bg-emerald-100" : "h-1 bg-surfaceHighlight/50"
                             )}>
                                <div
                                  className={clsx(
                                     "h-full rounded-full transition-all duration-500",
                                     isActive && "bg-emerald-500",
                                     isCompleted && "bg-success",
                                     isFailed && "bg-error",
                                     !isActive && !isCompleted && !isFailed && "bg-textMuted"
                                  )}
                                  style={{ width: `${agent.progress}%` }}
                                />
                             </div>

                             <div className={clsx(
                               "flex items-center justify-between text-xs font-mono",
                               isCompleted ? "text-textMuted/50" : "text-textMuted/70"
                             )}>
                                <div className="flex gap-3">
                                   <span className="flex items-center gap-1"><LayoutList className="w-3 h-3" /> D:{agent.depth}</span>
                                   <span className="flex items-center gap-1"><Server className="w-3 h-3" /> {agent.tmux_session?.slice(-8) || 'N/A'}</span>
                                </div>
                                <span className={clsx(
                                  "font-semibold",
                                  isActive && "text-emerald-600"
                                )}>{format(new Date(agent.last_update), 'HH:mm:ss')}</span>
                             </div>
                          </div>
                       )})}
                    </div>
                 </div>
              )}
           </div>
        </div>

      </div>
    </div>
  );
};

export default TaskDetail;
