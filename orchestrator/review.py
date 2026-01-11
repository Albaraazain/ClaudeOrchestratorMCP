"""
Review Agent Schema and State Machine Module for Claude Orchestrator.

This module defines the schema and data structures for the agentic review system.
Review agents are spawned to verify phase work before transitions are approved.

Key components:
- ReviewStatus: Enum for review lifecycle states (PENDING, IN_PROGRESS, COMPLETED)
- ReviewVerdict: Enum for review outcomes (APPROVED, REJECTED, NEEDS_REVISION)
- ReviewFinding: Dataclass for individual review findings
- ReviewAgent: Dataclass for review agent state
- ReviewConfig: Dataclass for review configuration

State Machine Flow:
    Phase AWAITING_REVIEW -> spawn review agent -> UNDER_REVIEW
    Review agent completes -> verdict determines next state:
        APPROVED -> phase APPROVED -> advance to next phase
        REJECTED -> phase REJECTED -> REVISING
        NEEDS_REVISION -> phase REVISING (minor fixes needed)

Author: Claude Code Orchestrator Project
License: MIT
"""

import uuid
import logging
from enum import Enum
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Any, Optional, TypedDict

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

# Valid review verdicts as frozenset for validation
REVIEW_VERDICTS = frozenset({'approved', 'rejected', 'needs_revision'})

# Valid finding types as frozenset for validation
REVIEW_FINDING_TYPES = frozenset({'issue', 'suggestion', 'blocker', 'praise'})

# Valid finding severities
REVIEW_FINDING_SEVERITIES = frozenset({'critical', 'high', 'medium', 'low'})

# Default review configuration values
DEFAULT_MIN_REVIEWERS = 1
DEFAULT_REQUIRE_UNANIMOUS = False
DEFAULT_AUTO_APPROVE_THRESHOLD = 0.0  # Disabled by default
DEFAULT_TIMEOUT_SECONDS = 900  # 15 minutes (increased from 5 min for complex reviews)


# ============================================================================
# ENUMS
# ============================================================================

class ReviewStatus(str, Enum):
    """
    Review status enum defining the lifecycle states of a review.

    States:
        PENDING: Review has been requested but not yet started
        IN_PROGRESS: Review agent is actively reviewing the phase work
        COMPLETED: Review has finished (check verdict for outcome)

    Usage:
        >>> status = ReviewStatus.PENDING
        >>> status.value
        'pending'
    """
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class ReviewVerdict(str, Enum):
    """
    Review verdict enum defining possible outcomes of a review.

    Verdicts:
        APPROVED: Phase work meets quality standards, can advance to next phase
        REJECTED: Phase work has critical issues, requires significant rework
        NEEDS_REVISION: Minor issues found, needs fixes before approval

    State Transitions:
        APPROVED -> phase transitions to APPROVED, then next phase activates
        REJECTED -> phase transitions to REJECTED, then REVISING
        NEEDS_REVISION -> phase transitions directly to REVISING

    Usage:
        >>> verdict = ReviewVerdict.APPROVED
        >>> verdict.value
        'approved'
    """
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVISION = "needs_revision"


# ============================================================================
# TYPED DICTS FOR JSON SERIALIZATION
# ============================================================================

class ReviewFindingDict(TypedDict, total=False):
    """
    TypedDict for JSON-serializable review finding.

    Used for API responses and registry storage.
    """
    finding_type: str  # 'issue', 'suggestion', 'blocker', 'praise'
    severity: str  # 'critical', 'high', 'medium', 'low'
    message: str
    file_path: Optional[str]
    line_number: Optional[int]
    suggested_fix: Optional[str]


class ReviewAgentDict(TypedDict, total=False):
    """
    TypedDict for JSON-serializable review agent.

    Used for API responses and registry storage.
    """
    review_id: str
    phase_id: str
    agent_id: str
    status: str
    verdict: Optional[str]
    findings: List[ReviewFindingDict]
    created_at: str
    completed_at: Optional[str]


class ReviewConfigDict(TypedDict, total=False):
    """
    TypedDict for JSON-serializable review configuration.

    Used for API responses and registry storage.
    """
    min_reviewers: int
    require_unanimous: bool
    auto_approve_threshold: float
    timeout_seconds: int


# ============================================================================
# DATACLASSES
# ============================================================================

@dataclass
class ReviewFinding:
    """
    Individual finding from a review agent.

    Represents a single observation, issue, or suggestion discovered
    during the review process. Findings can be positive (praise) or
    negative (issue, blocker).

    Attributes:
        finding_type: Type of finding - 'issue', 'suggestion', 'blocker', 'praise'
        severity: Impact level - 'critical', 'high', 'medium', 'low'
        message: Description of the finding
        file_path: Optional path to the file containing the issue
        line_number: Optional line number where issue was found
        suggested_fix: Optional suggested fix or improvement

    Example:
        >>> finding = ReviewFinding(
        ...     finding_type='issue',
        ...     severity='high',
        ...     message='Race condition in registry update',
        ...     file_path='orchestrator/registry.py',
        ...     line_number=245,
        ...     suggested_fix='Use LockedRegistryFile for atomic updates'
        ... )
    """
    finding_type: str
    severity: str
    message: str
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    suggested_fix: Optional[str] = None

    def __post_init__(self):
        """Validate finding_type and severity values."""
        if self.finding_type not in REVIEW_FINDING_TYPES:
            logger.warning(
                f"Invalid finding_type '{self.finding_type}'. "
                f"Expected one of: {REVIEW_FINDING_TYPES}"
            )

        if self.severity not in REVIEW_FINDING_SEVERITIES:
            logger.warning(
                f"Invalid severity '{self.severity}'. "
                f"Expected one of: {REVIEW_FINDING_SEVERITIES}"
            )

    def to_dict(self) -> ReviewFindingDict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReviewFinding':
        """Create ReviewFinding from dictionary."""
        return cls(
            finding_type=data.get('finding_type', 'issue'),
            severity=data.get('severity', 'medium'),
            message=data.get('message', ''),
            file_path=data.get('file_path'),
            line_number=data.get('line_number'),
            suggested_fix=data.get('suggested_fix')
        )

    def is_blocker(self) -> bool:
        """Check if this finding is a blocker (prevents approval)."""
        return (
            self.finding_type == 'blocker' or
            (self.finding_type == 'issue' and self.severity == 'critical')
        )


