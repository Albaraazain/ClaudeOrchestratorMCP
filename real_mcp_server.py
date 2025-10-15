#!/usr/bin/env python3
"""
Claude Orchestrator MCP Server

A Model Context Protocol (MCP) server for managing headless Claude agent orchestration
with tmux-based background execution and comprehensive progress tracking.

Author: Claude Code Orchestrator Project
License: MIT
"""

from fastmcp import FastMCP
from typing import Dict, List, Optional, Any
import json
import os
import subprocess
import uuid
import time
import logging
from datetime import datetime
from pathlib import Path
import sys
import re

# Initialize MCP server
mcp = FastMCP("Claude Orchestrator")

# Configuration
# WORKSPACE_BASE: Set via CLAUDE_ORCHESTRATOR_WORKSPACE env var to control where task workspaces are created
# Example: export CLAUDE_ORCHESTRATOR_WORKSPACE=/Users/yourname/Developer/Projects/yourproject/.agent-workspace
# Default: Creates .agent-workspace in the MCP server's directory
WORKSPACE_BASE = os.getenv('CLAUDE_ORCHESTRATOR_WORKSPACE', os.path.abspath('.agent-workspace'))
DEFAULT_MAX_AGENTS = int(os.getenv('CLAUDE_ORCHESTRATOR_MAX_AGENTS', '25'))
DEFAULT_MAX_CONCURRENT = int(os.getenv('CLAUDE_ORCHESTRATOR_MAX_CONCURRENT', '8'))
DEFAULT_MAX_DEPTH = int(os.getenv('CLAUDE_ORCHESTRATOR_MAX_DEPTH', '5'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def find_task_workspace(task_id: str) -> str:
    """
    Find the workspace directory for a given task ID.
    Searches in multiple locations:
    1. Server's WORKSPACE_BASE
    2. Common project locations (if task was created with client_cwd)
    
    Returns the workspace path or None if not found.
    """
    # Check server's default workspace
    workspace = f"{WORKSPACE_BASE}/{task_id}"
    if os.path.exists(f"{workspace}/AGENT_REGISTRY.json"):
        return workspace
    
    # Search in common project locations (for tasks created with client_cwd)
    # Look for .agent-workspace directories in parent directories
    current_dir = os.getcwd()
    for _ in range(5):  # Search up to 5 levels up
        candidate = os.path.join(current_dir, '.agent-workspace', task_id)
        if os.path.exists(f"{candidate}/AGENT_REGISTRY.json"):
            logger.info(f"Found task {task_id} in client workspace: {candidate}")
            return candidate
        parent = os.path.dirname(current_dir)
        if parent == current_dir:  # Reached root
            break
        current_dir = parent
    
    # Also check if WORKSPACE_BASE contains the task directly
    if os.path.exists(f"{WORKSPACE_BASE}/{task_id}/AGENT_REGISTRY.json"):
        return f"{WORKSPACE_BASE}/{task_id}"
    
    return None

def ensure_workspace():
    """Ensure workspace directory structure exists with proper initialization."""
    try:
        os.makedirs(f"{WORKSPACE_BASE}/registry", exist_ok=True)
        
        global_reg_path = f"{WORKSPACE_BASE}/registry/GLOBAL_REGISTRY.json"
        if not os.path.exists(global_reg_path):
            initial_registry = {
                "created_at": datetime.now().isoformat(),
                "total_tasks": 0,
                "active_tasks": 0,
                "total_agents_spawned": 0,
                "active_agents": 0,
                "max_concurrent_agents": DEFAULT_MAX_CONCURRENT,
                "tasks": {},
                "agents": {}
            }
            with open(global_reg_path, 'w') as f:
                json.dump(initial_registry, f, indent=2)
        logger.info(f"Workspace initialized at {WORKSPACE_BASE}")
    except Exception as e:
        logger.error(f"Failed to initialize workspace: {e}")
        raise

def check_tmux_available():
    """Check if tmux is available"""
    try:
        result = subprocess.run(['tmux', '-V'], capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("tmux not available or not responding")
        return False

def create_tmux_session(session_name: str, command: str, working_dir: str = None) -> Dict[str, Any]:
    """Create a tmux session to run Claude in background."""
    try:
        cmd = ['tmux', 'new-session', '-d', '-s', session_name]
        if working_dir:
            cmd.extend(['-c', working_dir])
        cmd.append(command)
        
        logger.info(f"Creating tmux session '{session_name}' with command: {command[:100]}...")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=working_dir, timeout=30)
        
        if result.returncode == 0:
            logger.info(f"Successfully created tmux session '{session_name}'")
            return {
                "success": True,
                "session_name": session_name,
                "command": command,
                "output": result.stdout,
                "error": result.stderr
            }
        else:
            logger.error(f"Failed to create tmux session '{session_name}': {result.stderr}")
            return {
                "success": False,
                "error": f"Failed to create tmux session: {result.stderr}",
                "return_code": result.returncode
            }
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout creating tmux session '{session_name}'")
        return {
            "success": False,
            "error": "Timeout creating tmux session"
        }
    except Exception as e:
        logger.error(f"Exception creating tmux session '{session_name}': {e}")
        return {
            "success": False,
            "error": f"Exception creating tmux session: {str(e)}"
        }

def get_tmux_session_output(session_name: str) -> str:
    """Capture output from tmux session"""
    try:
        result = subprocess.run([
            'tmux', 'capture-pane', '-t', session_name, '-p'
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            return result.stdout
        return f"Error capturing output: {result.stderr}"
    except Exception as e:
        return f"Exception capturing output: {str(e)}"

def check_tmux_session_exists(session_name: str) -> bool:
    """Check if tmux session exists"""
    try:
        result = subprocess.run([
            'tmux', 'has-session', '-t', session_name
        ], capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False

def kill_tmux_session(session_name: str) -> bool:
    """Kill a tmux session"""
    try:
        result = subprocess.run([
            'tmux', 'kill-session', '-t', session_name
        ], capture_output=True, text=True)
        return result.returncode == 0
    except Exception:
        return False

def calculate_task_complexity(description: str) -> int:
    """Calculate task complexity to guide orchestration depth"""
    complexity_keywords = {
        'comprehensive': 5, 'complete': 4, 'full': 4, 'entire': 4,
        'system': 3, 'platform': 3, 'application': 3, 'website': 2,
        'frontend': 2, 'backend': 2, 'database': 2, 'api': 2,
        'testing': 2, 'security': 2, 'performance': 2, 'optimization': 2,
        'deployment': 2, 'ci/cd': 2, 'monitoring': 2, 'analytics': 2,
        'authentication': 2, 'authorization': 2, 'integration': 2
    }
    
    score = 1  # Base complexity
    description_lower = description.lower()
    
    for keyword, points in complexity_keywords.items():
        if keyword in description_lower:
            score += points
    
    # Additional factors
    if len(description) > 200:
        score += 2
    if 'layers' in description_lower or 'multi' in description_lower:
        score += 3
    if 'specialist' in description_lower or 'expert' in description_lower:
        score += 2
        
    return min(score, 20)  # Cap at 20

def generate_specialization_recommendations(task_description: str, current_depth: int) -> List[str]:
    """Dynamically recommend specialist agent types based on task context"""
    description_lower = task_description.lower()
    
    # Domain detection patterns
    domain_patterns = {
        'frontend': ['frontend', 'ui', 'ux', 'react', 'vue', 'angular', 'css', 'javascript', 'html'],
        'backend': ['backend', 'api', 'server', 'database', 'sql', 'node', 'python', 'java'],
        'design': ['design', 'ui/ux', 'visual', 'branding', 'typography', 'layout', 'user experience'],
        'data': ['data', 'analytics', 'metrics', 'tracking', 'database', 'sql', 'mongodb'],
        'security': ['security', 'auth', 'authentication', 'authorization', 'encryption', 'ssl'],
        'performance': ['performance', 'optimization', 'speed', 'caching', 'load', 'scalability'],
        'testing': ['testing', 'qa', 'test', 'validation', 'e2e', 'unit test', 'integration'],
        'devops': ['deployment', 'ci/cd', 'docker', 'kubernetes', 'infrastructure', 'monitoring'],
        'mobile': ['mobile', 'ios', 'android', 'react native', 'flutter', 'responsive'],
        'ai_ml': ['ai', 'ml', 'machine learning', 'recommendation', 'algorithm', 'intelligence']
    }
    
    recommendations = []
    
    for domain, keywords in domain_patterns.items():
        if any(keyword in description_lower for keyword in keywords):
            if current_depth == 1:
                # First level: broad coordinators
                recommendations.append(f"{domain}_lead")
            elif current_depth == 2:
                # Second level: specific specialists
                if domain == 'frontend':
                    recommendations.extend(['css_specialist', 'js_specialist', 'component_specialist', 'animation_specialist'])
                elif domain == 'backend':
                    recommendations.extend(['api_specialist', 'database_specialist', 'auth_specialist', 'integration_specialist'])
                elif domain == 'design':
                    recommendations.extend(['visual_designer', 'ux_researcher', 'interaction_designer', 'brand_specialist'])
                elif domain == 'data':
                    recommendations.extend(['data_engineer', 'analytics_specialist', 'visualization_expert', 'etl_specialist'])
            elif current_depth >= 3:
                # Deeper levels: hyper-specialized micro-agents
                recommendations.extend([
                    f"{domain}_optimizer", f"{domain}_validator", f"{domain}_implementer", f"{domain}_tester"
                ])
    
    # Always recommend some general specialists for comprehensive coverage
    if current_depth <= 2:
        recommendations.extend(['architect', 'quality_assurance', 'documentation_specialist'])
    
    return list(set(recommendations))  # Remove duplicates

def create_orchestration_guidance_prompt(agent_type: str, task_description: str, current_depth: int, max_depth: int) -> str:
    """Generate dynamic guidance for orchestration based on context"""
    complexity = calculate_task_complexity(task_description)
    recommendations = generate_specialization_recommendations(task_description, current_depth + 1)
    
    if current_depth >= max_depth - 1:
        return "\n⚠️  DEPTH LIMIT REACHED - Focus on implementation rather than spawning children."
    
    # Determine orchestration intensity based on complexity and depth
    if complexity >= 15:
        intensity = "STRONGLY ENCOURAGED"
        child_count = "3-4 child agents"
    elif complexity >= 10:
        intensity = "ENCOURAGED"
        child_count = "2-3 child agents"
    else:
        intensity = "may consider"
        child_count = "1-2 child agents"
    
    guidance = f"""

🎯 ORCHESTRATION GUIDANCE (Depth {current_depth}/{max_depth}, Complexity: {complexity}/20):

You are {intensity} to spawn specialized child agents for better implementation quality.

RECOMMENDED CHILD SPECIALISTS:
{chr(10).join(f'• {agent}' for agent in recommendations[:6])}

🚀 ORCHESTRATION STRATEGY:
1. ANALYZE if your task benefits from specialization
2. SPAWN {child_count} with focused, specific roles
3. COORDINATE their work efficiently
4. Each child should handle a distinct domain

💡 NAMING CONVENTION: Use clear, descriptive names:
   - 'css_responsive_specialist' not just 'css'
   - 'api_authentication_handler' not just 'auth'
   - 'database_optimization_expert' not just 'db'

⭐ SUCCESS CRITERIA: Balance specialization with efficiency:
   - Spawn specialists only when beneficial
   - Coordinate effectively without micro-management
   - Deliver comprehensive, integrated results"""
    
    return guidance

def create_agent_wrapper(agent_id: str, workspace: str, agent_prompt: str) -> str:
    """Create a wrapper script with progress enforcement for an agent"""
    wrapper_path = f"{workspace}/wrapper_{agent_id}.sh"
    
    # Enhanced wrapper with progress enforcement
    wrapper_content = f'''#!/bin/bash

# Auto-generated Agent Wrapper with Progress Enforcement
# Agent ID: {agent_id}
# Workspace: {workspace}

AGENT_ID="{agent_id}"
WORKSPACE="{workspace}"
CHECKPOINT_INTERVAL=90  # Force progress every 90 seconds
PROGRESS_FILE="$WORKSPACE/progress/${{AGENT_ID}}_progress.jsonl"

echo "🤖 Starting Wrapped Agent: $AGENT_ID with Progress Enforcement"

# Create initial progress entry
echo "{{\\"timestamp\\": \\"$(date -Iseconds)\\", \\"agent_id\\": \\"$AGENT_ID\\", \\"action\\": \\"wrapper_init\\", \\"sub_task\\": \\"Agent Wrapper Startup\\", \\"sub_progress\\": 0, \\"overall_progress\\": 0, \\"status\\": \\"starting\\", \\"context\\": \\"Agent wrapper initializing with progress enforcement\\", \\"eta_subtask\\": \\"30s\\", \\"eta_overall\\": \\"estimated\\"}}" >> "$PROGRESS_FILE"

# Task phases for structured execution
TASK_PHASES=(
    "Phase 1: Analysis and Planning"
    "Phase 2: Core Implementation" 
    "Phase 3: Testing and Validation"
    "Phase 4: Documentation and Completion"
)

for i in "${{!TASK_PHASES[@]}}"; do
    PHASE="${{TASK_PHASES[$i]}}"
    PROGRESS=$(((i + 1) * 25))
    
    echo "🔄 Starting $PHASE"
    
    # Log phase start
    echo "{{\\"timestamp\\": \\"$(date -Iseconds)\\", \\"agent_id\\": \\"$AGENT_ID\\", \\"action\\": \\"phase_start\\", \\"sub_task\\": \\"$PHASE\\", \\"sub_progress\\": 0, \\"overall_progress\\": $PROGRESS, \\"status\\": \\"working\\", \\"context\\": \\"Starting $PHASE\\", \\"eta_subtask\\": \\"${{CHECKPOINT_INTERVAL}}s\\", \\"eta_overall\\": \\"${{CHECKPOINT_INTERVAL}}s\\"}}" >> "$PROGRESS_FILE"
    
    # Create phase-specific prompt
    PHASE_PROMPT="{agent_prompt}

CURRENT EXECUTION PHASE: $PHASE (Progress Target: $PROGRESS%)

CRITICAL PHASE REQUIREMENTS:
1. Focus ONLY on this phase of the task
2. You have exactly $CHECKPOINT_INTERVAL seconds for this phase
3. MUST create progress update in $PROGRESS_FILE when done
4. Use this exact format for progress updates:
   echo '{{\\"timestamp\\": \\"$(date -Iseconds)\\", \\"agent_id\\": \\"$AGENT_ID\\", \\"action\\": \\"phase_complete\\", \\"sub_task\\": \\"$PHASE\\", \\"sub_progress\\": 100, \\"overall_progress\\": $PROGRESS, \\"status\\": \\"completed\\", \\"context\\": \\"Completed $PHASE successfully\\", \\"eta_subtask\\": \\"0s\\", \\"eta_overall\\": \\"estimated\\"}}' >> $PROGRESS_FILE

PHASE-SPECIFIC INSTRUCTIONS:
- Phase 1: Plan your approach, analyze requirements, set up workspace
- Phase 2: Implement core functionality, create main files  
- Phase 3: Test your implementation, fix bugs, validate requirements
- Phase 4: Document your work, create completion summary

BEGIN $PHASE NOW!"

    # Execute Claude for this phase with timeout enforcement - model is sonnet (Claude Sonnet 4.5)
    timeout $CHECKPOINT_INTERVAL claude --dangerously-skip-permissions --print --model sonnet "$PHASE_PROMPT" || {{
        echo "⏰ Phase timeout - enforcing checkpoint"
        echo "{{\\"timestamp\\": \\"$(date -Iseconds)\\", \\"agent_id\\": \\"$AGENT_ID\\", \\"action\\": \\"timeout_checkpoint\\", \\"sub_task\\": \\"$PHASE\\", \\"sub_progress\\": 50, \\"overall_progress\\": $PROGRESS, \\"status\\": \\"checkpoint\\", \\"context\\": \\"Forced checkpoint due to ${{CHECKPOINT_INTERVAL}}s timeout\\", \\"eta_subtask\\": \\"0s\\", \\"eta_overall\\": \\"estimated\\"}}" >> "$PROGRESS_FILE"
    }}
    
    # Brief pause between phases
    sleep 2
    
    echo "✅ $PHASE completed with progress enforcement"
done

# Final completion
echo "{{\\"timestamp\\": \\"$(date -Iseconds)\\", \\"agent_id\\": \\"$AGENT_ID\\", \\"action\\": \\"wrapper_complete\\", \\"sub_task\\": \\"All Phases Complete\\", \\"sub_progress\\": 100, \\"overall_progress\\": 100, \\"status\\": \\"completed\\", \\"context\\": \\"Agent wrapper completed all phases successfully\\", \\"eta_subtask\\": \\"0s\\", \\"eta_overall\\": \\"0s\\"}}" >> "$PROGRESS_FILE"

echo "🎉 Wrapped Agent $AGENT_ID completed successfully!"
'''
    
    # Write wrapper script
    with open(wrapper_path, 'w') as f:
        f.write(wrapper_content)
    
    # Make executable
    os.chmod(wrapper_path, 0o755)
    
    return wrapper_path

@mcp.tool
def create_real_task(description: str, priority: str = "P2", client_cwd: str = None) -> Dict[str, Any]:
    """
    Create a real orchestration task with proper workspace.
    
    Args:
        description: Description of the task
        priority: Task priority
        client_cwd: Optional client working directory (defaults to server's location if not provided)
    
    Returns:
        Task creation result
    """
    ensure_workspace()
    
    # Use client's working directory if provided, otherwise use server's WORKSPACE_BASE
    if client_cwd:
        workspace_base = os.path.join(client_cwd, '.agent-workspace')
        logger.info(f"Using client workspace: {workspace_base}")
    else:
        workspace_base = WORKSPACE_BASE
        logger.info(f"Using server workspace: {workspace_base}")
    
    # Ensure client workspace directory exists
    os.makedirs(workspace_base, exist_ok=True)
    
    # Generate task ID
    task_id = f"TASK-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    workspace = f"{workspace_base}/{task_id}"
    
    # Create task workspace
    os.makedirs(f"{workspace}/progress", exist_ok=True)
    os.makedirs(f"{workspace}/logs", exist_ok=True)
    os.makedirs(f"{workspace}/findings", exist_ok=True)
    os.makedirs(f"{workspace}/output", exist_ok=True)  # For agent outputs
    
    # Create task registry
    registry = {
        "task_id": task_id,
        "task_description": description,
        "created_at": datetime.now().isoformat(),
        "workspace": workspace,
        "status": "INITIALIZED",
        "priority": priority,
        "agents": [],
        "agent_hierarchy": {"orchestrator": []},
        "max_agents": DEFAULT_MAX_AGENTS,
        "max_depth": DEFAULT_MAX_DEPTH,
        "max_concurrent": DEFAULT_MAX_CONCURRENT,
        "total_spawned": 0,
        "active_count": 0,
        "completed_count": 0,
        "orchestration_guidance": {
            "min_specialization_depth": 2,  # Encourage at least 2 layers (practical minimum)
            "recommended_child_agents_per_parent": 3,  # Each parent should spawn ~3 children (manageable)
            "specialization_domains": [],  # Dynamic list of identified domains
            "complexity_score": calculate_task_complexity(description)
        },
        "spiral_checks": {
            "enabled": True,
            "last_check": datetime.now().isoformat(),
            "violations": 0
        }
    }
    
    with open(f"{workspace}/AGENT_REGISTRY.json", 'w') as f:
        json.dump(registry, f, indent=2)
    
    # Update global registry
    global_reg_path = f"{WORKSPACE_BASE}/registry/GLOBAL_REGISTRY.json"
    with open(global_reg_path, 'r') as f:
        global_reg = json.load(f)
    
    global_reg['total_tasks'] += 1
    global_reg['active_tasks'] += 1
    global_reg['tasks'][task_id] = {
        'description': description,
        'created_at': datetime.now().isoformat(),
        'status': 'INITIALIZED'
    }
    
    with open(global_reg_path, 'w') as f:
        json.dump(global_reg, f, indent=2)
    
    return {
        "success": True,
        "task_id": task_id,
        "description": description,
        "priority": priority,
        "workspace": workspace,
        "status": "INITIALIZED"
    }

@mcp.tool  
def deploy_headless_agent(
    task_id: str,
    agent_type: str, 
    prompt: str,
    parent: str = "orchestrator"
) -> Dict[str, Any]:
    """
    Deploy a headless Claude agent using tmux for background execution.
    
    Args:
        task_id: Task ID to deploy agent for
        agent_type: Type of agent (investigator, fixer, etc.)
        prompt: Instructions for the agent
        parent: Parent agent ID
    
    Returns:
        Agent deployment result
    """
    if not check_tmux_available():
        logger.error("tmux not available for agent deployment")
        return {
            "success": False,
            "error": "tmux is not available - required for background execution"
        }
    
    # Find the task workspace (may be in client or server location)
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
    
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    
    # Load registry
    with open(registry_path, 'r') as f:
        registry = json.load(f)
    
    # Anti-spiral checks
    if registry['active_count'] >= registry['max_concurrent']:
        return {
            "success": False,
            "error": f"Too many active agents ({registry['active_count']}/{registry['max_concurrent']})"
        }
    
    if registry['total_spawned'] >= registry['max_agents']:
        return {
            "success": False,
            "error": f"Max agents reached ({registry['total_spawned']}/{registry['max_agents']})"
        }
    
    # Generate agent ID and session name
    agent_id = f"{agent_type}-{datetime.now().strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"
    session_name = f"agent_{agent_id}"
    
    # Calculate agent depth based on parent
    depth = 1 if parent == "orchestrator" else 2
    if parent != "orchestrator":
        # Try to find parent depth and increment
        with open(registry_path, 'r') as f:
            registry = json.load(f)
        for agent in registry['agents']:
            if agent['id'] == parent:
                depth = agent.get('depth', 1) + 1
                break
    
    # Load registry to get task description for orchestration guidance
    with open(registry_path, 'r') as f:
        task_registry = json.load(f)
    
    task_description = task_registry.get('task_description', '')
    max_depth = task_registry.get('max_depth', 5)
    orchestration_prompt = create_orchestration_guidance_prompt(agent_type, task_description, depth, max_depth)
    
    # Create comprehensive agent prompt with MCP self-reporting capabilities
    agent_prompt = f"""You are a headless Claude agent in an orchestrator system.

🤖 AGENT IDENTITY:
- Agent ID: {agent_id}  
- Agent Type: {agent_type}
- Task ID: {task_id}
- Parent Agent: {parent}
- Depth Level: {depth}
- Workspace: {workspace}

📝 YOUR MISSION:
{prompt}

{orchestration_prompt}

🔗 MCP SELF-REPORTING WITH COORDINATION - You MUST use these MCP functions to report progress:

1. PROGRESS UPDATES (every few minutes):
```
mcp__claude-orchestrator__update_agent_progress
Parameters: 
- task_id: "{task_id}"
- agent_id: "{agent_id}"  
- status: "working" | "blocked" | "completed" | "error"
- message: "Description of current work"
- progress: 0-100 (percentage)

RETURNS: Your update confirmation + comprehensive status of ALL agents for coordination!
- coordination_info.agents: Status of all other agents
- coordination_info.coordination_data.recent_progress: Latest progress from all agents
- coordination_info.coordination_data.recent_findings: Latest discoveries from all agents
```

2. REPORT FINDINGS (whenever you discover something important):
```
mcp__claude-orchestrator__report_agent_finding
Parameters:
- task_id: "{task_id}"
- agent_id: "{agent_id}"
- finding_type: "issue" | "solution" | "insight" | "recommendation"
- severity: "low" | "medium" | "high" | "critical"  
- message: "What you discovered"
- data: {{"any": "additional info"}}

RETURNS: Your finding confirmation + comprehensive status of ALL agents for coordination!
- coordination_info.agents: Status of all other agents
- coordination_info.coordination_data.recent_progress: Latest progress from all agents
- coordination_info.coordination_data.recent_findings: Latest discoveries from all agents
```

💡 COORDINATION ADVANTAGE: Every time you update progress or report a finding, you'll receive:
- Complete status of all other agents working on this task
- Their latest progress updates and discoveries
- Opportunity to coordinate and avoid duplicate work
- Insights to build upon others' findings

3. SPAWN CHILD AGENTS (if you need specialized help):
```
mcp__claude-orchestrator__spawn_child_agent
Parameters:
- task_id: "{task_id}"
- parent_agent_id: "{agent_id}"
- child_agent_type: "investigator" | "builder" | "fixer" | etc
- child_prompt: "Specific task for the child agent"
```

🚨 CRITICAL PROTOCOL:
1. START by calling update_agent_progress with status="working", progress=0
2. REGULARLY update progress every few minutes  
3. REPORT key findings as you discover them
4. SPAWN child agents if you need specialized help
5. END by calling update_agent_progress with status="completed", progress=100

You are working independently but can coordinate through the MCP orchestrator system.

BEGIN YOUR WORK NOW!
"""
    
    try:
        # Store agent prompt in file for tmux execution with absolute path
        prompt_file = os.path.abspath(f"{workspace}/agent_prompt_{agent_id}.txt")
        with open(prompt_file, 'w') as f:
            f.write(agent_prompt)
            
        # Run Claude in the calling project's directory, not the orchestrator workspace
        calling_project_dir = os.getcwd()
        claude_executable = os.getenv('CLAUDE_EXECUTABLE', 'claude')
        claude_flags = os.getenv('CLAUDE_FLAGS', '--print --output-format stream-json --verbose --dangerously-skip-permissions --model sonnet')
        
        # Escape the prompt for shell and pass as argument (not stdin redirection)
        escaped_prompt = agent_prompt.replace("'", "'\"'\"'")
        claude_command = f"cd '{calling_project_dir}' && {claude_executable} {claude_flags} '{escaped_prompt}'"
        
        # Create the session in the calling project directory 
        session_result = create_tmux_session(
            session_name=session_name,
            command=claude_command,
            working_dir=calling_project_dir
        )
        
        if not session_result["success"]:
            return {
                "success": False,
                "error": f"Failed to create agent session: {session_result['error']}"
            }
        
        # Give Claude a moment to start
        time.sleep(2)
        
        # Check if session is still running
        if not check_tmux_session_exists(session_name):
            return {
                "success": False,
                "error": "Agent session terminated immediately after creation"
            }
        
        # Update registry with new agent
        agent_data = {
            "id": agent_id,
            "type": agent_type,
            "tmux_session": session_name,
            "parent": parent,
            "depth": 1 if parent == "orchestrator" else 2,
            "status": "running",
            "started_at": datetime.now().isoformat(),
            "progress": 0,
            "last_update": datetime.now().isoformat(),
            "prompt": prompt[:200] + "..." if len(prompt) > 200 else prompt
        }
        
        registry['agents'].append(agent_data)
        registry['total_spawned'] += 1
        registry['active_count'] += 1
        
        # Update hierarchy
        if parent not in registry['agent_hierarchy']:
            registry['agent_hierarchy'][parent] = []
        registry['agent_hierarchy'][parent].append(agent_id)
        
        # Save updated registry
        with open(registry_path, 'w') as f:
            json.dump(registry, f, indent=2)
        
        # Update global registry
        global_reg_path = f"{WORKSPACE_BASE}/registry/GLOBAL_REGISTRY.json"
        with open(global_reg_path, 'r') as f:
            global_reg = json.load(f)
        
        global_reg['total_agents_spawned'] += 1
        global_reg['active_agents'] += 1
        global_reg['agents'][agent_id] = {
            'task_id': task_id,
            'type': agent_type,
            'parent': parent,
            'started_at': datetime.now().isoformat(),
            'tmux_session': session_name
        }
        
        with open(global_reg_path, 'w') as f:
            json.dump(global_reg, f, indent=2)
        
        # Log successful deployment
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": "agent_deployed",
            "agent_id": agent_id,
            "tmux_session": session_name,
            "command": claude_command[:100] + "...",
            "success": True,
            "session_creation": session_result
        }
        
        with open(f"{workspace}/logs/deploy_{agent_id}.json", 'w') as f:
            json.dump(log_entry, f, indent=2)
        
        return {
            "success": True,
            "agent_id": agent_id,
            "tmux_session": session_name,
            "type": agent_type,
            "parent": parent,
            "task_id": task_id,
            "status": "deployed",
            "workspace": workspace,
            "deployment_method": "tmux session"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to deploy agent: {str(e)}"
        }

@mcp.tool
def get_real_task_status(task_id: str) -> Dict[str, Any]:
    """
    Get detailed status of a real task and its agents.
    
    Args:
        task_id: Task ID to query
    
    Returns:
        Complete task status
    """
    # Find the task workspace (may be in client or server location)
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
    
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    
    with open(registry_path, 'r') as f:
        registry = json.load(f)
    
    # Update agent statuses based on tmux sessions
    for agent in registry['agents']:
        if agent['status'] == 'running' and 'tmux_session' in agent:
            # Check if tmux session still exists
            if not check_tmux_session_exists(agent['tmux_session']):
                agent['status'] = 'completed'
                registry['active_count'] = max(0, registry['active_count'] - 1)
                registry['completed_count'] = registry.get('completed_count', 0) + 1
    
    # Save updated registry
    with open(registry_path, 'w') as f:
        json.dump(registry, f, indent=2)
    
    # Enhanced progress tracking - read JSONL files  
    progress_entries = []
    findings_entries = []
    
    # Read all progress JSONL files
    progress_dir = f"{workspace}/progress"
    if os.path.exists(progress_dir):
        for file in os.listdir(progress_dir):
            if file.endswith('_progress.jsonl'):
                try:
                    with open(f"{progress_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    progress = json.loads(line)
                                    progress_entries.append(progress)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Read all findings JSONL files
    findings_dir = f"{workspace}/findings"
    if os.path.exists(findings_dir):
        for file in os.listdir(findings_dir):
            if file.endswith('_findings.jsonl'):
                try:
                    with open(f"{findings_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    finding = json.loads(line)
                                    findings_entries.append(finding)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Sort by timestamp
    progress_entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    findings_entries.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    return {
        "success": True,
        "task_id": task_id,
        "description": registry.get('task_description'),
        "status": registry.get('status'),
        "workspace": workspace,
        "agents": {
            "total_spawned": registry.get('total_spawned', 0),
            "active": registry.get('active_count', 0),
            "completed": registry.get('completed_count', 0),
            "agents_list": registry.get('agents', [])
        },
        "hierarchy": registry.get('agent_hierarchy', {}),
        "enhanced_progress": {
            "recent_updates": progress_entries[:10],  # Last 10 progress updates
            "recent_findings": findings_entries[:5],   # Last 5 findings
            "total_progress_entries": len(progress_entries),
            "total_findings": len(findings_entries),
            "progress_frequency": len(progress_entries) / max((registry.get('total_spawned', 1) * 10), 1)  # Updates per agent per 10-min window
        },
        "spiral_status": registry.get('spiral_checks', {}),
        "limits": {
            "max_agents": registry.get('max_agents', 10),
            "max_concurrent": registry.get('max_concurrent', 5),
            "max_depth": registry.get('max_depth', 3)
        }
    }

@mcp.tool
def get_agent_output(task_id: str, agent_id: str) -> Dict[str, Any]:
    """
    Get the current output from a running agent's tmux session.
    
    Args:
        task_id: Task ID containing the agent
        agent_id: Agent ID to get output from
    
    Returns:
        Agent output
    """
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
    
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    
    with open(registry_path, 'r') as f:
        registry = json.load(f)
    
    # Find agent
    agent = None
    for a in registry['agents']:
        if a['id'] == agent_id:
            agent = a
            break
    
    if not agent:
        return {
            "success": False,
            "error": f"Agent {agent_id} not found"
        }
    
    if 'tmux_session' not in agent:
        return {
            "success": False,
            "error": f"Agent {agent_id} has no tmux session"
        }
    
    session_name = agent['tmux_session']
    
    if not check_tmux_session_exists(session_name):
        return {
            "success": True,
            "agent_id": agent_id,
            "session_status": "terminated",
            "output": "Agent session has terminated"
        }
    
    output = get_tmux_session_output(session_name)
    
    return {
        "success": True,
        "agent_id": agent_id,
        "tmux_session": session_name,
        "session_status": "running",
        "output": output
    }

@mcp.tool
def kill_real_agent(task_id: str, agent_id: str, reason: str = "Manual termination") -> Dict[str, Any]:
    """
    Terminate a real running agent by killing its tmux session.
    
    Args:
        task_id: Task containing the agent
        agent_id: Agent to terminate  
        reason: Reason for termination
    
    Returns:
        Termination status
    """
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
    
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    
    with open(registry_path, 'r') as f:
        registry = json.load(f)
    
    # Find agent
    agent = None
    for a in registry['agents']:
        if a['id'] == agent_id:
            agent = a
            break
    
    if not agent:
        return {
            "success": False,
            "error": f"Agent {agent_id} not found"
        }
    
    try:
        session_name = agent.get('tmux_session')
        killed = False
        
        if session_name and check_tmux_session_exists(session_name):
            killed = kill_tmux_session(session_name)
        
        # Update registry
        agent['status'] = 'terminated'
        agent['terminated_at'] = datetime.now().isoformat()
        agent['termination_reason'] = reason
        registry['active_count'] = max(0, registry['active_count'] - 1)
        
        with open(registry_path, 'w') as f:
            json.dump(registry, f, indent=2)
        
        return {
            "success": True,
            "agent_id": agent_id,
            "tmux_session": session_name,
            "session_killed": killed,
            "reason": reason,
            "status": "terminated"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to terminate agent: {str(e)}"
        }

def get_comprehensive_task_status(task_id: str) -> Dict[str, Any]:
    """
    Get comprehensive status including all agents' progress and findings.
    Internal helper function for coordination.
    """
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {"success": False, "error": f"Task {task_id} not found in any workspace location"}
    
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    
    with open(registry_path, 'r') as f:
        registry = json.load(f)
    
    # Read all progress entries
    all_progress = []
    progress_dir = f"{workspace}/progress"
    if os.path.exists(progress_dir):
        for file in os.listdir(progress_dir):
            if file.endswith('_progress.jsonl'):
                try:
                    with open(f"{progress_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    all_progress.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Read all findings
    all_findings = []
    findings_dir = f"{workspace}/findings"
    if os.path.exists(findings_dir):
        for file in os.listdir(findings_dir):
            if file.endswith('_findings.jsonl'):
                try:
                    with open(f"{findings_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    all_findings.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Sort by timestamp (most recent first)
    all_progress.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    all_findings.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    return {
        "success": True,
        "task_info": {
            "task_id": task_id,
            "description": registry.get('task_description'),
            "status": registry.get('status'),
            "workspace": workspace
        },
        "agents": {
            "total_spawned": registry.get('total_spawned', 0),
            "active": registry.get('active_count', 0),
            "completed": registry.get('completed_count', 0),
            "agents_list": registry.get('agents', [])
        },
        "coordination_data": {
            "recent_progress": all_progress[:20],  # Last 20 progress updates from all agents
            "recent_findings": all_findings[:10],  # Last 10 findings from all agents
            "agent_status_summary": {
                agent['id']: {
                    "type": agent.get('type'),
                    "status": agent.get('status'),
                    "progress": agent.get('progress', 0),
                    "last_update": agent.get('last_update')
                } for agent in registry.get('agents', [])
            }
        },
        "hierarchy": registry.get('agent_hierarchy', {})
    }

@mcp.tool
def update_agent_progress(task_id: str, agent_id: str, status: str, message: str, progress: int = 0) -> Dict[str, Any]:
    """
    Update agent progress - called by agents themselves to self-report.
    Returns comprehensive status of all agents for coordination.
    
    Args:
        task_id: Task ID
        agent_id: Agent ID reporting progress  
        status: Current status (working/blocked/completed/etc)
        message: Status message describing current work
        progress: Progress percentage (0-100)
    
    Returns:
        Update result with comprehensive task status for coordination
    """
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
    
    registry_path = f"{workspace}/AGENT_REGISTRY.json"
    
    # Log progress update
    progress_file = f"{workspace}/progress/{agent_id}_progress.jsonl"
    os.makedirs(f"{workspace}/progress", exist_ok=True)
    
    progress_entry = {
        "timestamp": datetime.now().isoformat(),
        "agent_id": agent_id,
        "status": status,
        "message": message,
        "progress": progress
    }
    
    with open(progress_file, 'a') as f:
        f.write(json.dumps(progress_entry) + '\n')
    
    # Update registry
    with open(registry_path, 'r') as f:
        registry = json.load(f)
    
    # Find and update agent
    for agent in registry['agents']:
        if agent['id'] == agent_id:
            agent['last_update'] = datetime.now().isoformat()
            agent['status'] = status
            agent['progress'] = progress
            break
    
    with open(registry_path, 'w') as f:
        json.dump(registry, f, indent=2)
    
    # Get comprehensive status for coordination
    comprehensive_status = get_comprehensive_task_status(task_id)
    
    # Return own update confirmation plus comprehensive coordination data
    return {
        "success": True,
        "own_update": {
            "agent_id": agent_id,
            "status": status,
            "progress": progress,
            "message": message,
            "timestamp": progress_entry["timestamp"]
        },
        "coordination_info": comprehensive_status if comprehensive_status["success"] else None
    }

@mcp.tool  
def report_agent_finding(task_id: str, agent_id: str, finding_type: str, severity: str, message: str, data: dict = None) -> Dict[str, Any]:
    """
    Report a finding/discovery - called by agents to share discoveries.
    Returns comprehensive status of all agents for coordination.
    
    Args:
        task_id: Task ID
        agent_id: Agent ID reporting finding
        finding_type: Type of finding (issue/solution/insight/etc)
        severity: Severity level (low/medium/high/critical)  
        message: Finding description
        data: Additional finding data
    
    Returns:
        Report result with comprehensive task status for coordination
    """
    if data is None:
        data = {}
    
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            "success": False,
            "error": f"Task {task_id} not found in any workspace location"
        }
        
    findings_file = f"{workspace}/findings/{agent_id}_findings.jsonl"
    os.makedirs(f"{workspace}/findings", exist_ok=True)
    
    finding_entry = {
        "timestamp": datetime.now().isoformat(),
        "agent_id": agent_id,
        "finding_type": finding_type,
        "severity": severity,
        "message": message,
        "data": data
    }
    
    with open(findings_file, 'a') as f:
        f.write(json.dumps(finding_entry) + '\n')
    
    # Get comprehensive status for coordination
    comprehensive_status = get_comprehensive_task_status(task_id)
    
    # Return own finding confirmation plus comprehensive coordination data
    return {
        "success": True,
        "own_finding": {
            "agent_id": agent_id,
            "finding_type": finding_type,
            "severity": severity,
            "message": message,
            "timestamp": finding_entry["timestamp"],
            "data": data
        },
        "coordination_info": comprehensive_status if comprehensive_status["success"] else None
    }

@mcp.tool
def spawn_child_agent(task_id: str, parent_agent_id: str, child_agent_type: str, child_prompt: str) -> Dict[str, Any]:
    """
    Spawn a child agent - called by agents to create sub-agents.
    
    Args:
        task_id: Parent task ID
        parent_agent_id: ID of parent agent spawning this child
        child_agent_type: Type of child agent
        child_prompt: Prompt for child agent
    
    Returns:
        Child agent spawn result  
    """
    # Delegate to existing deployment function
    return deploy_headless_agent(task_id, child_agent_type, child_prompt, parent_agent_id)

@mcp.resource("tasks://list")  
def list_real_tasks() -> str:
    """List all real tasks."""
    ensure_workspace()
    
    global_reg_path = f"{WORKSPACE_BASE}/registry/GLOBAL_REGISTRY.json"
    if not os.path.exists(global_reg_path):
        return json.dumps({"tasks": [], "message": "No tasks found"})
    
    with open(global_reg_path, 'r') as f:
        global_reg = json.load(f)
    
    return json.dumps(global_reg, indent=2)

@mcp.resource("task://{task_id}/status")
def get_task_resource(task_id: str) -> str:
    """Get task details as resource."""
    result = get_real_task_status(task_id)
    return json.dumps(result, indent=2)

@mcp.resource("task://{task_id}/progress-timeline")  
def get_task_progress_timeline(task_id: str) -> str:
    """Get comprehensive progress timeline for a task."""
    # Find the task workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return json.dumps({"error": f"Task {task_id} not found in any workspace location"}, indent=2)
    
    all_progress = []
    all_findings = []
    
    # Read all progress files
    progress_dir = f"{workspace}/progress"
    if os.path.exists(progress_dir):
        for file in os.listdir(progress_dir):
            if file.endswith('_progress.jsonl'):
                try:
                    with open(f"{progress_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    all_progress.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Read all findings files
    findings_dir = f"{workspace}/findings" 
    if os.path.exists(findings_dir):
        for file in os.listdir(findings_dir):
            if file.endswith('_findings.jsonl'):
                try:
                    with open(f"{findings_dir}/{file}", 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    entry = json.loads(line)
                                    all_findings.append(entry)
                                except json.JSONDecodeError:
                                    continue
                except:
                    continue
    
    # Sort by timestamp
    all_progress.sort(key=lambda x: x.get('timestamp', ''))
    all_findings.sort(key=lambda x: x.get('timestamp', ''))
    
    # Create combined timeline
    timeline = []
    for progress in all_progress:
        timeline.append({**progress, "entry_type": "progress"})
    for finding in all_findings:
        timeline.append({**finding, "entry_type": "finding"})
    
    timeline.sort(key=lambda x: x.get('timestamp', ''))
    
    return json.dumps({
        "task_id": task_id,
        "timeline": timeline,
        "summary": {
            "total_progress_entries": len(all_progress),
            "total_findings": len(all_findings),
            "timeline_span": {
                "start": timeline[0]["timestamp"] if timeline else None,
                "end": timeline[-1]["timestamp"] if timeline else None
            },
            "agents_active": len(set(entry.get("agent_id") for entry in timeline if entry.get("agent_id")))
        }
    }, indent=2)

if __name__ == "__main__":
    mcp.run()