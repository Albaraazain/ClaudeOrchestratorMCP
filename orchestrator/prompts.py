"""
Agent Prompt Generation Module

Handles generation of agent prompts including:
- Type-specific requirements (investigator, builder, fixer)
- Task enrichment context formatting
- Orchestration guidance for child agent spawning
- Specialization recommendations based on task analysis

All prompt templates are centralized here for easy maintenance.
"""

from typing import Dict, List, Any
from .tasks import calculate_task_complexity


def generate_specialization_recommendations(task_description: str, current_depth: int) -> List[str]:
    """
    Dynamically recommend specialist agent types based on task context.

    Args:
        task_description: Description of the task
        current_depth: Current depth in agent hierarchy

    Returns:
        List of recommended agent type names
    """
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


def format_task_enrichment_prompt(task_registry: Dict[str, Any]) -> str:
    """
    Format task enrichment context as a prompt section for agents.
    Reads task_context from registry and returns formatted markdown or empty string.

    Args:
        task_registry: Task registry dict that may contain 'task_context' field

    Returns:
        Formatted markdown section with task context, or empty string if no enrichment
    """
    task_context = task_registry.get('task_context', {})
    if not task_context:
        return ""

    sections = []

    # Background context
    if bg := task_context.get('background_context'):
        sections.append(f"""
BACKGROUND CONTEXT:
{bg}
""")

    # Expected deliverables
    if deliverables := task_context.get('expected_deliverables'):
        items = '\n'.join(f"  - {d}" for d in deliverables)
        sections.append(f"""
EXPECTED DELIVERABLES:
{items}
""")

    # Success criteria
    if criteria := task_context.get('success_criteria'):
        items = '\n'.join(f"  - {c}" for c in criteria)
        sections.append(f"""
SUCCESS CRITERIA:
{items}
""")

    # Constraints
    if constraints := task_context.get('constraints'):
        items = '\n'.join(f"  - {c}" for c in constraints)
        sections.append(f"""
CONSTRAINTS:
{items}
""")

    # Relevant files (limit to first 10)
    if files := task_context.get('relevant_files'):
        items = '\n'.join(f"  - {f}" for f in files[:10])
        if len(files) > 10:
            items += f"\n  - ... and {len(files) - 10} more files"
        sections.append(f"""
RELEVANT FILES TO EXAMINE:
{items}
""")

    # Related documentation
    if docs := task_context.get('related_documentation'):
        items = '\n'.join(f"  - {d}" for d in docs)
        sections.append(f"""
RELATED DOCUMENTATION:
{items}
""")

    # Conversation history that led to this task
    if conv_history := task_context.get('conversation_history'):
        messages = conv_history.get('messages', [])
        truncated_count = conv_history.get('truncated_count', 0)

        if messages:
            # Format messages with numbering and role indicators
            formatted_messages = []
            for idx, msg in enumerate(messages, 1):
                role = msg['role']
                content = msg['content']
                timestamp = msg.get('timestamp', 'unknown time')
                truncated_flag = " [TRUNCATED]" if msg.get('truncated') else ""

                # Parse timestamp to human-readable format
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(timestamp)
                    time_str = dt.strftime('%H:%M:%S')
                except:
                    time_str = timestamp

                # Role indicator
                role_indicator = {
                    'user': 'User',
                    'assistant': 'Assistant',
                    'orchestrator': 'Orchestrator'
                }
                role_name = role_indicator.get(role, role.capitalize())

                formatted_messages.append(
                    f"[{idx}] {role_name} ({time_str}){truncated_flag}:\n    {content}\n"
                )

            messages_text = '\n'.join(formatted_messages)

            # Add metadata footer
            footer = f"\nHistory metadata: {len(messages)} messages"
            if truncated_count > 0:
                footer += f", {truncated_count} truncated (user messages kept concise)"

            sections.append(f"""
CONVERSATION HISTORY (Leading to This Task):

The orchestrator had the following conversation before creating this task.
This provides context for WHY this task exists and WHAT the user wants.

{messages_text}{footer}
""")

    if sections:
        return f"""
{'='*80}
TASK CONTEXT (Provided by task creator)
{'='*80}

{''.join(sections)}

{'='*80}
"""
    return ""