@dataclass
class ReviewAgent:
    """
    Review agent state tracking.

    Represents an agent that has been spawned to review a phase's work.
    Tracks the review lifecycle from pending through completion.

    Attributes:
        review_id: Unique identifier for this review (auto-generated)
        phase_id: ID of the phase being reviewed
        agent_id: ID of the agent performing the review
        status: Current review status (PENDING, IN_PROGRESS, COMPLETED)
        verdict: Final verdict (only set when status is COMPLETED)
        findings: List of findings discovered during review
        created_at: ISO timestamp when review was requested
        completed_at: ISO timestamp when review completed (None if ongoing)

    Example:
        >>> review = ReviewAgent(
        ...     phase_id='phase-abc123',
        ...     agent_id='review-agent-xyz789',
        ...     status=ReviewStatus.IN_PROGRESS.value,
        ... )
        >>> review.add_finding(ReviewFinding(
        ...     finding_type='issue',
        ...     severity='medium',
        ...     message='Missing error handling'
        ... ))
    """
    review_id: str = field(default_factory=lambda: f"review-{uuid.uuid4().hex[:12]}")
    phase_id: str = ""
    agent_id: str = ""
    status: str = field(default=ReviewStatus.PENDING.value)
    verdict: Optional[str] = None
    findings: List[ReviewFinding] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None

    def __post_init__(self):
        """Validate status and verdict values."""
        # Validate status
        valid_statuses = {s.value for s in ReviewStatus}
        if self.status not in valid_statuses:
            logger.warning(
                f"Invalid review status '{self.status}'. "
                f"Expected one of: {valid_statuses}"
            )

        # Validate verdict if provided
        if self.verdict is not None:
            valid_verdicts = {v.value for v in ReviewVerdict}
            if self.verdict not in valid_verdicts:
                logger.warning(
                    f"Invalid review verdict '{self.verdict}'. "
                    f"Expected one of: {valid_verdicts}"
                )

    def to_dict(self) -> ReviewAgentDict:
        """Convert to dictionary for JSON serialization."""
        return {
            'review_id': self.review_id,
            'phase_id': self.phase_id,
            'agent_id': self.agent_id,
            'status': self.status,
            'verdict': self.verdict,
            'findings': [f.to_dict() for f in self.findings],
            'created_at': self.created_at,
            'completed_at': self.completed_at
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReviewAgent':
        """Create ReviewAgent from dictionary."""
        findings = []
        for finding_data in data.get('findings', []):
            if isinstance(finding_data, dict):
                findings.append(ReviewFinding.from_dict(finding_data))
            elif isinstance(finding_data, ReviewFinding):
                findings.append(finding_data)

        return cls(
            review_id=data.get('review_id', f"review-{uuid.uuid4().hex[:12]}"),
            phase_id=data.get('phase_id', ''),
            agent_id=data.get('agent_id', ''),
            status=data.get('status', ReviewStatus.PENDING.value),
            verdict=data.get('verdict'),
            findings=findings,
            created_at=data.get('created_at', datetime.now().isoformat()),
            completed_at=data.get('completed_at')
        )

    def add_finding(self, finding: ReviewFinding) -> None:
        """Add a finding to this review."""
        self.findings.append(finding)
        logger.debug(
            f"Added {finding.finding_type} finding to review {self.review_id}: "
            f"{finding.message[:50]}..."
        )

    def start_review(self) -> None:
        """Transition review from PENDING to IN_PROGRESS."""
        if self.status != ReviewStatus.PENDING.value:
            logger.warning(
                f"Cannot start review {self.review_id}: "
                f"status is {self.status}, expected {ReviewStatus.PENDING.value}"
            )
            return

        self.status = ReviewStatus.IN_PROGRESS.value
        logger.info(f"Review {self.review_id} started for phase {self.phase_id}")

    def complete_review(self, verdict: ReviewVerdict) -> None:
        """
        Complete the review with a verdict.

        Args:
            verdict: The review verdict (APPROVED, REJECTED, NEEDS_REVISION)
        """
        if self.status == ReviewStatus.COMPLETED.value:
            logger.warning(f"Review {self.review_id} is already completed")
            return

        self.status = ReviewStatus.COMPLETED.value
        self.verdict = verdict.value
        self.completed_at = datetime.now().isoformat()

        logger.info(
            f"Review {self.review_id} completed for phase {self.phase_id}: "
            f"verdict={verdict.value}, findings={len(self.findings)}"
        )

    def has_blockers(self) -> bool:
        """Check if any findings are blockers."""
        return any(f.is_blocker() for f in self.findings)

    def get_blocking_findings(self) -> List[ReviewFinding]:
        """Get all findings that are blockers."""
        return [f for f in self.findings if f.is_blocker()]

    def get_findings_by_severity(self, severity: str) -> List[ReviewFinding]:
        """Get findings filtered by severity."""
        return [f for f in self.findings if f.severity == severity]

    def get_findings_summary(self) -> Dict[str, int]:
        """Get a summary count of findings by type."""
        summary = {}
        for finding in self.findings:
            ftype = finding.finding_type
            summary[ftype] = summary.get(ftype, 0) + 1
        return summary


@dataclass
class ReviewConfig:
    """
    Configuration for the review process.

    Defines how reviews are conducted and what criteria must be met
    for a phase to be approved.

    Attributes:
        min_reviewers: Minimum number of review agents required (default: 1)
        require_unanimous: Whether all reviewers must approve (default: False)
        auto_approve_threshold: Percentage of approvals needed for auto-approve
                               (0.0-1.0, 0.0 means disabled, default: 0.0)
        timeout_seconds: Maximum time allowed for review (default: 300s/5min)

    Example:
        >>> config = ReviewConfig(
        ...     min_reviewers=2,
        ...     require_unanimous=True,
        ...     timeout_seconds=600
        ... )
    """
    min_reviewers: int = DEFAULT_MIN_REVIEWERS
    require_unanimous: bool = DEFAULT_REQUIRE_UNANIMOUS
    auto_approve_threshold: float = DEFAULT_AUTO_APPROVE_THRESHOLD
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def __post_init__(self):
        """Validate configuration values."""
        if self.min_reviewers < 1:
            logger.warning(
                f"min_reviewers must be at least 1, got {self.min_reviewers}. "
                "Setting to 1."
            )
            self.min_reviewers = 1

        if not (0.0 <= self.auto_approve_threshold <= 1.0):
            logger.warning(
                f"auto_approve_threshold must be between 0.0 and 1.0, "
                f"got {self.auto_approve_threshold}. Clamping to valid range."
            )
            self.auto_approve_threshold = max(0.0, min(1.0, self.auto_approve_threshold))

        if self.timeout_seconds < 0:
            logger.warning(
                f"timeout_seconds must be non-negative, got {self.timeout_seconds}. "
                "Setting to default."
            )
            self.timeout_seconds = DEFAULT_TIMEOUT_SECONDS

    def to_dict(self) -> ReviewConfigDict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ReviewConfig':
        """Create ReviewConfig from dictionary."""
        return cls(
            min_reviewers=data.get('min_reviewers', DEFAULT_MIN_REVIEWERS),
            require_unanimous=data.get('require_unanimous', DEFAULT_REQUIRE_UNANIMOUS),
            auto_approve_threshold=data.get('auto_approve_threshold', DEFAULT_AUTO_APPROVE_THRESHOLD),
            timeout_seconds=data.get('timeout_seconds', DEFAULT_TIMEOUT_SECONDS)
        )

    def should_auto_approve(self, approval_count: int, total_reviewers: int) -> bool:
        """
        Check if auto-approval threshold is met.

        Args:
            approval_count: Number of reviewers who approved
            total_reviewers: Total number of reviewers

        Returns:
            True if auto-approval threshold is met (and enabled)
        """
        if self.auto_approve_threshold <= 0.0:
            return False  # Auto-approve disabled

        if total_reviewers == 0:
            return False

        approval_ratio = approval_count / total_reviewers
        return approval_ratio >= self.auto_approve_threshold


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_review_agent(
    phase_id: str,
    agent_id: str
) -> ReviewAgent:
    """
    Create a new review agent for a phase.

    Factory function to create a ReviewAgent with proper defaults.

    Args:
        phase_id: ID of the phase to review
        agent_id: ID of the agent performing the review

    Returns:
        New ReviewAgent instance in PENDING status

    Example:
        >>> review = create_review_agent('phase-abc123', 'agent-xyz789')
        >>> review.status
        'pending'
    """
    review = ReviewAgent(
        phase_id=phase_id,
        agent_id=agent_id,
        status=ReviewStatus.PENDING.value
    )

    logger.info(
        f"Created review agent {review.review_id} for phase {phase_id}, "
        f"reviewer: {agent_id}"
    )

    return review


def validate_verdict(verdict: str) -> bool:
    """
    Validate that a verdict string is valid.

    Args:
        verdict: Verdict string to validate

    Returns:
        True if valid, False otherwise
    """
    return verdict in REVIEW_VERDICTS


def validate_finding_type(finding_type: str) -> bool:
    """
    Validate that a finding type string is valid.

    Args:
        finding_type: Finding type to validate

    Returns:
        True if valid, False otherwise
    """
    return finding_type in REVIEW_FINDING_TYPES


def determine_verdict_from_findings(findings: List[ReviewFinding]) -> ReviewVerdict:
    """
    Automatically determine verdict based on findings.

    Logic:
    - If any blocker: REJECTED
    - If any critical issue: REJECTED
    - If any high severity issue: NEEDS_REVISION
    - Otherwise: APPROVED

    Args:
        findings: List of review findings

    Returns:
        Appropriate ReviewVerdict based on findings

    Example:
        >>> findings = [ReviewFinding(finding_type='issue', severity='high', message='Bug')]
        >>> verdict = determine_verdict_from_findings(findings)
        >>> verdict
        <ReviewVerdict.NEEDS_REVISION: 'needs_revision'>
    """
    if not findings:
        logger.debug("No findings, auto-approving")
        return ReviewVerdict.APPROVED

    # Check for blockers
    blockers = [f for f in findings if f.is_blocker()]
    if blockers:
        logger.debug(f"Found {len(blockers)} blockers, rejecting")
        return ReviewVerdict.REJECTED

    # Check for critical issues
    critical_issues = [
        f for f in findings
        if f.finding_type == 'issue' and f.severity == 'critical'
    ]
    if critical_issues:
        logger.debug(f"Found {len(critical_issues)} critical issues, rejecting")
        return ReviewVerdict.REJECTED

    # Check for high severity issues
    high_issues = [
        f for f in findings
        if f.finding_type == 'issue' and f.severity == 'high'
    ]
    if high_issues:
        logger.debug(f"Found {len(high_issues)} high severity issues, needs revision")
        return ReviewVerdict.NEEDS_REVISION

    # No blocking issues
    logger.debug("No blocking issues found, approving")
    return ReviewVerdict.APPROVED


# ============================================================================
# VERDICT SUBMISSION AND PHASE TRANSITION FUNCTIONS
# ============================================================================

def submit_review_verdict(
    task_id: str,
    review_id: str,
    verdict: str,
    findings: List[dict],
    reviewer_notes: str = "",
    find_task_workspace=None,
    read_registry_with_lock=None,
    write_registry_with_lock=None
) -> Dict[str, Any]:
    """
    Submit a review verdict and trigger appropriate phase transition.

    This function:
    1. Validates the verdict is valid (approved, rejected, needs_revision)
    2. Updates the review record in the registry with verdict and findings
    3. Based on verdict, transitions the phase status:
       - APPROVED -> phase goes to APPROVED state
       - REJECTED -> phase goes to REJECTED state
       - NEEDS_REVISION -> phase goes to REVISING state

    Args:
        task_id: Task ID containing the phase
        review_id: ID of the review being submitted
        verdict: The verdict ('approved', 'rejected', 'needs_revision')
        findings: List of finding dicts [{type, severity, message, ...}]
        reviewer_notes: Optional notes from the reviewer
        find_task_workspace: Dependency injection - function to find workspace
        read_registry_with_lock: Dependency injection - function to read registry
        write_registry_with_lock: Dependency injection - function to write registry

    Returns:
        Dict with:
        - success: bool - True if verdict was submitted successfully
        - review_id: str - The review ID
        - verdict: str - The submitted verdict
        - phase_status: str - The new phase status after transition
        - findings_count: int - Number of findings recorded
        - error: str - Error message if failed (only if success=False)

    Raises:
        ValueError: If verdict is not valid

    Example:
        >>> result = submit_review_verdict(
        ...     task_id='TASK-123',
        ...     review_id='review-abc123',
        ...     verdict='approved',
        ...     findings=[{'type': 'praise', 'severity': 'low', 'message': 'Good work'}],
        ...     find_task_workspace=my_find_func,
        ...     read_registry_with_lock=my_read_func,
        ...     write_registry_with_lock=my_write_func
        ... )
    """
    import os  # Local import to avoid top-level dependency
    import json

    logger.info(f"Submitting review verdict: task={task_id}, review={review_id}, verdict={verdict}")

    # Validate verdict
    if verdict not in REVIEW_VERDICTS:
        error_msg = f"Invalid verdict '{verdict}'. Must be one of: {REVIEW_VERDICTS}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg,
            'review_id': review_id,
            'verdict': verdict,
            'phase_status': None,
            'findings_count': 0
        }

    # Validate dependencies
    if find_task_workspace is None:
        return {
            'success': False,
            'error': 'find_task_workspace function not provided',
            'review_id': review_id,
            'verdict': verdict,
            'phase_status': None,
            'findings_count': 0
        }

    if read_registry_with_lock is None or write_registry_with_lock is None:
        return {
            'success': False,
            'error': 'Registry read/write functions not provided',
            'review_id': review_id,
            'verdict': verdict,
            'phase_status': None,
            'findings_count': 0
        }

    # Find workspace
    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            'success': False,
            'error': f'Task {task_id} not found',
            'review_id': review_id,
            'verdict': verdict,
            'phase_status': None,
            'findings_count': 0
        }

    registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")

    try:
        # Read registry
        registry = read_registry_with_lock(registry_path)

        # Find the review in registry
        reviews = registry.get('reviews', [])
        review_record = None
        review_index = -1

        for i, r in enumerate(reviews):
            if r.get('review_id') == review_id:
                review_record = r
                review_index = i
                break

        if review_record is None:
            return {
                'success': False,
                'error': f'Review {review_id} not found in registry',
                'review_id': review_id,
                'verdict': verdict,
                'phase_status': None,
                'findings_count': 0
            }

        phase_id = review_record.get('phase_id')

        # Find the phase
        phases = registry.get('phases', [])
        phase = None
        phase_index = -1

        for i, p in enumerate(phases):
            if p.get('id') == phase_id:
                phase = p
                phase_index = i
                break

        if phase is None:
            return {
                'success': False,
                'error': f'Phase {phase_id} not found in registry',
                'review_id': review_id,
                'verdict': verdict,
                'phase_status': None,
                'findings_count': 0
            }

        # Convert findings to ReviewFinding format
        review_findings = []
        for finding_data in findings:
            if isinstance(finding_data, dict):
                review_findings.append(ReviewFinding.from_dict(finding_data).to_dict())
            else:
                review_findings.append(finding_data)

        # Update review record
        review_record['verdict'] = verdict
        review_record['findings'] = review_findings
        review_record['status'] = ReviewStatus.COMPLETED.value
        review_record['completed_at'] = datetime.now().isoformat()
        review_record['reviewer_notes'] = reviewer_notes
        registry['reviews'][review_index] = review_record

        # Determine new phase status based on verdict
        current_status = phase.get('status', '')
        new_phase_status = None

        if verdict == ReviewVerdict.APPROVED.value:
            new_phase_status = 'approved'
        elif verdict == ReviewVerdict.REJECTED.value:
            new_phase_status = 'rejected'
        elif verdict == ReviewVerdict.NEEDS_REVISION.value:
            new_phase_status = 'revising'

        # Update phase status
        if new_phase_status:
            phase['status'] = new_phase_status
            phase['status_updated_at'] = datetime.now().isoformat()
            phase['review_verdict'] = verdict
            phase['review_id'] = review_id
            registry['phases'][phase_index] = phase

            logger.info(
                f"Phase {phase_id} transitioned: {current_status} -> {new_phase_status} "
                f"(verdict={verdict})"
            )

        # Increment version
        registry['version'] = registry.get('version', 0) + 1

        # Write registry
        write_registry_with_lock(registry_path, registry)

        return {
            'success': True,
            'review_id': review_id,
            'verdict': verdict,
            'phase_status': new_phase_status,
            'findings_count': len(review_findings),
            'phase_id': phase_id
        }

    except Exception as e:
        error_msg = f"Error submitting review verdict: {e}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg,
            'review_id': review_id,
            'verdict': verdict,
            'phase_status': None,
            'findings_count': 0
        }


