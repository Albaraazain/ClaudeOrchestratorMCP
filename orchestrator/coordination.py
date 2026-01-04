"""
Enhanced coordination response module for LLM agents.

This module provides structured coordination information that helps agents:
1. Understand what peers are working on (avoid duplication)
2. See recent discoveries from other agents (build on findings)
3. Detect conflicts or overlapping work areas
4. Get recommendations on where to focus next

Design Principles:
- LLM-friendly text formatting with clear headers
- Context-aware recommendations based on agent type
- Compact but informative (target <8KB for context window efficiency)
- Structured for easy parsing while remaining human-readable
"""

from typing import Dict, List, Any, Optional, TypedDict
from datetime import datetime
import json
import os
from dataclasses import dataclass, asdict


class AgentStatus(TypedDict):
    """Status of a single agent for coordination."""
    agent_id: str
    agent_type: str
    status: str  # working, blocked, completed, error, failed
    progress: int  # 0-100
    current_focus: str  # What they're working on
    last_update_ago: str  # "2 min ago", "15 sec ago" etc
    location: Optional[str]  # File/module they're working on


class PeerFinding(TypedDict):
    """A finding from a peer agent."""
    agent_id: str
    agent_type: str
    finding_type: str  # issue, solution, insight, recommendation
    severity: str  # low, medium, high, critical
    message: str
    timestamp_ago: str  # "5 min ago"
    relevance_score: float  # 0-1, how relevant to current agent


class WorkArea(TypedDict):
    """Work area being covered by agents."""
    area: str  # e.g., "authentication", "database", "UI components"
    agents_working: List[str]
    coverage_level: str  # none, partial, full, overlapping


class CoordinationRecommendation(TypedDict):
    """Specific recommendation for the requesting agent."""
    priority: str  # high, medium, low
    action: str  # focus_on, avoid, coordinate_with, wait_for
    target: str  # What to focus on/avoid
    reason: str  # Why this recommendation