def create_orchestration_guidance_prompt(
    agent_type: str,
    task_description: str,
    current_depth: int,
    max_depth: int
) -> str:
    """
    Generate dynamic guidance for orchestration based on context.

    Args:
        agent_type: Type of the current agent
        task_description: Description of the task
        current_depth: Current depth in agent hierarchy
        max_depth: Maximum allowed depth

    Returns:
        Orchestration guidance prompt section
    """
    complexity = calculate_task_complexity(task_description)
    recommendations = generate_specialization_recommendations(task_description, current_depth + 1)

    if current_depth >= max_depth - 1:
        return "\nDEPTH LIMIT REACHED - Focus on implementation rather than spawning children."

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

ORCHESTRATION GUIDANCE (Depth {current_depth}/{max_depth}, Complexity: {complexity}/20):

You are {intensity} to spawn specialized child agents for better implementation quality.

RECOMMENDED CHILD SPECIALISTS:
{chr(10).join(f'- {agent}' for agent in recommendations[:6])}

ORCHESTRATION STRATEGY:
1. ANALYZE if your task benefits from specialization
2. SPAWN {child_count} with focused, specific roles
3. COORDINATE their work efficiently
4. Each child should handle a distinct domain

NAMING CONVENTION: Use clear, descriptive names:
   - 'css_responsive_specialist' not just 'css'
   - 'api_authentication_handler' not just 'auth'
   - 'database_optimization_expert' not just 'db'

SUCCESS CRITERIA: Balance specialization with efficiency:
   - Spawn specialists only when beneficial
   - Coordinate effectively without micro-management
   - Deliver comprehensive, integrated results"""

    return guidance


def get_investigator_requirements() -> str:
    """Return investigator-specific requirements enforcing Read-First Development."""
    return """
INVESTIGATOR PROTOCOL - READ-FIRST DEVELOPMENT

MANDATORY INVESTIGATION STEPS (IN ORDER):
1. CONTEXT GATHERING (30-40% of time):
   - Search codebase for existing patterns FIRST
   - Read relevant files to understand current state
   - Identify what exists vs what's missing
   - Check documentation, comments, git history
   - Map dependencies and relationships

2. PATTERN ANALYSIS (30-40% of time):
   - What patterns are used consistently?
   - What conventions must be followed?
   - What are the architectural boundaries?
   - What similar code exists that we can learn from?
   - What constraints exist (performance, compatibility)?

3. EVIDENCE COLLECTION (20-30% of time):
   - Document findings with file paths and line numbers
   - Quote relevant code sections
   - Capture metrics (file counts, complexity, coverage)
   - List gaps, issues, or inconsistencies found
   - Provide concrete examples, not generalizations

SUCCESS CRITERIA - Definition of 'DONE':
Your investigation is ONLY complete when:
- All relevant code has been READ (not assumed)
- Findings are DOCUMENTED with evidence (file paths, line numbers)
- Patterns are IDENTIFIED and EXPLAINED (not just listed)
- Gaps or issues are SPECIFIC (not vague)
- Recommendations are ACTIONABLE (not generic)

EVIDENCE REQUIRED FOR COMPLETION:
BEFORE reporting status='completed', you MUST provide:
1. Files you read - list specific paths and what you learned
2. Patterns you found - describe with code examples
3. Findings documented - use report_agent_finding for each discovery
4. Metrics collected - how many files, functions, patterns?
5. Gaps identified - what's missing or broken?
6. Recommendations - specific, actionable next steps

ANTI-PATTERNS TO AVOID:
- Assuming without reading actual code
- Generic findings without evidence
- Incomplete investigation (only surface-level)
- No concrete examples or quotes
- Vague recommendations like "needs improvement"
- Claiming done without documenting findings

VALIDATION CHECKPOINT - Answer Before Claiming Complete:

Run this self-check. If you answer 'NO' to ANY question, you are NOT done:

[ ] Did I read at least 3 relevant files? (List them: ___, ___, ___)
[ ] Can I cite specific line numbers for my findings? (Show examples: file.py:123, ...)
[ ] Did I document findings using report_agent_finding? (How many: ___)
[ ] Did I identify at least 2 alternative approaches? (List: 1.___, 2.___)
[ ] Are my findings specific enough that a builder could act on them without asking questions?
[ ] Did I check for similar patterns elsewhere in the codebase?
[ ] Would a senior engineer approve this investigation without follow-up questions?

If ANY checkbox is unchecked, CONTINUE investigating before reporting completed.
"""


def get_builder_requirements() -> str:
    """Return builder-specific requirements enforcing Quality Implementation."""
    return """
BUILDER PROTOCOL - QUALITY IMPLEMENTATION

MANDATORY BUILD STEPS (IN ORDER):
1. UNDERSTAND BEFORE CODING (30% of time):
   - Read existing code to match style and patterns
   - Identify project conventions (naming, structure, testing)
   - Check what APIs must NOT break (backward compatibility)
   - Search for similar existing implementations
   - Identify constraints: performance, security, compatibility