def calculate_aggregate_verdict(
    reviews: List[Dict[str, Any]],
    config: Optional[ReviewConfig] = None
) -> Dict[str, Any]:
    """
    Calculate aggregate verdict from multiple review results.

    Given multiple review verdicts, determines the final outcome based on
    ReviewConfig settings (require_unanimous, auto_approve_threshold).

    Aggregation Logic:
    1. If require_unanimous=True: All must approve for APPROVED, any rejection -> REJECTED
    2. If require_unanimous=False: Majority rule with tie-breaker to NEEDS_REVISION
    3. auto_approve_threshold: If approval ratio >= threshold, auto-approve

    Args:
        reviews: List of review dicts with 'verdict' field
        config: Optional ReviewConfig for aggregation rules

    Returns:
        Dict with:
        - verdict: str - Final aggregated verdict
        - reasoning: str - Explanation of how verdict was determined
        - approval_count: int - Number of APPROVED verdicts
        - rejection_count: int - Number of REJECTED verdicts
        - revision_count: int - Number of NEEDS_REVISION verdicts
        - total_reviews: int - Total number of reviews

    Example:
        >>> reviews = [
        ...     {'verdict': 'approved'},
        ...     {'verdict': 'needs_revision'},
        ...     {'verdict': 'approved'}
        ... ]
        >>> result = calculate_aggregate_verdict(reviews)
        >>> result['verdict']
        'approved'
    """
    if config is None:
        config = ReviewConfig()

    if not reviews:
        return {
            'verdict': ReviewVerdict.APPROVED.value,
            'reasoning': 'No reviews submitted, defaulting to approved',
            'approval_count': 0,
            'rejection_count': 0,
            'revision_count': 0,
            'total_reviews': 0
        }

    # Count verdicts
    approval_count = 0
    rejection_count = 0
    revision_count = 0

    for review in reviews:
        verdict = review.get('verdict', '')
        if verdict == ReviewVerdict.APPROVED.value:
            approval_count += 1
        elif verdict == ReviewVerdict.REJECTED.value:
            rejection_count += 1
        elif verdict == ReviewVerdict.NEEDS_REVISION.value:
            revision_count += 1

    total_reviews = len(reviews)

    logger.debug(
        f"Aggregating {total_reviews} reviews: "
        f"approved={approval_count}, rejected={rejection_count}, revision={revision_count}"
    )

    # Apply aggregation rules
    final_verdict = None
    reasoning = ""

    # Check auto-approve threshold first
    if config.should_auto_approve(approval_count, total_reviews):
        final_verdict = ReviewVerdict.APPROVED.value
        approval_ratio = approval_count / total_reviews
        reasoning = (
            f"Auto-approved: {approval_count}/{total_reviews} approvals "
            f"({approval_ratio:.1%}) meets threshold ({config.auto_approve_threshold:.1%})"
        )

    elif config.require_unanimous:
        # Unanimous decision required
        if rejection_count > 0:
            final_verdict = ReviewVerdict.REJECTED.value
            reasoning = f"Unanimous required: {rejection_count} rejection(s) prevent approval"
        elif revision_count > 0:
            final_verdict = ReviewVerdict.NEEDS_REVISION.value
            reasoning = f"Unanimous required: {revision_count} revision request(s) prevent approval"
        else:
            final_verdict = ReviewVerdict.APPROVED.value
            reasoning = f"Unanimous approval: all {approval_count} reviewers approved"

    else:
        # Majority rule
        if rejection_count > approval_count and rejection_count > revision_count:
            final_verdict = ReviewVerdict.REJECTED.value
            reasoning = f"Majority rejected: {rejection_count}/{total_reviews} rejections"
        elif approval_count > rejection_count and approval_count > revision_count:
            final_verdict = ReviewVerdict.APPROVED.value
            reasoning = f"Majority approved: {approval_count}/{total_reviews} approvals"
        elif revision_count >= approval_count or revision_count >= rejection_count:
            # Tie or revision majority
            final_verdict = ReviewVerdict.NEEDS_REVISION.value
            reasoning = f"Needs revision: {revision_count}/{total_reviews} revision requests (tie-breaker)"
        else:
            # Default to needs_revision on ties
            final_verdict = ReviewVerdict.NEEDS_REVISION.value
            reasoning = "No clear majority, defaulting to needs_revision"

    logger.info(f"Aggregate verdict: {final_verdict} - {reasoning}")

    return {
        'verdict': final_verdict,
        'reasoning': reasoning,
        'approval_count': approval_count,
        'rejection_count': rejection_count,
        'revision_count': revision_count,
        'total_reviews': total_reviews
    }