@dataclass
class CoordinationResponse:
    """
    Complete coordination response for an agent.
    Designed to be rendered as structured text for LLM consumption.
    """

    # Metadata
    task_id: str
    requesting_agent: str
    timestamp: str

    # Core coordination data
    agent_summary: Dict[str, int]  # active, completed, blocked counts
    active_agents: List[AgentStatus]
    recent_findings: List[PeerFinding]  # Last 10, relevance-sorted
    work_coverage: List[WorkArea]

    # Conflict detection
    potential_conflicts: List[Dict[str, Any]]
    duplicate_work_detected: bool

    # Recommendations
    recommendations: List[CoordinationRecommendation]
    suggested_focus_areas: List[str]
    areas_to_avoid: List[str]

    # Optional fields with defaults
    response_version: str = "2.0"

    def format_text_response(self, detail_level: str = "standard") -> str:
        """
        Format coordination data as LLM-friendly text.

        Args:
            detail_level: "minimal", "standard", or "full"

        Returns:
            Formatted text response optimized for LLM parsing
        """
        lines = []

        # Header
        lines.append("=" * 60)
        lines.append("PEER COORDINATION UPDATE")
        lines.append("=" * 60)
        lines.append(f"Task: {self.task_id}")
        lines.append(f"Your ID: {self.requesting_agent}")
        lines.append(f"Generated: {self.timestamp}")
        lines.append("")

        # Agent Status Summary
        lines.append("## AGENT STATUS SUMMARY")
        lines.append(f"Total Active: {self.agent_summary.get('active', 0)}")
        lines.append(f"Completed: {self.agent_summary.get('completed', 0)}")
        lines.append(f"Blocked: {self.agent_summary.get('blocked', 0)}")
        lines.append("")

        # Active Agents Detail
        if self.active_agents and detail_level != "minimal":
            lines.append("## ACTIVE AGENTS")
            for agent in self.active_agents:
                status_icon = self._get_status_icon(agent['status'])
                lines.append(f"{status_icon} [{agent['agent_id']}] ({agent['agent_type']})")
                lines.append(f"   Status: {agent['status']} | Progress: {agent['progress']}%")
                lines.append(f"   Working on: {agent['current_focus']}")
                lines.append(f"   Last update: {agent['last_update_ago']}")
                if agent.get('location'):
                    lines.append(f"   Location: {agent['location']}")
                lines.append("")

        # Recent Findings (prioritized by relevance and severity)
        if self.recent_findings:
            lines.append("## RECENT PEER FINDINGS")

            # Group by severity for better visibility
            critical_findings = [f for f in self.recent_findings if f['severity'] == 'critical']
            high_findings = [f for f in self.recent_findings if f['severity'] == 'high']
            other_findings = [f for f in self.recent_findings if f['severity'] not in ['critical', 'high']]

            for finding_group, group_name in [(critical_findings, "CRITICAL"),
                                              (high_findings, "HIGH PRIORITY"),
                                              (other_findings, "OTHER")]:
                if finding_group:
                    if group_name != "OTHER" or detail_level == "full":
                        lines.append(f"  ### {group_name}:")
                        for finding in finding_group[:5 if detail_level == "standard" else 10]:
                            icon = self._get_finding_icon(finding['finding_type'])
                            lines.append(f"  {icon} [{finding['agent_id']}] {finding['timestamp_ago']}")
                            lines.append(f"     {finding['message'][:200]}")
                            if finding.get('relevance_score', 0) > 0.7:
                                lines.append(f"     ⚠️ HIGHLY RELEVANT TO YOUR WORK")
                        lines.append("")

        # Conflict Detection
        if self.potential_conflicts or self.duplicate_work_detected:
            lines.append("## ⚠️ CONFLICT DETECTION")
            if self.duplicate_work_detected:
                lines.append("DUPLICATE WORK DETECTED - Coordinate with peers!")
            for conflict in self.potential_conflicts:
                lines.append(f"- {conflict.get('description', 'Potential conflict detected')}")
                if conflict.get('agents_involved'):
                    lines.append(f"  Agents involved: {', '.join(conflict['agents_involved'])}")
            lines.append("")

        # Work Coverage Analysis
        if detail_level != "minimal" and self.work_coverage:
            lines.append("## WORK COVERAGE ANALYSIS")
            for area in self.work_coverage:
                coverage_icon = self._get_coverage_icon(area['coverage_level'])
                lines.append(f"{coverage_icon} {area['area']}")
                if area['agents_working']:
                    lines.append(f"   Agents: {', '.join(area['agents_working'])}")
                lines.append(f"   Coverage: {area['coverage_level']}")
            lines.append("")

        # Recommendations (always include)
        lines.append("## 🎯 RECOMMENDATIONS FOR YOU")
        if self.recommendations:
            for rec in self.recommendations[:3]:  # Top 3 recommendations
                priority_icon = "🔴" if rec['priority'] == "high" else "🟡" if rec['priority'] == "medium" else "🟢"
                lines.append(f"{priority_icon} {rec['action'].upper()}: {rec['target']}")
                lines.append(f"   Reason: {rec['reason']}")
        else:
            lines.append("Continue with your current approach - no conflicts detected")
        lines.append("")

        # Focus Areas
        if self.suggested_focus_areas:
            lines.append("## SUGGESTED FOCUS AREAS")
            for area in self.suggested_focus_areas[:5]:
                lines.append(f"✓ {area}")
            lines.append("")

        if self.areas_to_avoid:
            lines.append("## AREAS TO AVOID (Already Covered)")
            for area in self.areas_to_avoid[:5]:
                lines.append(f"✗ {area}")
            lines.append("")

        # Footer with quick stats
        lines.append("-" * 60)
        total_size = len("\n".join(lines))
        lines.append(f"Response size: {total_size} bytes | Detail level: {detail_level}")

        return "\n".join(lines)

    def _get_status_icon(self, status: str) -> str:
        """Get status icon for better visibility."""
        icons = {
            "working": "🔄",
            "blocked": "🚫",
            "completed": "✅",
            "error": "❌",
            "failed": "💀"
        }
        return icons.get(status, "•")

    def _get_finding_icon(self, finding_type: str) -> str:
        """Get finding type icon."""
        icons = {
            "issue": "🐛",
            "solution": "💡",
            "insight": "🔍",
            "recommendation": "💭"
        }
        return icons.get(finding_type, "•")

    def _get_coverage_icon(self, coverage_level: str) -> str:
        """Get coverage level icon."""
        icons = {
            "none": "⚪",
            "partial": "🟡",
            "full": "🟢",
            "overlapping": "🔴"
        }
        return icons.get(coverage_level, "•")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