2. ERROR-FIRST IMPLEMENTATION (40% of time):
   - Think: What can go wrong? List failure modes FIRST
   - Implement error handling for edge cases BEFORE happy path
   - What if input is null/empty/invalid/huge?
   - What if network fails? What if dependency is unavailable?
   - Add logging for debugging future issues

3. TEST AND VERIFY (30% of time):
   - Write or update tests for new functionality
   - Test edge cases (empty, null, boundary values)
   - Run test suite - MUST pass before claiming done
   - Manual testing: actually use what you built
   - Check: did I break anything else?

SUCCESS CRITERIA - Definition of 'DONE':
Your build is ONLY complete when:
- Tests pass (show test output)
- Edge cases handled (null, empty, invalid, boundary)
- No regressions (existing functionality still works)
- Code follows project patterns (style, structure, conventions)
- Error handling is comprehensive (not just happy path)

EVIDENCE REQUIRED FOR COMPLETION:
BEFORE reporting status='completed', you MUST provide:
1. List of files you modified (with what changed)
2. Test results - show actual command output
3. Edge cases you handled - list them specifically
4. Manual testing performed - what did you test?
5. Impact analysis - what else could this affect?
6. Self-review - what's the weakest part of your implementation?

ANTI-PATTERNS TO AVOID:
- Coding before understanding existing patterns
- Implementing without error handling
- Not testing edge cases (null, empty, invalid)
- Claiming done without running tests
- Breaking existing APIs without migration path
- No logging for future debugging
- Leaving debug code or console.logs

VALIDATION CHECKPOINT - Answer Before Claiming Complete:

Run this self-check. If you answer 'NO' to ANY question, you are NOT done:

[ ] Did tests pass? (Show command output: ___)
[ ] What files did I modify? (List them: ___)
[ ] What edge cases did I handle? (Name 3 minimum: ___, ___, ___)
[ ] What breaks if input is null/empty/invalid? (Answer: ___)
[ ] Did I manually test this? (What did I test: ___)
[ ] What's the weakest part of my implementation? (Be honest: ___)
[ ] Would I approve this PR if someone else wrote it? (Yes/No with reason: ___)
[ ] Did I add error handling and logging for debugging?
[ ] Does my code follow project patterns and conventions?

If ANY checkbox is unchecked, CONTINUE building before reporting completed.
"""


def get_fixer_requirements() -> str:
    """Return fixer-specific requirements enforcing Root Cause Diagnosis."""
    return """
FIXER PROTOCOL - ROOT CAUSE DIAGNOSIS

MANDATORY DEBUGGING STEPS (IN ORDER):
1. REPRODUCE FIRST (25% of time):
   - Reproduce the bug reliably with exact steps
   - Document EXACT reproduction steps (command/input/environment)
   - If you can't reproduce it, you can't verify the fix
   - Test on clean environment: is it environmental or code?
   - Verify error message/behavior matches reported issue

2. ROOT CAUSE ANALYSIS (40% of time):
   - Identify root cause, NOT just symptoms
   - Ask: Why did this happen? Trace execution path
   - Read the actual code, don't trust error messages
   - Check git history: when was this introduced? Why?
   - Is this a regression? Was it working before?
   - What assumptions were violated?

3. FIX AND VERIFY (25% of time):
   - Fix the root cause, not the symptom
   - Verify fix addresses the actual problem
   - Test that bug no longer reproduces
   - Add regression test to prevent recurrence
   - Check: did my fix break anything else?

4. PREVENT RECURRENCE (10% of time):
   - Search for similar bugs in other code
   - Add tests for edge cases that caused this
   - Update documentation if assumptions were wrong
   - Consider: how could we have caught this earlier?

SUCCESS CRITERIA - Definition of 'DONE':
Your fix is ONLY complete when:
- Bug is reproducible (documented exact steps)
- Root cause identified (not just symptoms)
- Fix verified (bug no longer occurs)
- Regression tests added (prevents future recurrence)
- Similar issues checked (are there other instances?)

EVIDENCE REQUIRED FOR COMPLETION:
BEFORE reporting status='completed', you MUST provide:
1. Bug reproduction steps - exact commands/input
2. Root cause explanation - why did this happen?
3. Files modified to fix the issue
4. Test results - show bug fixed
5. Regression tests added - show test code
6. Similar issues checked - where did you look?