def finalize_phase_review(
    task_id: str,
    phase_id: str,
    find_task_workspace=None,
    read_registry_with_lock=None,
    write_registry_with_lock=None
) -> Dict[str, Any]:
    """
    Finalize phase review when all reviewers have submitted.

    This function:
    1. Checks if all required reviewers have submitted verdicts
    2. Aggregates verdicts using calculate_aggregate_verdict()
    3. Triggers the appropriate phase transition
    4. Appends review summary to the handover document

    Called automatically when all reviewers complete, or manually by orchestrator.

    Args:
        task_id: Task ID
        phase_id: Phase ID to finalize review for
        find_task_workspace: Dependency injection
        read_registry_with_lock: Dependency injection
        write_registry_with_lock: Dependency injection

    Returns:
        Dict with:
        - success: bool - True if finalization succeeded
        - finalized: bool - True if review was finalized (False if still waiting)
        - verdict: str - Final verdict (only if finalized)
        - phase_status: str - New phase status (only if finalized)
        - reviews_submitted: int - Number of reviews submitted
        - reviews_required: int - Number of reviews required
        - handover_updated: bool - True if handover was updated
        - error: str - Error message if failed

    Example:
        >>> result = finalize_phase_review(
        ...     task_id='TASK-123',
        ...     phase_id='phase-abc123',
        ...     find_task_workspace=my_find_func,
        ...     read_registry_with_lock=my_read_func,
        ...     write_registry_with_lock=my_write_func
        ... )
    """
    import os

    logger.info(f"Finalizing phase review: task={task_id}, phase={phase_id}")

    # Validate dependencies
    if find_task_workspace is None:
        return {
            'success': False,
            'finalized': False,
            'error': 'find_task_workspace function not provided'
        }

    if read_registry_with_lock is None or write_registry_with_lock is None:
        return {
            'success': False,
            'finalized': False,
            'error': 'Registry read/write functions not provided'
        }

    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            'success': False,
            'finalized': False,
            'error': f'Task {task_id} not found'
        }

    registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")

    try:
        registry = read_registry_with_lock(registry_path)

        # Find the phase
        phases = registry.get('phases', [])
        phase = None
        phase_index = -1

        for i, p in enumerate(phases):
            if p.get('id') == phase_id:
                phase = p
                phase_index = i
                break

        if phase is None:
            return {
                'success': False,
                'finalized': False,
                'error': f'Phase {phase_id} not found'
            }

        # Get review config (from phase or default)
        config_data = phase.get('review_config', {})
        config = ReviewConfig.from_dict(config_data) if config_data else ReviewConfig()

        # Find all reviews for this phase
        reviews = registry.get('reviews', [])
        phase_reviews = [r for r in reviews if r.get('phase_id') == phase_id]

        # Count completed reviews
        completed_reviews = [
            r for r in phase_reviews
            if r.get('status') == ReviewStatus.COMPLETED.value
        ]

        reviews_submitted = len(completed_reviews)
        reviews_required = config.min_reviewers

        logger.debug(
            f"Phase {phase_id}: {reviews_submitted}/{reviews_required} reviews submitted"
        )

        # Check if all required reviews are in
        if reviews_submitted < reviews_required:
            return {
                'success': True,
                'finalized': False,
                'reviews_submitted': reviews_submitted,
                'reviews_required': reviews_required,
                'message': f'Waiting for {reviews_required - reviews_submitted} more review(s)'
            }

        # All reviews in - aggregate verdicts
        aggregate_result = calculate_aggregate_verdict(completed_reviews, config)
        final_verdict = aggregate_result['verdict']

        # Determine new phase status
        if final_verdict == ReviewVerdict.APPROVED.value:
            new_status = 'approved'
        elif final_verdict == ReviewVerdict.REJECTED.value:
            new_status = 'rejected'
        else:
            new_status = 'revising'

        # Update phase
        phase['status'] = new_status
        phase['status_updated_at'] = datetime.now().isoformat()
        phase['review_finalized_at'] = datetime.now().isoformat()
        phase['final_verdict'] = final_verdict
        phase['verdict_reasoning'] = aggregate_result['reasoning']
        registry['phases'][phase_index] = phase

        # Increment version
        registry['version'] = registry.get('version', 0) + 1

        # Write registry
        write_registry_with_lock(registry_path, registry)

        # Update handover document with review summary
        handover_updated = False
        try:
            handover_updated = _update_handover_with_review(
                workspace, phase_id, phase.get('name', 'Unknown'),
                completed_reviews, aggregate_result
            )
        except Exception as e:
            logger.warning(f"Could not update handover with review summary: {e}")

        logger.info(
            f"Phase {phase_id} review finalized: verdict={final_verdict}, "
            f"status={new_status}, handover_updated={handover_updated}"
        )

        return {
            'success': True,
            'finalized': True,
            'verdict': final_verdict,
            'phase_status': new_status,
            'reviews_submitted': reviews_submitted,
            'reviews_required': reviews_required,
            'reasoning': aggregate_result['reasoning'],
            'handover_updated': handover_updated
        }

    except Exception as e:
        error_msg = f"Error finalizing phase review: {e}"
        logger.error(error_msg)
        return {
            'success': False,
            'finalized': False,
            'error': error_msg
        }