def calculate_time_ago(timestamp: str) -> str:
    """
    Calculate human-readable time difference.

    Args:
        timestamp: ISO format timestamp

    Returns:
        Human-readable time like "2 min ago", "15 sec ago"
    """
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        diff = datetime.now() - dt.replace(tzinfo=None)
        seconds = int(diff.total_seconds())

        if seconds < 60:
            return f"{seconds} sec ago"
        elif seconds < 3600:
            return f"{seconds // 60} min ago"
        elif seconds < 86400:
            return f"{seconds // 3600} hours ago"
        else:
            return f"{seconds // 86400} days ago"
    except:
        return "unknown time"


def calculate_relevance_score(
    finding: Dict[str, Any],
    requesting_agent_type: str,
    requesting_agent_focus: Optional[str] = None
) -> float:
    """
    Calculate how relevant a finding is to the requesting agent.

    Args:
        finding: The finding to evaluate
        requesting_agent_type: Type of agent requesting coordination
        requesting_agent_focus: What the agent is working on

    Returns:
        Relevance score between 0 and 1
    """
    score = 0.5  # Base relevance

    # Critical findings are always relevant
    if finding.get('severity') == 'critical':
        score += 0.3
    elif finding.get('severity') == 'high':
        score += 0.2

    # Type-based relevance
    finding_type = finding.get('finding_type', '')
    agent_type = requesting_agent_type.lower()

    if agent_type == 'fixer' and finding_type == 'issue':
        score += 0.2
    elif agent_type == 'investigator' and finding_type == 'insight':
        score += 0.2
    elif agent_type == 'builder' and finding_type == 'solution':
        score += 0.2

    # Focus area matching (if provided)
    if requesting_agent_focus and finding.get('message'):
        message_lower = finding['message'].lower()
        focus_lower = requesting_agent_focus.lower()

        # Simple keyword matching
        focus_keywords = focus_lower.split()
        matches = sum(1 for kw in focus_keywords if kw in message_lower)
        if matches > 0:
            score += min(0.3, matches * 0.1)

    return min(1.0, score)


def detect_work_conflicts(
    agents: List[Dict[str, Any]],
    requesting_agent_id: str
) -> tuple[List[Dict[str, Any]], bool]:
    """
    Detect potential conflicts or duplicate work.

    Args:
        agents: List of active agents
        requesting_agent_id: ID of agent requesting coordination

    Returns:
        Tuple of (conflicts list, duplicate_work_detected flag)
    """
    conflicts = []
    duplicate_detected = False

    # Find requesting agent
    requesting = None
    for agent in agents:
        if agent.get('id') == requesting_agent_id:
            requesting = agent
            break

    if not requesting:
        return conflicts, duplicate_detected

    requesting_focus = requesting.get('current_focus', '').lower()
    requesting_type = requesting.get('type', '')

    # Check other agents
    for agent in agents:
        if agent.get('id') == requesting_agent_id:
            continue

        other_focus = agent.get('current_focus', '').lower()
        other_type = agent.get('type', '')

        # Same type working on similar area
        if requesting_type == other_type and requesting_focus and other_focus:
            # Simple overlap detection
            focus_words = set(requesting_focus.split())
            other_words = set(other_focus.split())
            overlap = focus_words & other_words

            if len(overlap) >= 2:  # At least 2 common words
                conflicts.append({
                    'description': f"Potential duplicate work with {agent.get('id')}",
                    'agents_involved': [requesting_agent_id, agent.get('id')],
                    'area': ' '.join(overlap),
                    'severity': 'high' if requesting_type == other_type else 'medium'
                })
                duplicate_detected = True

    return conflicts, duplicate_detected