ANTI-PATTERNS TO AVOID:
- Fixing symptoms instead of root cause
- Claiming fix without reproducing bug first
- No regression tests to prevent recurrence
- Not checking for similar bugs elsewhere
- Trusting error messages without reading code
- Not verifying the fix actually works
- Breaking other functionality with the fix

VALIDATION CHECKPOINT - Answer Before Claiming Complete:

Run this self-check. If you answer 'NO' to ANY question, you are NOT done:

[ ] Can I reproduce the bug? (Show exact steps: ___)
[ ] What is the root cause? (Explain why it happens: ___)
[ ] Does my fix address root cause or just symptoms? (Which: ___)
[ ] Did I verify the bug no longer occurs? (How: ___)
[ ] What regression tests did I add? (Show test code or file: ___)
[ ] Did I check for similar bugs? (Where did I look: ___)
[ ] Could my fix break anything else? (Analyzed: ___)
[ ] Did I update documentation if assumptions were wrong? (Files: ___)

If ANY checkbox is unchecked, CONTINUE fixing before reporting completed.
"""


def get_universal_protocol() -> str:
    """
    Return universal protocol that works for ANY agent type without restriction.
    Allows fully dynamic agent types per user request for flexibility.

    The specialized protocols (investigator/builder/fixer) remain available as reference
    but are no longer enforced, enabling custom agent types like 'jwt-validator',
    'security-analyzer', etc. without forcing them into predefined buckets.
    """
    return """
AGENT PROTOCOL - SYSTEMATIC APPROACH

MISSION EXECUTION STEPS:
1. UNDERSTAND (30% of time):
   - Read relevant code/documentation to understand context
   - Identify what exists vs what needs to change
   - Check project conventions and patterns
   - Map dependencies and constraints

2. PLAN & IMPLEMENT (40% of time):
   - Break down the task into specific steps
   - Consider edge cases and error scenarios
   - Implement with proper error handling
   - Follow project coding standards

3. VERIFY & DOCUMENT (30% of time):
   - Test your changes work correctly
   - Check for regressions or side effects
   - Document findings with file:line citations
   - Provide evidence of completion

SUCCESS CRITERIA - Definition of 'DONE':
Your work is ONLY complete when:
- Task requirements fully addressed (not partial)
- Changes tested and verified working
- Evidence provided (file paths, test results, findings)
- No regressions introduced
- Work follows project patterns and conventions

EVIDENCE REQUIRED FOR COMPLETION:
BEFORE reporting status='completed', you MUST provide:
1. What you accomplished - specific changes made
2. Files modified - list paths with what changed
3. Testing performed - show results/output
4. Findings documented - use report_agent_finding for discoveries
5. Quality check - did you verify it works?

ANTI-PATTERNS TO AVOID:
- Assuming without reading actual code
- Generic findings without specific evidence
- Claiming done without testing/verification
- Breaking existing functionality
- No file:line citations for your findings

FORCED SELF-INTERROGATION CHECKLIST:
Answer BEFORE claiming done:
1. Did I READ the relevant code or assume?
2. Can I cite specific files/lines I analyzed or modified?
3. Did I TEST my changes work?
4. Did I document findings with evidence?
5. What could go wrong? Did I handle edge cases?
6. Would I accept this work quality from someone else?
"""


def get_type_specific_requirements(agent_type: str) -> str:
    """
    Get type-specific requirements for agent based on type.

    Now fully dynamic - accepts ANY agent_type string without restriction.
    Specialized protocols (investigator/builder/fixer) kept for reference
    but no longer enforced, allowing custom types like 'jwt-validator',
    'security-analyzer', 'performance-optimizer', etc.

    Args:
        agent_type: Type of agent - ANY string accepted

    Returns:
        Protocol string for the agent type
    """
    # Check if user wants a specific specialized protocol (optional)
    # Otherwise, return universal protocol that works for any type
    type_specific_protocols = {
        'investigator': get_investigator_requirements,
        'builder': get_builder_requirements,
        'fixer': get_fixer_requirements,
    }

    # If agent_type exactly matches a specialized protocol, use it
    # Otherwise use universal protocol (allows ANY custom type)
    if agent_type.lower() in type_specific_protocols:
        return type_specific_protocols[agent_type.lower()]()
    else:
        # Universal protocol works for ANY agent type - fully dynamic
        return get_universal_protocol()


__all__ = [
    'generate_specialization_recommendations',
    'format_task_enrichment_prompt',
    'create_orchestration_guidance_prompt',
    'get_investigator_requirements',
    'get_builder_requirements',
    'get_fixer_requirements',
    'get_universal_protocol',
    'get_type_specific_requirements',
]