def _update_handover_with_review(
    workspace: str,
    phase_id: str,
    phase_name: str,
    reviews: List[Dict[str, Any]],
    aggregate_result: Dict[str, Any]
) -> bool:
    """
    Internal helper to update handover document with review summary.

    Args:
        workspace: Task workspace path
        phase_id: Phase ID
        phase_name: Phase name
        reviews: List of completed review dicts
        aggregate_result: Result from calculate_aggregate_verdict

    Returns:
        True if handover was updated successfully
    """
    import os

    try:
        # Import handover module - handle potential import issues
        try:
            from . import handover as handover_module
        except ImportError:
            # Try absolute import if relative fails
            import orchestrator.handover as handover_module

        # Load existing handover
        existing_handover = handover_module.load_handover(workspace, phase_id)

        # Format review summary
        review_summary = format_review_for_handover(reviews, aggregate_result)

        if existing_handover:
            # Append to existing summary
            existing_summary = existing_handover.summary or ""
            existing_handover.summary = (
                f"{existing_summary}\n\n"
                "## Review Summary\n"
                f"{review_summary}"
            )

            # Add review findings to key_findings
            for review in reviews:
                for finding in review.get('findings', []):
                    if finding.get('severity') in ('critical', 'high'):
                        existing_handover.key_findings.append({
                            'type': f"review_{finding.get('finding_type', 'issue')}",
                            'severity': finding.get('severity', 'medium'),
                            'message': finding.get('message', ''),
                            'data': {
                                'reviewer': review.get('agent_id', 'unknown'),
                                'file_path': finding.get('file_path'),
                                'suggested_fix': finding.get('suggested_fix')
                            }
                        })

            # Save updated handover
            save_result = handover_module.save_handover(workspace, existing_handover)
            return save_result.get('success', False)

        else:
            # Create new handover with review summary
            new_handover = handover_module.HandoverDocument(
                phase_id=phase_id,
                phase_name=phase_name,
                summary=f"## Review Summary\n{review_summary}",
                key_findings=[],
                blockers=[],
                recommendations=[],
                artifacts=[],
                metrics={
                    'reviews_submitted': len(reviews),
                    'final_verdict': aggregate_result.get('verdict')
                }
            )

            save_result = handover_module.save_handover(workspace, new_handover)
            return save_result.get('success', False)

    except Exception as e:
        logger.error(f"Error updating handover with review: {e}")
        return False


def format_review_for_handover(
    reviews: List[Dict[str, Any]],
    aggregate_result: Dict[str, Any],
    max_findings_per_review: int = 5
) -> str:
    """
    Format review results for inclusion in handover document.

    Creates a human-readable summary of review results suitable for
    inclusion in handover documents. Respects token limits by truncating
    findings if necessary.

    Args:
        reviews: List of completed review dicts
        aggregate_result: Result from calculate_aggregate_verdict
        max_findings_per_review: Maximum findings to include per review

    Returns:
        Formatted markdown string summarizing the reviews

    Example:
        >>> summary = format_review_for_handover(reviews, aggregate_result)
        >>> print(summary)
        **Final Verdict:** APPROVED
        **Reasoning:** Majority approved: 2/3 approvals
        ...
    """
    lines = []

    # Header with aggregate result
    verdict = aggregate_result.get('verdict', 'unknown').upper()
    reasoning = aggregate_result.get('reasoning', 'No reasoning provided')

    lines.append(f"**Final Verdict:** {verdict}")
    lines.append(f"**Reasoning:** {reasoning}")
    lines.append("")

    # Vote counts
    lines.append("**Vote Summary:**")
    lines.append(f"- Approved: {aggregate_result.get('approval_count', 0)}")
    lines.append(f"- Rejected: {aggregate_result.get('rejection_count', 0)}")
    lines.append(f"- Needs Revision: {aggregate_result.get('revision_count', 0)}")
    lines.append(f"- Total Reviewers: {aggregate_result.get('total_reviews', 0)}")
    lines.append("")

    # Individual review summaries
    if reviews:
        lines.append("### Individual Reviews")
        lines.append("")

        for review in reviews:
            reviewer = review.get('agent_id', 'Unknown Reviewer')
            review_verdict = review.get('verdict', 'unknown')
            findings = review.get('findings', [])

            lines.append(f"**Reviewer:** {reviewer}")
            lines.append(f"**Verdict:** {review_verdict}")

            if findings:
                lines.append(f"**Findings ({len(findings)}):**")
                # Only include up to max_findings_per_review
                for i, finding in enumerate(findings[:max_findings_per_review]):
                    severity = finding.get('severity', 'medium').upper()
                    ftype = finding.get('finding_type', 'issue')
                    message = finding.get('message', 'No message')
                    # Truncate long messages
                    if len(message) > 200:
                        message = message[:200] + "..."
                    lines.append(f"  - [{severity}] {ftype}: {message}")

                if len(findings) > max_findings_per_review:
                    lines.append(f"  - _({len(findings) - max_findings_per_review} more findings truncated)_")
            else:
                lines.append("**Findings:** None")

            lines.append("")

    return "\n".join(lines)


# ============================================================================
# REVIEW TRIGGERING AND RECORD CREATION FUNCTIONS
# ============================================================================

def create_review_record(
    task_id: str,
    phase_id: str,
    agent_id: str,
    workspace: str,
    review_config: Optional[ReviewConfig] = None
) -> Dict[str, Any]:
    """
    Create a new review record in the task registry.

    Creates a ReviewAgent entry and stores it atomically in the registry
    using LockedRegistryFile to prevent race conditions.

    Args:
        task_id: Task ID for logging/context
        phase_id: Phase ID being reviewed
        agent_id: ID of the agent that will perform the review
        workspace: Task workspace path (contains AGENT_REGISTRY.json)
        review_config: Optional review configuration

    Returns:
        Dict with:
        - success: bool - True if record was created
        - review_id: str - The generated review ID
        - review: dict - The full review record
        - error: str - Error message if failed

    Example:
        >>> result = create_review_record(
        ...     task_id='TASK-123',
        ...     phase_id='phase-abc',
        ...     agent_id='reviewer-xyz',
        ...     workspace='/path/to/workspace'
        ... )
        >>> result['review_id']
        'review-abc123def456'
    """
    import os
    import json

    logger.info(
        f"Creating review record: task={task_id}, phase={phase_id}, "
        f"agent={agent_id}, workspace={workspace}"
    )

    registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")

    try:
        # Import LockedRegistryFile for atomic operations
        try:
            from .registry import LockedRegistryFile
        except ImportError:
            from orchestrator.registry import LockedRegistryFile

        # Create the review agent record
        review = ReviewAgent(
            phase_id=phase_id,
            agent_id=agent_id,
            status=ReviewStatus.PENDING.value
        )
        review_dict = review.to_dict()

        # Atomically add to registry
        with LockedRegistryFile(registry_path) as (registry, f):
            # Ensure 'reviews' section exists
            if 'reviews' not in registry:
                registry['reviews'] = []
                logger.debug(f"Initialized 'reviews' section in registry")

            # Add the review record
            registry['reviews'].append(review_dict)

            # Increment version
            registry['version'] = registry.get('version', 0) + 1

            # Write back atomically
            f.seek(0)
            f.write(json.dumps(registry, indent=2))
            f.truncate()

            logger.info(
                f"Created review record {review.review_id} for phase {phase_id} "
                f"(registry version={registry['version']})"
            )

        return {
            'success': True,
            'review_id': review.review_id,
            'review': review_dict,
            'phase_id': phase_id,
            'agent_id': agent_id
        }

    except FileNotFoundError:
        error_msg = f"Registry file not found: {registry_path}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg,
            'review_id': None,
            'review': None
        }

    except Exception as e:
        error_msg = f"Failed to create review record: {e}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg,
            'review_id': None,
            'review': None
        }