def generate_recommendations(
    agent_type: str,
    agent_status: str,
    conflicts: List[Dict[str, Any]],
    work_coverage: List[WorkArea],
    findings: List[PeerFinding]
) -> List[CoordinationRecommendation]:
    """
    Generate smart recommendations for the agent.

    Args:
        agent_type: Type of requesting agent
        agent_status: Current status of agent
        conflicts: Detected conflicts
        work_coverage: Work area coverage analysis
        findings: Recent peer findings

    Returns:
        List of recommendations
    """
    recommendations = []

    # Handle conflicts first
    if conflicts:
        for conflict in conflicts[:2]:  # Top 2 conflicts
            recommendations.append(CoordinationRecommendation(
                priority='high',
                action='coordinate_with',
                target=conflict['agents_involved'][1] if len(conflict['agents_involved']) > 1 else 'peer agents',
                reason=conflict['description']
            ))

    # Find gaps in coverage
    uncovered_areas = [area for area in work_coverage if area['coverage_level'] == 'none']
    if uncovered_areas and agent_status == 'working':
        recommendations.append(CoordinationRecommendation(
            priority='medium',
            action='focus_on',
            target=uncovered_areas[0]['area'],
            reason='This area has no coverage yet'
        ))

    # Type-specific recommendations
    if agent_type == 'fixer':
        # Look for critical issues
        critical_issues = [f for f in findings if f['finding_type'] == 'issue' and f['severity'] == 'critical']
        if critical_issues:
            recommendations.append(CoordinationRecommendation(
                priority='high',
                action='focus_on',
                target=f"Critical issue from {critical_issues[0]['agent_id']}",
                reason=critical_issues[0]['message'][:100]
            ))

    elif agent_type == 'investigator':
        # Check for areas needing investigation
        partial_areas = [area for area in work_coverage if area['coverage_level'] == 'partial']
        if partial_areas:
            recommendations.append(CoordinationRecommendation(
                priority='medium',
                action='focus_on',
                target=f"Deeper investigation of {partial_areas[0]['area']}",
                reason='Area only partially covered'
            ))

    # Avoid overlapping work
    overlapping_areas = [area for area in work_coverage if area['coverage_level'] == 'overlapping']
    for area in overlapping_areas[:2]:
        recommendations.append(CoordinationRecommendation(
            priority='low',
            action='avoid',
            target=area['area'],
            reason=f"Already covered by {len(area['agents_working'])} agents"
        ))

    return recommendations


def build_coordination_response(
    task_id: str,
    requesting_agent_id: str,
    registry: Dict[str, Any],
    findings: List[Dict[str, Any]],
    progress_entries: List[Dict[str, Any]]
) -> CoordinationResponse:
    """
    Build a complete coordination response from raw data.

    Args:
        task_id: Task ID
        requesting_agent_id: ID of agent requesting coordination
        registry: Task registry data
        findings: All findings from agents
        progress_entries: All progress updates

    Returns:
        Complete CoordinationResponse object
    """
    # Extract requesting agent info
    requesting_agent = None
    requesting_type = 'unknown'
    for agent in registry.get('agents', []):
        if agent['id'] == requesting_agent_id:
            requesting_agent = agent
            requesting_type = agent.get('type', 'unknown')
            break

    # Build agent status list
    active_agents = []
    agent_summary = {'active': 0, 'completed': 0, 'blocked': 0}

    for agent in registry.get('agents', []):
        status = agent.get('status', 'unknown')

        # Count by status
        if status in ['working', 'running']:
            agent_summary['active'] += 1
        elif status == 'completed':
            agent_summary['completed'] += 1
        elif status == 'blocked':
            agent_summary['blocked'] += 1

        # Add to active list if not completed
        if status != 'completed' and agent['id'] != requesting_agent_id:
            # Find latest progress for this agent
            agent_progress = [p for p in progress_entries if p.get('agent_id') == agent['id']]
            latest_progress = agent_progress[-1] if agent_progress else {}

            active_agents.append(AgentStatus(
                agent_id=agent['id'],
                agent_type=agent.get('type', 'unknown'),
                status=status,
                progress=latest_progress.get('progress', 0),
                current_focus=latest_progress.get('message', 'Unknown focus'),
                last_update_ago=calculate_time_ago(latest_progress.get('timestamp', '')),
                location=None  # Could be enhanced with file tracking
            ))

    # Process findings with relevance scoring
    peer_findings = []
    for finding in findings[-20:]:  # Last 20 findings
        if finding.get('agent_id') != requesting_agent_id:  # Exclude own findings
            relevance = calculate_relevance_score(
                finding,
                requesting_type,
                requesting_agent.get('current_focus') if requesting_agent else None
            )

            peer_findings.append(PeerFinding(
                agent_id=finding['agent_id'],
                agent_type=finding.get('agent_type', 'unknown'),
                finding_type=finding['finding_type'],
                severity=finding['severity'],
                message=finding['message'],
                timestamp_ago=calculate_time_ago(finding.get('timestamp', '')),
                relevance_score=relevance
            ))

    # Sort by relevance and severity
    peer_findings.sort(key=lambda x: (x['relevance_score'],
                                      {'critical': 4, 'high': 3, 'medium': 2, 'low': 1}.get(x['severity'], 0)),
                      reverse=True)

    # Analyze work coverage
    work_areas = {}
    for agent in registry.get('agents', []):
        if agent.get('status') in ['working', 'running']:
            # Extract work area from agent focus or type
            focus = agent.get('current_focus', '').lower()
            area = agent.get('type', 'general')

            # Simple area extraction (could be enhanced)
            if 'auth' in focus:
                area = 'authentication'
            elif 'database' in focus or 'db' in focus:
                area = 'database'
            elif 'api' in focus:
                area = 'api'
            elif 'ui' in focus or 'frontend' in focus:
                area = 'ui'
            elif 'test' in focus:
                area = 'testing'

            if area not in work_areas:
                work_areas[area] = []
            work_areas[area].append(agent['id'])

    work_coverage = []
    for area, agents in work_areas.items():
        coverage = 'none'
        if len(agents) == 0:
            coverage = 'none'
        elif len(agents) == 1:
            coverage = 'partial'
        elif len(agents) == 2:
            coverage = 'full'
        else:
            coverage = 'overlapping'

        work_coverage.append(WorkArea(
            area=area,
            agents_working=agents,
            coverage_level=coverage
        ))

    # Detect conflicts
    conflicts, duplicate_work = detect_work_conflicts(
        registry.get('agents', []),
        requesting_agent_id
    )

    # Generate recommendations
    recommendations = generate_recommendations(
        requesting_type,
        requesting_agent.get('status', 'working') if requesting_agent else 'working',
        conflicts,
        work_coverage,
        peer_findings[:10]  # Use top 10 findings
    )

    # Build suggested focus areas and areas to avoid
    suggested_areas = []
    avoid_areas = []

    for area in work_coverage:
        if area['coverage_level'] == 'none':
            suggested_areas.append(area['area'])
        elif area['coverage_level'] == 'overlapping':
            avoid_areas.append(f"{area['area']} (covered by {len(area['agents_working'])} agents)")

    # Create response
    return CoordinationResponse(
        task_id=task_id,
        requesting_agent=requesting_agent_id,
        timestamp=datetime.now().isoformat(),
        agent_summary=agent_summary,
        active_agents=active_agents,
        recent_findings=peer_findings[:10],  # Top 10 most relevant
        work_coverage=work_coverage,
        potential_conflicts=conflicts,
        duplicate_work_detected=duplicate_work,
        recommendations=recommendations,
        suggested_focus_areas=suggested_areas,
        areas_to_avoid=avoid_areas
    )


