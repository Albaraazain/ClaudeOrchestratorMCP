import React, { useEffect, useState, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { format } from 'date-fns';
import {
  Activity,
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Cpu,
  LayoutGrid,
  Loader2,
  MessageSquare,
  ShieldCheck,
  Terminal
} from 'lucide-react';
import clsx from 'clsx';
import { apiService } from '../services/api';
import type { Task, Agent, Finding } from '../types';

// Extended Agent type to include findings locally
interface AgentWithFindings extends Agent {
  recentFindings?: Finding[];
  loadingFindings?: boolean;
}

const TaskBoard: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [agents, setAgents] = useState<AgentWithFindings[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Refs for polling interval
  const findingsIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Fetch Task Details
  const fetchTask = async () => {
    if (!taskId) return;
    try {
      const taskData = await apiService.getTask(taskId);
      setTask(taskData);
      
      // Update agents list, preserving existing findings if agent exists
      setAgents(prevAgents => {
        if (!taskData.agents) return [];
        
        // Filter for active/relevant agents (or show all? user said "running agents", but "track" might imply history too. 
        // Let's show active + recently completed/failed to keep context, or just all. 
        // A board usually implies active work. Let's stick to "Active" + "Recently Completed" logic or just all but sorted.
        // User asked for "track all running agents". Let's focus on non-terminated/non-archived if possible, 
        // but typically "running", "working", "blocked", "reviewing".
        // Let's show ALL but filter visually or sort.
        
        const newAgents = taskData.agents.map(newAgent => {
          const existing = prevAgents.find(a => a.id === newAgent.id || a.agent_id === newAgent.id); // Handle id/agent_id mismatch if any
          // Note: API returns 'id', type def has 'agent_id'. Need to be careful. 
          // TaskDetail.tsx uses 'id'. API schema uses 'id'. Types/index.ts uses 'agent_id'. 
          // Let's assume API returns 'id' matching schema, but we map it if needed.
          // Actually api.ts returns whatever axios returns. Backend sends AgentData with 'id'.
          // So 'newAgent' has 'id'.
          
          return {
            ...newAgent,
            recentFindings: existing?.recentFindings || [],
            loadingFindings: existing?.loadingFindings || false
          };
        });
        return newAgents;
      });
    } catch (err) {
      console.error('Failed to fetch task:', err);
      // Don't set error on poll if we already have data
      if (!task) setError('Failed to load task details');
    } finally {
      setLoading(false);
    }
  };

  // Fetch findings for active agents
  const fetchFindings = async () => {
    if (!taskId || !agents.length) return;

    // Identify active agents to poll findings for
    const activeAgents = agents.filter(a => 
      ['running', 'working', 'blocked', 'reviewing'].includes(a.status)
    );

    // Also fetch for recently completed (last 1 min) maybe? No, stick to active for now to save bandwidth.
    
    await Promise.all(activeAgents.map(async (agent) => {
      try {
        const agentId = agent.id || agent.agent_id;
        const findings = await apiService.getAgentFindings(taskId, agentId, 5); // Get last 5
        
        setAgents(prev => prev.map(a => {
          if ((a.id || a.agent_id) === agentId) {
            return { ...a, recentFindings: findings };
          }
          return a;
        }));
      } catch (e) {
        console.warn(`Failed to fetch findings for agent ${agent.id}`, e);
      }
    }));
  };

  useEffect(() => {
    fetchTask();
    const taskInterval = setInterval(fetchTask, 3000);
    return () => clearInterval(taskInterval);
  }, [taskId]);

  useEffect(() => {
    // Poll findings every 5 seconds
    const interval = setInterval(fetchFindings, 5000);
    return () => clearInterval(interval);
  }, [taskId, agents.length]); // Re-create if agents list length changes significantly (e.g. initial load)


  if (loading && !task) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-12 h-12 text-primary animate-spin" />
      </div>
    );
  }

  if (error || !task) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-error">
        <AlertCircle className="w-12 h-12 mb-4" />
        <span className="text-lg">{error || 'Task not found'}</span>
        <button onClick={() => navigate('/')} className="mt-4 text-primary hover:underline">
          Go back home
        </button>
      </div>
    );
  }

  // Filter agents for the board - Focus on Active, but maybe show sections?
  // "track all running agents" -> Filter for running/working/blocked/reviewing
  const runningAgents = agents.filter(a => ['running', 'working', 'blocked', 'reviewing'].includes(a.status));
  const otherAgents = agents.filter(a => !['running', 'working', 'blocked', 'reviewing'].includes(a.status));

  // Sort: Running agents by last update? Or by ID?
  const sortedRunning = [...runningAgents].sort((a, b) => {
     // Sort by last update desc
     return new Date(b.last_update).getTime() - new Date(a.last_update).getTime();
  });

  return (
    <div className="h-[calc(100vh-4rem)] flex flex-col gap-6 overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 bg-surface border border-surfaceHighlight rounded-xl p-4 shadow-sm flex justify-between items-center">
        <div className="flex items-center gap-4">
          <button 
            onClick={() => navigate(`/tasks/${taskId}`)}
            className="p-2 hover:bg-surfaceHighlight rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5 text-textMuted" />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-text">Live Operations Board</h1>
              <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary text-xs font-medium border border-primary/20">
                {runningAgents.length} Active
              </span>
            </div>
            <p className="text-sm text-textMuted flex items-center gap-2">
              Task: {task.task_id}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
            <button 
                onClick={() => navigate(`/tasks/${taskId}`)}
                className="flex items-center gap-2 px-3 py-2 text-sm font-medium text-textMuted hover:text-text hover:bg-surfaceHighlight rounded-lg transition-colors"
            >
                <LayoutGrid className="w-4 h-4" />
                Detail View
            </button>
        </div>
      </div>

      {/* Board Content */}
      <div className="flex-1 overflow-y-auto p-1">
        {sortedRunning.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 text-textMuted">
            <Activity className="w-12 h-12 mb-4 opacity-20" />
            <p>No active agents running currently.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-4 pb-10">
            {sortedRunning.map(agent => (
              <AgentBoardCard key={agent.id || agent.agent_id} agent={agent} onClick={() => navigate(`/tasks/${taskId}/agents/${agent.id || agent.agent_id}`)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

// Sub-component for individual Agent Card
const AgentBoardCard: React.FC<{ agent: AgentWithFindings; onClick: () => void }> = ({ agent, onClick }) => {
  const isActive = ['running', 'working', 'blocked'].includes(agent.status);
  const isReviewing = agent.status === 'reviewing';
  const isFailed = ['failed', 'error', 'terminated'].includes(agent.status);
  const isCompleted = agent.status === 'completed';

  const statusColor = isActive ? 'text-emerald-500' :
                      isReviewing ? 'text-secondary' :
                      isFailed ? 'text-error' :
                      isCompleted ? 'text-success' : 'text-textMuted';
  
  const borderColor = isActive ? 'border-emerald-500/50' :
                      isReviewing ? 'border-secondary/50' :
                      isFailed ? 'border-error/50' :
                      isCompleted ? 'border-success/50' : 'border-surfaceHighlight';
                      
  const bgColor = isActive ? 'bg-white shadow-[0_0_15px_rgba(16,185,129,0.1)]' : 'bg-surface';

  return (
    <div 
      onClick={onClick}
      className={clsx(
        "rounded-xl border-2 p-4 flex flex-col gap-3 transition-all duration-300 cursor-pointer hover:shadow-lg relative overflow-hidden",
        borderColor,
        bgColor
      )}
    >
        {/* Status Stripe */}
        <div className={clsx(
            "absolute top-0 left-0 right-0 h-1",
            isActive ? "bg-emerald-500" :
            isReviewing ? "bg-secondary" :
            isFailed ? "bg-error" : "bg-textMuted"
        )} />

      {/* Header */}
      <div className="flex justify-between items-start mt-1">
        <div className="flex items-center gap-2">
            <div className={clsx(
                "p-1.5 rounded-lg",
                isActive ? "bg-emerald-100" : "bg-surfaceHighlight"
            )}>
                {isReviewing ? <ShieldCheck className={clsx("w-5 h-5", statusColor)} /> :
                 <Cpu className={clsx("w-5 h-5", statusColor)} />}
            </div>
            <div>
                <h3 className="font-bold text-text text-sm leading-tight">{agent.type}</h3>
                <div className="text-xs text-textMuted font-mono">{(agent.id || agent.agent_id).slice(-8)}</div>
            </div>
        </div>
        <span className={clsx(
            "px-2 py-0.5 rounded-full text-xs font-bold uppercase",
            isActive ? "bg-emerald-100 text-emerald-700" :
            isReviewing ? "bg-secondary/10 text-secondary" :
            isFailed ? "bg-error/10 text-error" : "bg-surfaceHighlight text-textMuted"
        )}>
            {agent.status}
        </span>
      </div>

      {/* Progress */}
      <div className="space-y-1">
        <div className="flex justify-between text-xs text-textMuted">
            <span>Progress</span>
            <span>{agent.progress}%</span>
        </div>
        <div className="h-1.5 w-full bg-surfaceHighlight rounded-full overflow-hidden">
            <div 
                className={clsx("h-full rounded-full transition-all duration-500", 
                    isActive ? "bg-emerald-500" : 
                    isReviewing ? "bg-secondary" : "bg-textMuted"
                )}
                style={{ width: `${agent.progress}%` }}
            />
        </div>
      </div>

      {/* Findings Feed */}
      <div className="flex-1 bg-surfaceHighlight/30 rounded-lg p-2 min-h-[120px] max-h-[160px] overflow-hidden flex flex-col">
        <div className="flex items-center gap-1.5 mb-2 text-xs font-semibold text-textMuted uppercase tracking-wider">
            <MessageSquare className="w-3 h-3" />
            Recent Activity
        </div>
        <div className="space-y-2 overflow-y-auto pr-1 text-xs">
            {agent.recentFindings && agent.recentFindings.length > 0 ? (
                agent.recentFindings.slice(0, 3).map((finding, idx) => (
                    <div key={idx} className="bg-white rounded border border-surfaceHighlight p-2 shadow-sm">
                        <div className="flex items-center gap-1.5 mb-1">
                             <div className={clsx(
                                 "w-1.5 h-1.5 rounded-full",
                                 finding.severity === 'critical' ? 'bg-red-500' :
                                 finding.severity === 'high' ? 'bg-orange-500' :
                                 finding.severity === 'medium' ? 'bg-yellow-500' : 'bg-blue-500'
                             )} />
                             <span className="font-medium text-text truncate">
                                {finding.finding_type}
                             </span>
                             <span className="ml-auto text-[10px] text-textMuted">
                                {format(new Date(finding.timestamp), 'HH:mm:ss')}
                             </span>
                        </div>
                        <p className="text-textMuted leading-snug line-clamp-2">
                            {finding.message}
                        </p>
                    </div>
                ))
            ) : (
                <div className="h-full flex flex-col items-center justify-center text-textMuted opacity-50">
                    <p>No recent findings</p>
                </div>
            )}
        </div>
      </div>

      {/* Footer Info */}
      <div className="flex justify-between items-center text-[10px] text-textMuted font-mono pt-1 border-t border-surfaceHighlight/50">
        <div className="flex items-center gap-1">
            <Terminal className="w-3 h-3" />
            {agent.tmux_session?.slice(-10) || 'N/A'}
        </div>
        <div>
            Updated: {format(new Date(agent.last_update), 'HH:mm:ss')}
        </div>
      </div>

    </div>
  );
}

export default TaskBoard;