def trigger_phase_review(
    task_id: str,
    phase_id: str,
    workspace: str,
    review_config: Optional[ReviewConfig] = None,
    deploy_agent_fn: Optional[callable] = None
) -> Dict[str, Any]:
    """
    Trigger a review for a phase that has transitioned to AWAITING_REVIEW.

    This function:
    1. Creates a review record in the registry
    2. Optionally deploys a review agent via deploy_agent_fn callback
    3. Updates the phase status to UNDER_REVIEW

    Called by try_advance_to_review() when a phase transitions to AWAITING_REVIEW,
    or can be called manually to initiate a review.

    Args:
        task_id: Task ID containing the phase
        phase_id: Phase ID to review
        workspace: Task workspace path
        review_config: Optional review configuration (defaults used if None)
        deploy_agent_fn: Optional callback to deploy a review agent.
                        Called with (task_id, phase_id, workspace, review_id).
                        Should return deployment info (agent_id, etc).

    Returns:
        Dict with:
        - success: bool - True if review was triggered successfully
        - review_id: str - The generated review ID
        - agent_deployed: bool - True if agent was deployed
        - deployment_result: Any - Result from deploy_agent_fn (if called)
        - phase_status: str - New phase status (should be 'under_review')
        - error: str - Error message if failed

    Example:
        >>> def my_deploy_fn(task_id, phase_id, workspace, review_id):
        ...     # Deploy the review agent
        ...     return {'agent_id': 'review-agent-123'}
        >>>
        >>> result = trigger_phase_review(
        ...     task_id='TASK-123',
        ...     phase_id='phase-abc',
        ...     workspace='/path/to/workspace',
        ...     deploy_agent_fn=my_deploy_fn
        ... )
    """
    import os
    import json

    logger.info(
        f"Triggering phase review: task={task_id}, phase={phase_id}, "
        f"workspace={workspace}"
    )

    if review_config is None:
        review_config = ReviewConfig()

    registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")

    try:
        # Import LockedRegistryFile for atomic operations
        try:
            from .registry import LockedRegistryFile
        except ImportError:
            from orchestrator.registry import LockedRegistryFile

        # Generate review ID upfront so we can pass it to deploy_agent_fn
        review_id = f"review-{uuid.uuid4().hex[:12]}"
        agent_id = ""  # Will be set after deployment

        # First, deploy the review agent if callback provided
        agent_deployed = False
        deployment_result = None

        if deploy_agent_fn is not None:
            try:
                logger.debug(f"Deploying review agent for phase {phase_id}")
                deployment_result = deploy_agent_fn(
                    task_id, phase_id, workspace, review_id
                )
                agent_deployed = True

                # Extract agent_id from deployment result if available
                if isinstance(deployment_result, dict):
                    agent_id = deployment_result.get('agent_id', f"reviewer-{uuid.uuid4().hex[:8]}")
                else:
                    agent_id = f"reviewer-{uuid.uuid4().hex[:8]}"

                logger.info(f"Review agent deployed: {agent_id}")

            except Exception as e:
                logger.error(f"Failed to deploy review agent: {e}")
                deployment_result = {'error': str(e)}
        else:
            # No deploy function - just create the record with placeholder agent
            agent_id = f"pending-reviewer-{uuid.uuid4().hex[:8]}"

        # Create review record and update phase status atomically
        with LockedRegistryFile(registry_path) as (registry, f):
            # Ensure 'reviews' section exists
            if 'reviews' not in registry:
                registry['reviews'] = []
                logger.debug(f"Initialized 'reviews' section in registry")

            # Create the review agent record
            review = ReviewAgent(
                review_id=review_id,
                phase_id=phase_id,
                agent_id=agent_id,
                status=ReviewStatus.IN_PROGRESS.value if agent_deployed else ReviewStatus.PENDING.value
            )
            review_dict = review.to_dict()

            # Add the review record
            registry['reviews'].append(review_dict)

            # Update phase status to UNDER_REVIEW
            phases = registry.get('phases', [])
            phase_updated = False

            for phase in phases:
                if phase.get('id') == phase_id:
                    phase['status'] = 'under_review'
                    phase['status_updated_at'] = datetime.now().isoformat()
                    phase['current_review_id'] = review_id
                    phase['review_config'] = review_config.to_dict()
                    phase_updated = True
                    break

            if not phase_updated:
                logger.warning(f"Phase {phase_id} not found in registry, review record created anyway")

            # Increment version
            registry['version'] = registry.get('version', 0) + 1

            # Write back atomically
            f.seek(0)
            f.write(json.dumps(registry, indent=2))
            f.truncate()

            logger.info(
                f"Phase review triggered: review_id={review_id}, phase={phase_id}, "
                f"agent_deployed={agent_deployed}, version={registry['version']}"
            )

        return {
            'success': True,
            'review_id': review_id,
            'agent_id': agent_id,
            'agent_deployed': agent_deployed,
            'deployment_result': deployment_result,
            'phase_status': 'under_review',
            'review_config': review_config.to_dict()
        }

    except FileNotFoundError:
        error_msg = f"Registry file not found: {registry_path}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg,
            'review_id': None,
            'agent_deployed': False,
            'phase_status': None
        }

    except Exception as e:
        error_msg = f"Failed to trigger phase review: {e}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg,
            'review_id': None,
            'agent_deployed': False,
            'phase_status': None
        }