# Example usage and testing
if __name__ == "__main__":
    # Test data
    test_registry = {
        'agents': [
            {'id': 'agent1', 'type': 'investigator', 'status': 'working', 'current_focus': 'analyzing authentication flow'},
            {'id': 'agent2', 'type': 'fixer', 'status': 'working', 'current_focus': 'fixing database connection issues'},
            {'id': 'agent3', 'type': 'builder', 'status': 'completed', 'current_focus': 'built API endpoints'},
        ]
    }

    test_findings = [
        {
            'agent_id': 'agent2',
            'finding_type': 'issue',
            'severity': 'critical',
            'message': 'Found SQL injection vulnerability in login endpoint',
            'timestamp': datetime.now().isoformat()
        },
        {
            'agent_id': 'agent3',
            'finding_type': 'solution',
            'severity': 'high',
            'message': 'Implemented rate limiting on all API endpoints',
            'timestamp': datetime.now().isoformat()
        }
    ]

    test_progress = [
        {
            'agent_id': 'agent1',
            'status': 'working',
            'progress': 60,
            'message': 'Analyzing authentication flow patterns',
            'timestamp': datetime.now().isoformat()
        }
    ]

    # Build response
    response = build_coordination_response(
        task_id='TASK-TEST-123',
        requesting_agent_id='agent1',
        registry=test_registry,
        findings=test_findings,
        progress_entries=test_progress
    )

    # Test different detail levels
    print("MINIMAL DETAIL LEVEL:")
    print(response.format_text_response('minimal'))
    print("\n" + "="*60 + "\n")

    print("STANDARD DETAIL LEVEL:")
    print(response.format_text_response('standard'))
    print("\n" + "="*60 + "\n")

    print("FULL DETAIL LEVEL:")
    print(response.format_text_response('full'))