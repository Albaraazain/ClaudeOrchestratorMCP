import React, { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { 
  ArrowLeft, 
  Terminal, 
  FileText, 
  Activity, 
  Clock, 
  Cpu, 
  CheckCircle2, 
  AlertCircle, 
  AlertTriangle, 
  Lightbulb, 
  ShieldAlert 
} from 'lucide-react';
import clsx from 'clsx';
import { useAgentLogs, useAgentDetails } from '../hooks/useAgentLogs';
import type { AgentFinding, AgentProgress } from '../hooks/useAgentLogs';
import { LogViewer } from '../components/LogViewer'; // Assuming this component exists/works

export const AgentDetail: React.FC<{ showLogs?: boolean }> = ({ showLogs = false }) => {
  const { taskId, agentId } = useParams<{ taskId: string; agentId: string }>();
  const [activeTab, setActiveTab] = useState<'logs' | 'findings' | 'progress'>(showLogs ? 'logs' : 'logs');

  // Fetch agent details and logs
  const { agent, findings, progress, isLoading: detailsLoading, error: detailsError } = useAgentDetails({
    taskId: taskId || '',
    agentId: agentId || '',
    enabled: !!(taskId && agentId)
  });

  const { logs, isLoading: logsLoading, error: logsError, metadata } = useAgentLogs({
    taskId: taskId || '',
    agentId: agentId || '',
    enabled: !!(taskId && agentId) && activeTab === 'logs'
  });

  if (!taskId || !agentId) return <div className="p-8 text-center text-error">Missing task or agent ID</div>;
  
  if (detailsLoading && !agent) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  if ((detailsError && !agent) || !agent) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-error">
        <AlertCircle className="w-12 h-12 mb-4" />
        <span className="text-lg">{detailsError || 'Agent not found'}</span>
        <Link to={`/tasks/${taskId}`} className="mt-4 text-primary hover:underline">Back to Task</Link>
      </div>
    );
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed': return 'text-success bg-success/10 border-success/20';
      case 'failed':
      case 'error': return 'text-error bg-error/10 border-error/20';
      case 'running':
      case 'working': return 'text-primary bg-primary/10 border-primary/20';
      case 'blocked': return 'text-warning bg-warning/10 border-warning/20';
      default: return 'text-textMuted bg-surfaceHighlight/50 border-surfaceHighlight';
    }
  };

  const formatDuration = (start?: string, end?: string) => {
     if (!start) return '--';
     const s = new Date(start);
     const e = end ? new Date(end) : new Date();
     const diff = Math.floor((e.getTime() - s.getTime()) / 1000);
     const m = Math.floor(diff / 60);
     const sec = diff % 60;
     return `${m}m ${sec}s`;
  };

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] gap-6">
      {/* Header Card */}
      <div className="flex-shrink-0 bg-surface border border-surfaceHighlight rounded-xl p-6 shadow-xl">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
           <div className="flex items-start gap-4">
              <Link 
                 to={`/tasks/${taskId}`} 
                 className="mt-1 p-2 rounded-lg bg-surfaceHighlight/30 hover:bg-surfaceHighlight/60 text-textMuted hover:text-text transition-colors"
              >
                 <ArrowLeft className="w-5 h-5" />
              </Link>
              <div>
                 <div className="flex items-center gap-3 mb-1">
                    <h1 className="text-2xl font-bold text-text font-mono tracking-tight">{agent.id.substring(0, 8)}...</h1>
                    <span className={clsx("px-2.5 py-0.5 rounded-full text-xs font-medium border uppercase", getStatusColor(agent.status))}>
                       {agent.status}
                    </span>
                 </div>
                 <div className="flex items-center gap-2 text-textMuted text-sm">
                    <span className="font-mono text-primary">{agent.type}</span>
                    <span>•</span>
                    {agent.parent && <Link to={`/tasks/${taskId}/agents/${agent.parent}`} className="hover:text-primary transition-colors">Parent: {agent.parent.substring(0,6)}...</Link>}
                    <span>•</span>
                    <span>Phase {agent.phase_index !== undefined ? agent.phase_index + 1 : '?'}</span>
                 </div>
              </div>
           </div>

           <div className="flex items-center gap-6 text-sm">
              <div className="flex flex-col items-end">
                 <div className="text-textMuted text-xs uppercase tracking-wider mb-1">Duration</div>
                 <div className="font-mono text-text flex items-center gap-2">
                    <Clock className="w-4 h-4 text-secondary" />
                    {formatDuration(agent.started_at, agent.completed_at)}
                 </div>
              </div>
              <div className="flex flex-col items-end">
                 <div className="text-textMuted text-xs uppercase tracking-wider mb-1">Session</div>
                 <div className="font-mono text-text flex items-center gap-2">
                    <Cpu className="w-4 h-4 text-primary" />
                    {agent.tmux_session || 'N/A'}
                 </div>
              </div>
           </div>
        </div>

        {/* Progress Bar (Header) */}
        <div className="mt-6">
           <div className="flex justify-between text-xs text-textMuted mb-1">
              <span>Progress</span>
              <span>{agent.progress}%</span>
           </div>
           <div className="w-full h-2 bg-surfaceHighlight/30 rounded-full overflow-hidden">
              <div 
                 className={clsx(
                    "h-full rounded-full transition-all duration-500",
                    agent.status === 'completed' ? "bg-success" : 
                    agent.status === 'failed' ? "bg-error" : "bg-gradient-to-r from-primary to-secondary"
                 )}
                 style={{ width: `${agent.progress}%` }}
              />
           </div>
        </div>

        {/* Prompt Preview */}
        {agent.prompt && (
           <div className="mt-4 p-3 bg-background/50 border border-surfaceHighlight rounded-lg text-xs font-mono text-textMuted line-clamp-2 hover:line-clamp-none transition-all cursor-help">
              <span className="text-primary font-bold mr-2">$ PROMPT:</span>
              {agent.prompt}
           </div>
        )}
      </div>

      {/* Tabs Navigation */}
      <div className="flex border-b border-surfaceHighlight">
         {[
            { id: 'logs', icon: Terminal, label: 'Live Console', count: metadata?.total_lines },
            { id: 'findings', icon: Lightbulb, label: 'Findings', count: findings.length },
            { id: 'progress', icon: Activity, label: 'Timeline', count: progress.length },
         ].map(tab => (
            <button
               key={tab.id}
               onClick={() => setActiveTab(tab.id as any)}
               className={clsx(
                  "flex items-center gap-2 px-6 py-3 border-b-2 text-sm font-medium transition-colors",
                  activeTab === tab.id 
                     ? "border-primary text-primary" 
                     : "border-transparent text-textMuted hover:text-text hover:border-surfaceHighlight"
               )}
            >
               <tab.icon className="w-4 h-4" />
               {tab.label}
               {tab.count !== undefined && tab.count > 0 && (
                  <span className="px-1.5 py-0.5 rounded-full bg-surfaceHighlight text-xs text-text ml-1">
                     {tab.count}
                  </span>
               )}
            </button>
         ))}
      </div>

      {/* Tab Content */}
      <div className="flex-1 min-h-0 bg-surface border border-surfaceHighlight rounded-xl overflow-hidden shadow-lg relative">
         
         {detailsError && (
            <div className="absolute top-3 right-3 z-10 bg-error/10 border border-error/30 text-error text-xs px-3 py-2 rounded-lg">
               Live updates interrupted: {detailsError}
            </div>
         )}

         {/* LOGS TAB */}
         {activeTab === 'logs' && (
            <div className="h-full min-h-0 font-mono text-sm overflow-hidden">
               {logsLoading && logs.length === 0 ? (
                  <div className="flex items-center gap-2 text-primary animate-pulse">
                     <Terminal className="w-4 h-4" /> Initializing stream...
                  </div>
               ) : (
                  <div className="h-full min-h-0 flex flex-col gap-3">
                     {(logsError || (logsLoading && logs.length > 0)) && (
                        <div className={clsx(
                           "text-xs flex items-center gap-2 px-3 py-2 rounded-lg border",
                           logsError
                              ? "text-error bg-error/10 border-error/30"
                              : "text-textMuted bg-surfaceHighlight/10 border-surfaceHighlight"
                        )}>
                           <AlertCircle className="w-4 h-4" />
                           {logsError ? `Failed to refresh logs: ${logsError}` : 'Refreshing logs…'}
                        </div>
                     )}
                     <LogViewer logs={logs} className="flex-1 min-h-0" />
                  </div>
               )}
            </div>
         )}

         {/* FINDINGS TAB */}
         {activeTab === 'findings' && (
            <div className="h-full overflow-y-auto p-6 space-y-4">
               {findings.length === 0 ? (
                  <div className="text-center py-12 text-textMuted">
                     <Lightbulb className="w-12 h-12 mx-auto mb-3 opacity-20" />
                     No findings reported yet
                  </div>
               ) : (
                  findings.map((f, i) => (
                     <div key={i} className={clsx(
                        "p-4 rounded-lg border flex gap-4",
                        f.severity === 'critical' ? "bg-error/10 border-error/30" :
                        f.severity === 'high' ? "bg-error/5 border-error/20" :
                        f.severity === 'medium' ? "bg-warning/5 border-warning/20" :
                        "bg-surfaceHighlight/10 border-surfaceHighlight"
                     )}>
                        <div className={clsx(
                           "p-2 rounded-lg h-fit",
                           f.finding_type === 'issue' ? "bg-error/20 text-error" :
                           f.finding_type === 'solution' ? "bg-success/20 text-success" :
                           f.finding_type === 'insight' ? "bg-secondary/20 text-secondary" :
                           "bg-primary/20 text-primary"
                        )}>
                           {f.finding_type === 'issue' ? <AlertTriangle className="w-5 h-5" /> :
                            f.finding_type === 'solution' ? <CheckCircle2 className="w-5 h-5" /> :
                            f.finding_type === 'insight' ? <Lightbulb className="w-5 h-5" /> :
                            <FileText className="w-5 h-5" />}
                        </div>
                        <div className="flex-1">
                           <div className="flex justify-between items-start mb-1">
                              <h3 className="font-semibold text-text capitalize flex items-center gap-2">
                                 {f.finding_type}
                                 <span className="text-xs px-2 py-0.5 rounded-full bg-surface border border-surfaceHighlight text-textMuted uppercase">
                                    {f.severity}
                                 </span>
                              </h3>
                              <span className="text-xs text-textMuted">{new Date(f.timestamp).toLocaleTimeString()}</span>
                           </div>
                           <p className="text-textMuted text-sm leading-relaxed">{f.message}</p>
                           {f.data && (
                              <pre className="mt-3 p-3 bg-black/30 rounded border border-white/5 text-xs font-mono text-primary/80 overflow-x-auto">
                                 {JSON.stringify(f.data, null, 2)}
                              </pre>
                           )}
                        </div>
                     </div>
                  ))
               )}
            </div>
         )}

         {/* PROGRESS TAB */}
         {activeTab === 'progress' && (
            <div className="h-full overflow-y-auto p-6 relative">
               <div className="absolute left-9 top-6 bottom-6 w-0.5 bg-surfaceHighlight/50" />
               <div className="space-y-6">
                  {progress.map((p, i) => (
                     <div key={i} className="relative flex gap-6">
                        <div className={clsx(
                           "relative z-10 w-6 h-6 rounded-full border-2 flex items-center justify-center bg-surface",
                           p.status === 'completed' ? "border-success text-success" :
                           p.status === 'failed' ? "border-error text-error" :
                           "border-primary text-primary"
                        )}>
                           <div className={clsx("w-2 h-2 rounded-full", 
                              p.status === 'completed' ? "bg-success" : 
                              p.status === 'failed' ? "bg-error" : "bg-primary"
                           )} />
                        </div>
                        <div className="flex-1 bg-surfaceHighlight/5 border border-surfaceHighlight/50 rounded-lg p-4">
                           <div className="flex justify-between items-center mb-2">
                              <span className={clsx(
                                 "text-xs font-bold uppercase px-2 py-0.5 rounded",
                                 getStatusColor(p.status)
                              )}>
                                 {p.status}
                              </span>
                              <span className="text-xs text-textMuted font-mono">
                                 {new Date(p.timestamp).toLocaleTimeString()} • {p.progress}%
                              </span>
                           </div>
                           <p className="text-sm text-textMuted">{p.message}</p>
                        </div>
                     </div>
                  ))}
               </div>
            </div>
         )}

      </div>
    </div>
  );
};