def get_phase_reviews(
    task_id: str,
    phase_id: str,
    workspace: str,
    status_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get all reviews for a specific phase.

    Args:
        task_id: Task ID for context
        phase_id: Phase ID to get reviews for
        workspace: Task workspace path
        status_filter: Optional filter by review status (pending, in_progress, completed)

    Returns:
        Dict with:
        - success: bool
        - reviews: List of review dicts
        - total: int - Total review count
        - by_status: Dict of counts by status
        - error: str if failed
    """
    import os
    import json

    logger.debug(f"Getting reviews for phase {phase_id}")

    registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")

    try:
        # Read registry
        try:
            from .registry import read_registry_with_lock
        except ImportError:
            from orchestrator.registry import read_registry_with_lock

        registry = read_registry_with_lock(registry_path)
        all_reviews = registry.get('reviews', [])

        # Filter by phase_id
        phase_reviews = [r for r in all_reviews if r.get('phase_id') == phase_id]

        # Apply status filter if provided
        if status_filter:
            phase_reviews = [r for r in phase_reviews if r.get('status') == status_filter]

        # Count by status
        by_status = {}
        for review in phase_reviews:
            status = review.get('status', 'unknown')
            by_status[status] = by_status.get(status, 0) + 1

        return {
            'success': True,
            'reviews': phase_reviews,
            'total': len(phase_reviews),
            'by_status': by_status,
            'phase_id': phase_id
        }

    except Exception as e:
        error_msg = f"Failed to get phase reviews: {e}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg,
            'reviews': [],
            'total': 0,
            'by_status': {}
        }


# ============================================================================
# MCP TOOL WRAPPER FUNCTIONS
# ============================================================================

def request_phase_review(
    task_id: str,
    phase_id: Optional[str] = None,
    reviewer_types: Optional[List[str]] = None,
    review_config: Optional[dict] = None,
    find_task_workspace=None,
    read_registry_with_lock=None
) -> Dict[str, Any]:
    """
    Initiate a review for a phase (MCP wrapper).

    This MCP tool wrapper creates a new review request for a phase.
    If phase_id is not specified, uses the current active phase.

    Args:
        task_id: Task ID
        phase_id: Phase ID to review (optional, uses current phase if not specified)
        reviewer_types: List of reviewer agent types (e.g., ['code_reviewer', 'test_runner'])
        review_config: Optional review configuration dict (min_reviewers, require_unanimous, etc.)
        find_task_workspace: Dependency injection - function to find workspace
        read_registry_with_lock: Dependency injection - function to read registry

    Returns:
        Dict with:
        - success: bool - True if review was initiated
        - review_id: str - The created review ID
        - phase_id: str - Phase being reviewed
        - reviewer_types: List[str] - Types of reviewers requested
        - status: str - Review status ('pending')
        - error: str - Error message if failed

    Example:
        >>> result = request_phase_review(
        ...     task_id='TASK-123',
        ...     phase_id='phase-abc123',
        ...     reviewer_types=['code_reviewer', 'security_auditor'],
        ...     find_task_workspace=my_find_func,
        ...     read_registry_with_lock=my_read_func
        ... )
        >>> result['review_id']
        'review-xyz789'
    """
    import os

    logger.info(f"Requesting phase review: task={task_id}, phase={phase_id}")

    # Validate dependencies
    if find_task_workspace is None:
        return {
            'success': False,
            'error': 'find_task_workspace function not provided',
            'review_id': None,
            'phase_id': phase_id,
            'reviewer_types': reviewer_types or [],
            'status': None
        }

    if read_registry_with_lock is None:
        return {
            'success': False,
            'error': 'read_registry_with_lock function not provided',
            'review_id': None,
            'phase_id': phase_id,
            'reviewer_types': reviewer_types or [],
            'status': None
        }

    workspace = find_task_workspace(task_id)
    if not workspace:
        return {
            'success': False,
            'error': f'Task {task_id} not found',
            'review_id': None,
            'phase_id': phase_id,
            'reviewer_types': reviewer_types or [],
            'status': None
        }

    registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")

    try:
        registry = read_registry_with_lock(registry_path)

        # Find phase - use specified or find current active phase
        phases = registry.get('phases', [])
        target_phase = None

        if phase_id:
            for p in phases:
                if p.get('id') == phase_id:
                    target_phase = p
                    break
        else:
            # Find current active phase
            for p in phases:
                status = p.get('status', '')
                if status in ('active', 'awaiting_review', 'under_review'):
                    target_phase = p
                    phase_id = p.get('id')
                    break

        if target_phase is None:
            return {
                'success': False,
                'error': f'Phase {phase_id or "current"} not found',
                'review_id': None,
                'phase_id': phase_id,
                'reviewer_types': reviewer_types or [],
                'status': None
            }

        # Default reviewer types if not specified
        if not reviewer_types:
            reviewer_types = ['code_reviewer']

        # Use trigger_phase_review to create the review
        result = trigger_phase_review(
            task_id=task_id,
            phase_id=phase_id,
            reviewer_agent_id=f"review-{uuid.uuid4().hex[:8]}",
            workspace=workspace,
            review_config=ReviewConfig.from_dict(review_config) if review_config else None
        )

        if result.get('success'):
            return {
                'success': True,
                'review_id': result.get('review_id'),
                'phase_id': phase_id,
                'phase_name': target_phase.get('name', 'Unknown'),
                'reviewer_types': reviewer_types,
                'status': ReviewStatus.PENDING.value
            }
        else:
            return {
                'success': False,
                'error': result.get('error', 'Failed to trigger review'),
                'review_id': None,
                'phase_id': phase_id,
                'reviewer_types': reviewer_types,
                'status': None
            }

    except Exception as e:
        error_msg = f"Error requesting phase review: {e}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg,
            'review_id': None,
            'phase_id': phase_id,
            'reviewer_types': reviewer_types or [],
            'status': None
        }


def submit_review(
    task_id: str,
    review_id: str,
    verdict: str,
    findings: List[dict],
    notes: str = "",
    find_task_workspace=None,
    read_registry_with_lock=None,
    write_registry_with_lock=None
) -> Dict[str, Any]:
    """
    Submit a review verdict (MCP wrapper for agents).

    Thin wrapper around submit_review_verdict for agents to use
    when they complete their review.

    Args:
        task_id: Task ID
        review_id: Review ID being submitted
        verdict: Verdict ('approved', 'rejected', 'needs_revision')
        findings: List of finding dicts [{finding_type, severity, message, ...}]
        notes: Optional reviewer notes
        find_task_workspace: Dependency injection
        read_registry_with_lock: Dependency injection
        write_registry_with_lock: Dependency injection

    Returns:
        Dict with:
        - success: bool
        - review_id: str
        - verdict: str
        - phase_status: str - New phase status after transition
        - findings_count: int
        - error: str - Error message if failed

    Example:
        >>> result = submit_review(
        ...     task_id='TASK-123',
        ...     review_id='review-abc123',
        ...     verdict='approved',
        ...     findings=[{'finding_type': 'praise', 'severity': 'low', 'message': 'Clean code'}],
        ...     notes='All checks passed'
        ... )
    """
    logger.info(f"submit_review called: task={task_id}, review={review_id}, verdict={verdict}")

    # Delegate to submit_review_verdict
    return submit_review_verdict(
        task_id=task_id,
        review_id=review_id,
        verdict=verdict,
        findings=findings,
        reviewer_notes=notes,
        find_task_workspace=find_task_workspace,
        read_registry_with_lock=read_registry_with_lock,
        write_registry_with_lock=write_registry_with_lock
    )


def get_review_status(
    task_id: str,
    phase_id: Optional[str] = None,
    review_id: Optional[str] = None,
    find_task_workspace=None,
    read_registry_with_lock=None
) -> Dict[str, Any]:
    """
    Get current review status for a phase (MCP wrapper).

    Returns status information including all reviewers and their verdicts.

    Args:
        task_id: Task ID
        phase_id: Phase ID to get review status for (optional)
        review_id: Specific review ID to get status for (optional)
        find_task_workspace: Dependency injection
        read_registry_with_lock: Dependency injection

    Returns:
        Dict with:
        - success: bool
        - phase_id: str
        - phase_status: str - Current phase status
        - reviews: List[dict] - All reviews for the phase
        - aggregate_verdict: dict - Aggregated verdict if all reviews complete
        - pending_reviewers: int - Number of reviewers still pending
        - completed_reviewers: int - Number of completed reviews
        - error: str - Error message if failed

    Example:
        >>> status = get_review_status(
        ...     task_id='TASK-123',
        ...     phase_id='phase-abc123'
        ... )
        >>> status['completed_reviewers']
        2
    """
    import os

    logger.debug(f"Getting review status: task={task_id}, phase={phase_id}, review={review_id}")

    if find_task_workspace is None:
        return {'success': False, 'error': 'find_task_workspace function not provided'}

    if read_registry_with_lock is None:
        return {'success': False, 'error': 'read_registry_with_lock function not provided'}

    workspace = find_task_workspace(task_id)
    if not workspace:
        return {'success': False, 'error': f'Task {task_id} not found'}

    registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")

    try:
        registry = read_registry_with_lock(registry_path)

        # If review_id specified, get specific review
        if review_id:
            reviews = registry.get('reviews', [])
            for review in reviews:
                if review.get('review_id') == review_id:
                    return {
                        'success': True,
                        'review': review,
                        'review_id': review_id,
                        'phase_id': review.get('phase_id'),
                        'status': review.get('status'),
                        'verdict': review.get('verdict'),
                        'findings_count': len(review.get('findings', []))
                    }
            return {'success': False, 'error': f'Review {review_id} not found'}

        # Get phase reviews
        if not phase_id:
            phases = registry.get('phases', [])
            for p in phases:
                status = p.get('status', '')
                if status in ('awaiting_review', 'under_review'):
                    phase_id = p.get('id')
                    break

        if not phase_id:
            return {'success': False, 'error': 'No phase_id and no phase awaiting review'}

        # Find phase
        phases = registry.get('phases', [])
        target_phase = None
        for p in phases:
            if p.get('id') == phase_id:
                target_phase = p
                break

        if not target_phase:
            return {'success': False, 'error': f'Phase {phase_id} not found'}

        # Get all reviews for this phase
        all_reviews = registry.get('reviews', [])
        phase_reviews = [r for r in all_reviews if r.get('phase_id') == phase_id]

        # Count by status
        pending = [r for r in phase_reviews if r.get('status') == ReviewStatus.PENDING.value]
        in_progress = [r for r in phase_reviews if r.get('status') == ReviewStatus.IN_PROGRESS.value]
        completed = [r for r in phase_reviews if r.get('status') == ReviewStatus.COMPLETED.value]

        # Calculate aggregate if all complete
        aggregate_verdict = None
        if completed and not pending and not in_progress:
            config_data = target_phase.get('review_config', {})
            config = ReviewConfig.from_dict(config_data) if config_data else ReviewConfig()
            aggregate_verdict = calculate_aggregate_verdict(completed, config)

        return {
            'success': True,
            'phase_id': phase_id,
            'phase_name': target_phase.get('name', 'Unknown'),
            'phase_status': target_phase.get('status'),
            'reviews': phase_reviews,
            'total_reviews': len(phase_reviews),
            'pending_reviewers': len(pending),
            'in_progress_reviewers': len(in_progress),
            'completed_reviewers': len(completed),
            'aggregate_verdict': aggregate_verdict,
            'is_finalized': target_phase.get('review_finalized_at') is not None
        }

    except Exception as e:
        error_msg = f"Error getting review status: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}


def get_review_context(
    task_id: str,
    review_id: str,
    find_task_workspace=None,
    read_registry_with_lock=None
) -> Dict[str, Any]:
    """
    Get context needed for a reviewer agent (MCP wrapper).

    Returns comprehensive context including:
    - Phase handover document
    - Changed files list
    - Agent findings from the phase
    - Review configuration

    Args:
        task_id: Task ID
        review_id: Review ID to get context for
        find_task_workspace: Dependency injection
        read_registry_with_lock: Dependency injection

    Returns:
        Dict with:
        - success: bool
        - review_id: str
        - phase_id: str
        - phase_name: str
        - handover_content: str - Full handover document as markdown
        - changed_files: List[str] - Files modified in the phase
        - agent_findings: List[dict] - Findings from phase agents
        - review_config: dict - Review configuration
        - reviewer_instructions: str - Instructions for the reviewer
        - error: str - Error message if failed

    Example:
        >>> context = get_review_context(
        ...     task_id='TASK-123',
        ...     review_id='review-abc123'
        ... )
        >>> print(context['handover_content'])
        '# Phase Handover: Implementation...'
    """
    import os
    import json

    logger.info(f"Getting review context: task={task_id}, review={review_id}")

    if find_task_workspace is None:
        return {'success': False, 'error': 'find_task_workspace function not provided'}

    if read_registry_with_lock is None:
        return {'success': False, 'error': 'read_registry_with_lock function not provided'}

    workspace = find_task_workspace(task_id)
    if not workspace:
        return {'success': False, 'error': f'Task {task_id} not found'}

    registry_path = os.path.join(workspace, "AGENT_REGISTRY.json")

    try:
        registry = read_registry_with_lock(registry_path)

        # Find the review
        reviews = registry.get('reviews', [])
        review = None
        for r in reviews:
            if r.get('review_id') == review_id:
                review = r
                break

        if not review:
            return {'success': False, 'error': f'Review {review_id} not found'}

        phase_id = review.get('phase_id')

        # Find the phase
        phases = registry.get('phases', [])
        phase = None
        for p in phases:
            if p.get('id') == phase_id:
                phase = p
                break

        if not phase:
            return {'success': False, 'error': f'Phase {phase_id} not found'}

        phase_name = phase.get('name', 'Unknown Phase')

        # Load handover document
        handover_content = ""
        try:
            from . import handover as handover_module
            handover_doc = handover_module.load_handover(workspace, phase_id)
            if handover_doc:
                handover_content = handover_module.format_handover_markdown(handover_doc)
        except Exception as e:
            logger.warning(f"Could not load handover: {e}")
            handover_content = f"_Handover document not available: {e}_"

        # Get agent findings for this phase
        agent_findings = []
        findings_dir = os.path.join(workspace, "findings")
        if os.path.exists(findings_dir):
            phase_agents = [
                a for a in registry.get('agents', [])
                if a.get('phase_id') == phase_id
            ]
            agent_ids = {a.get('id') for a in phase_agents}

            for filename in os.listdir(findings_dir):
                if not filename.endswith('_findings.jsonl'):
                    continue
                agent_id = filename.replace('_findings.jsonl', '')
                if agent_id not in agent_ids:
                    continue

                findings_file = os.path.join(findings_dir, filename)
                try:
                    with open(findings_file, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    finding = json.loads(line)
                                    agent_findings.append(finding)
                                except json.JSONDecodeError:
                                    continue
                except Exception as e:
                    logger.warning(f"Error reading findings file {filename}: {e}")

        # Sort findings by severity
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        agent_findings.sort(key=lambda f: severity_order.get(f.get('severity', 'low'), 4))

        # Get changed files from artifacts
        changed_files = []
        if phase.get('artifacts'):
            changed_files = [a.get('path') for a in phase.get('artifacts', []) if a.get('path')]

        # Build reviewer instructions
        reviewer_instructions = _build_reviewer_instructions(
            phase_name=phase_name,
            reviewer_types=review.get('reviewer_types', ['code_reviewer']),
            findings_count=len(agent_findings),
            changed_files_count=len(changed_files)
        )

        return {
            'success': True,
            'review_id': review_id,
            'phase_id': phase_id,
            'phase_name': phase_name,
            'phase_status': phase.get('status'),
            'handover_content': handover_content,
            'changed_files': changed_files,
            'agent_findings': agent_findings,
            'agent_findings_count': len(agent_findings),
            'review_config': review.get('review_config', {}),
            'reviewer_types': review.get('reviewer_types', []),
            'reviewer_instructions': reviewer_instructions
        }

    except Exception as e:
        error_msg = f"Error getting review context: {e}"
        logger.error(error_msg)
        return {'success': False, 'error': error_msg}


def _build_reviewer_instructions(
    phase_name: str,
    reviewer_types: List[str],
    findings_count: int,
    changed_files_count: int
) -> str:
    """
    Build instructions for reviewer agents.

    Args:
        phase_name: Name of the phase being reviewed
        reviewer_types: Types of reviewers requested
        findings_count: Number of agent findings to review
        changed_files_count: Number of changed files

    Returns:
        Formatted instruction string for reviewers
    """
    instructions = f"""
## Review Instructions for {phase_name} Phase

You are reviewing the work completed in the **{phase_name}** phase.

### Your Review Scope
- Reviewer type(s): {', '.join(reviewer_types)}
- Agent findings to review: {findings_count}
- Changed files to examine: {changed_files_count}

### Review Process
1. **Read the handover document** - Understand what work was done
2. **Examine agent findings** - Check for critical/high severity issues
3. **Review changed files** - Verify code quality and correctness
4. **Determine verdict**:
   - `approved` - Work meets quality standards, ready to advance
   - `needs_revision` - Minor issues that should be fixed
   - `rejected` - Critical issues requiring significant rework

### Verdict Guidelines
- **APPROVE** if: All critical requirements met, no blocking issues, acceptable quality
- **NEEDS_REVISION** if: Minor fixable issues, no critical blockers
- **REJECT** if: Critical bugs/security issues, core functionality broken, significant rework needed

### Submitting Your Review
Use submit_review() with:
- Your verdict ('approved', 'needs_revision', 'rejected')
- List of findings [{{'finding_type': 'issue|suggestion|blocker|praise', 'severity': 'critical|high|medium|low', 'message': '...'}}]
- Optional notes explaining your decision
"""
    return instructions.strip()


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    # Enums
    'ReviewStatus',
    'ReviewVerdict',
    # Constants
    'REVIEW_VERDICTS',
    'REVIEW_FINDING_TYPES',
    'REVIEW_FINDING_SEVERITIES',
    'DEFAULT_MIN_REVIEWERS',
    'DEFAULT_REQUIRE_UNANIMOUS',
    'DEFAULT_AUTO_APPROVE_THRESHOLD',
    'DEFAULT_TIMEOUT_SECONDS',
    # Dataclasses
    'ReviewFinding',
    'ReviewAgent',
    'ReviewConfig',
    # TypedDicts
    'ReviewFindingDict',
    'ReviewAgentDict',
    'ReviewConfigDict',
    # Helper functions
    'create_review_agent',
    'validate_verdict',
    'validate_finding_type',
    'determine_verdict_from_findings',
    # Verdict submission and phase transition functions
    'submit_review_verdict',
    'calculate_aggregate_verdict',
    'finalize_phase_review',
    'format_review_for_handover',
    # Review triggering and record creation functions
    'create_review_record',
    'trigger_phase_review',
    'get_phase_reviews',
    # MCP tool wrapper functions
    'request_phase_review',
    'submit_review',
    'get_review_status',
    'get_review_context',
]
