"""
Project Context Detection Module

Handles automatic detection of project language, frameworks, testing tools,
and patterns to provide context-aware agent prompts.

Functions:
- parse_markdown_context: Parse markdown files for project info
- detect_project_context: Detect project details from config files
- format_project_context_prompt: Format context as agent prompt section
"""

import os
import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# Project context detection cache
_project_context_cache: Dict[str, Dict[str, Any]] = {}


def parse_markdown_context(content: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse markdown content to extract language, framework, and testing information.

    Args:
        content: Markdown file content
        context: Existing context dict to update

    Returns:
        Updated context dict with extracted information
    """
    content_lower = content.lower()

    # Language detection - search for explicit mentions
    language_keywords = {
        'python': ['python', 'py', 'pip', 'pyproject', 'virtualenv', 'venv'],
        'javascript': ['javascript', 'js', 'node.js', 'nodejs', 'npm'],
        'typescript': ['typescript', 'ts', 'tsc'],
        'go': ['golang', 'go ', ' go'],
        'rust': ['rust', 'cargo', 'rustc'],
        'java': ['java', 'jvm', 'maven', 'gradle'],
        'ruby': ['ruby', 'gem', 'bundler'],
        'php': ['php', 'composer'],
        'c++': ['c++', 'cpp', 'cmake'],
        'c#': ['c#', 'csharp', '.net', 'dotnet']
    }

    for lang, keywords in language_keywords.items():
        if any(kw in content_lower for kw in keywords):
            context['language'] = lang.title() if lang != 'c++' else 'C++'
            if lang == 'typescript':
                context['language'] = 'TypeScript'
            elif lang == 'javascript':
                context['language'] = 'JavaScript'
            break

    # Framework detection
    framework_keywords = {
        'FastMCP': ['fastmcp', 'fast mcp', 'mcp server'],
        'Django': ['django'],
        'Flask': ['flask'],
        'FastAPI': ['fastapi', 'fast api'],
        'React': ['react', 'reactjs'],
        'Vue': ['vue', 'vuejs', 'vue.js'],
        'Angular': ['angular'],
        'Next.js': ['next.js', 'nextjs'],
        'Express': ['express', 'expressjs'],
        'Svelte': ['svelte'],
        'Spring': ['spring boot', 'spring framework'],
        'Rails': ['rails', 'ruby on rails']
    }

    for framework, keywords in framework_keywords.items():
        if any(kw in content_lower for kw in keywords):
            if framework not in context['frameworks']:
                context['frameworks'].append(framework)

    # Testing framework detection
    testing_keywords = {
        'pytest': ['pytest'],
        'unittest': ['unittest'],
        'jest': ['jest'],
        'mocha': ['mocha'],
        'vitest': ['vitest'],
        'playwright': ['playwright'],
        'cypress': ['cypress'],
        'go test': ['go test', 'testing package'],
        'cargo test': ['cargo test'],
        'junit': ['junit']
    }

    for test_fw, keywords in testing_keywords.items():
        if any(kw in content_lower for kw in keywords):
            if not context['testing_framework']:
                context['testing_framework'] = test_fw
            break

    # Package manager detection
    pm_keywords = {
        'pip': ['pip', 'pypi'],
        'npm': ['npm'],
        'yarn': ['yarn'],
        'pnpm': ['pnpm'],
        'cargo': ['cargo'],
        'go mod': ['go mod', 'go modules'],
        'maven': ['maven'],
        'gradle': ['gradle']
    }

    for pm, keywords in pm_keywords.items():
        if any(kw in content_lower for kw in keywords):
            if not context['package_manager']:
                context['package_manager'] = pm
            break

    # Project type inference
    if 'mcp' in content_lower or 'fastmcp' in content_lower:
        context['project_type'] = 'mcp_server'
    elif any(fw in content_lower for fw in ['django', 'flask', 'fastapi', 'express', 'rails', 'spring']):
        context['project_type'] = 'web_application'
    elif any(fw in content_lower for fw in ['react', 'vue', 'angular', 'svelte', 'next']):
        context['project_type'] = 'web_application'

    return context


def detect_project_context(project_dir: str) -> Dict[str, Any]:
    """
    Detect project language, frameworks, testing tools, and patterns.
    Prioritizes human-curated markdown files over config file scanning.

    Priority order:
    1. .claude/CLAUDE.md (project-specific)
    2. project_context.md (project root)
    3. Config files (pyproject.toml, package.json, go.mod, etc.) as fallback

    Fast detection (<500ms) with graceful error handling.

    Args:
        project_dir: Path to project directory

    Returns:
        Context dict with language, frameworks, testing, etc.
    """
    cache_key = os.path.abspath(project_dir)
    if cache_key in _project_context_cache:
        return _project_context_cache[cache_key]

    context = {
        'language': 'Unknown',
        'frameworks': [],
        'testing_framework': None,
        'package_manager': None,
        'project_type': 'unknown',
        'config_files_found': [],
        'confidence': 'low',
        'source': 'none'
    }

    # PRIORITY 1: Check .claude/CLAUDE.md (relative to project_dir)
    claude_md_path = os.path.join(project_dir, '.claude', 'CLAUDE.md')
    if os.path.exists(claude_md_path):
        try:
            with open(claude_md_path, 'r', encoding='utf-8') as f:
                content = f.read()
                context = parse_markdown_context(content, context)
                context['source'] = '.claude/CLAUDE.md'
                context['confidence'] = 'high'
                context['config_files_found'].append('.claude/CLAUDE.md')
                _project_context_cache[cache_key] = context
                return context
        except Exception as e:
            logger.warning(f"Error reading .claude/CLAUDE.md: {e}")

    # PRIORITY 2: Check project_context.md (project root)
    project_md_path = os.path.join(project_dir, 'project_context.md')
    if os.path.exists(project_md_path):
        try:
            with open(project_md_path, 'r', encoding='utf-8') as f:
                content = f.read()
                context = parse_markdown_context(content, context)
                context['source'] = 'project_context.md'
                context['confidence'] = 'high'
                context['config_files_found'].append('project_context.md')
                _project_context_cache[cache_key] = context
                return context
        except Exception as e:
            logger.warning(f"Error reading project_context.md: {e}")

    # FALLBACK: Use config file scanning
    try:
        # Python detection
        pyproject_path = os.path.join(project_dir, 'pyproject.toml')
        if os.path.exists(pyproject_path):
            context['language'] = 'Python'
            context['config_files_found'].append('pyproject.toml')
            try:
                with open(pyproject_path, 'r') as f:
                    content = f.read().lower()
                    if 'fastmcp' in content:
                        context['frameworks'].append('FastMCP')
                        context['project_type'] = 'mcp_server'
                    if 'django' in content:
                        context['frameworks'].append('Django')
                        context['project_type'] = 'web_application'
                    if 'flask' in content:
                        context['frameworks'].append('Flask')
                        context['project_type'] = 'web_application'
                    if 'fastapi' in content:
                        context['frameworks'].append('FastAPI')
                        context['project_type'] = 'web_application'
                    if 'pytest' in content:
                        context['testing_framework'] = 'pytest'
                    if 'unittest' in content and not context['testing_framework']:
                        context['testing_framework'] = 'unittest'
                    context['package_manager'] = 'pip'
                    context['confidence'] = 'high'
            except Exception:
                pass

        requirements_path = os.path.join(project_dir, 'requirements.txt')
        if os.path.exists(requirements_path) and context['language'] == 'Unknown':
            context['language'] = 'Python'
            context['config_files_found'].append('requirements.txt')
            context['package_manager'] = 'pip'
            context['confidence'] = 'medium'
            try:
                with open(requirements_path, 'r') as f:
                    content = f.read().lower()
                    if 'fastmcp' in content:
                        context['frameworks'].append('FastMCP')
                        context['project_type'] = 'mcp_server'
                    if 'django' in content:
                        context['frameworks'].append('Django')
                        context['project_type'] = 'web_application'
                    if 'flask' in content:
                        context['frameworks'].append('Flask')
                        context['project_type'] = 'web_application'
                    if 'pytest' in content:
                        context['testing_framework'] = 'pytest'
            except Exception:
                pass

        # JavaScript/TypeScript detection
        package_json_path = os.path.join(project_dir, 'package.json')
        if os.path.exists(package_json_path):
            context['language'] = 'JavaScript'
            context['config_files_found'].append('package.json')
            try:
                with open(package_json_path, 'r') as f:
                    pkg_data = json.load(f)
                    deps = {**pkg_data.get('dependencies', {}), **pkg_data.get('devDependencies', {})}

                    if 'react' in deps:
                        context['frameworks'].append('React')
                        context['project_type'] = 'web_application'
                    if 'vue' in deps:
                        context['frameworks'].append('Vue')
                        context['project_type'] = 'web_application'
                    if 'angular' in deps or '@angular/core' in deps:
                        context['frameworks'].append('Angular')
                        context['project_type'] = 'web_application'
                    if 'next' in deps:
                        context['frameworks'].append('Next.js')
                        context['project_type'] = 'web_application'
                    if 'express' in deps:
                        context['frameworks'].append('Express')
                        context['project_type'] = 'web_application'
                    if 'jest' in deps:
                        context['testing_framework'] = 'jest'
                    if 'mocha' in deps and not context['testing_framework']:
                        context['testing_framework'] = 'mocha'
                    if 'playwright' in deps:
                        if not context['testing_framework']:
                            context['testing_framework'] = 'playwright'
                        context['frameworks'].append('Playwright')

                    # Check for lock files
                    if os.path.exists(os.path.join(project_dir, 'package-lock.json')):
                        context['package_manager'] = 'npm'
                    elif os.path.exists(os.path.join(project_dir, 'yarn.lock')):
                        context['package_manager'] = 'yarn'
                    elif os.path.exists(os.path.join(project_dir, 'pnpm-lock.yaml')):
                        context['package_manager'] = 'pnpm'
                    else:
                        context['package_manager'] = 'npm'

                    context['confidence'] = 'high'
            except Exception:
                context['package_manager'] = 'npm'
                context['confidence'] = 'low'

        tsconfig_path = os.path.join(project_dir, 'tsconfig.json')
        if os.path.exists(tsconfig_path) and context['language'] == 'JavaScript':
            context['language'] = 'TypeScript'
            context['config_files_found'].append('tsconfig.json')

        # Go detection
        go_mod_path = os.path.join(project_dir, 'go.mod')
        if os.path.exists(go_mod_path):
            context['language'] = 'Go'
            context['config_files_found'].append('go.mod')
            context['package_manager'] = 'go mod'
            context['testing_framework'] = 'go test'
            context['confidence'] = 'high'

        # Rust detection
        cargo_path = os.path.join(project_dir, 'Cargo.toml')
        if os.path.exists(cargo_path):
            context['language'] = 'Rust'
            context['config_files_found'].append('Cargo.toml')
            context['package_manager'] = 'cargo'
            context['testing_framework'] = 'cargo test'
            context['confidence'] = 'high'

    except Exception as e:
        logger.warning(f"Error detecting project context: {e}")

    # Set source for config file fallback
    if context['source'] == 'none' and context['config_files_found']:
        context['source'] = 'config_files'

    # Cache and return
    _project_context_cache[cache_key] = context
    return context


def format_project_context_prompt(context: Dict[str, Any]) -> str:
    """
    Format detected project context as a prompt section with implications and constraints.

    Args:
        context: Project context dict from detect_project_context

    Returns:
        Formatted prompt section string
    """
    if context['language'] == 'Unknown' or context['confidence'] == 'low':
        return """
PROJECT CONTEXT:
Unable to auto-detect project details. Search for config files (package.json, pyproject.toml, go.mod, etc.) to understand project structure, language, and frameworks before proceeding.
"""

    frameworks_str = ', '.join(context['frameworks']) if context['frameworks'] else 'None detected'
    testing_str = context['testing_framework'] or 'Not detected'
    pm_str = context['package_manager'] or 'Not detected'

    source_str = context.get('source', 'unknown')
    prompt = f"""
PROJECT CONTEXT (Source: {source_str}):
- Language: {context['language']}
- Frameworks: {frameworks_str}
- Testing: {testing_str}
- Package Manager: {pm_str}
- Project Type: {context['project_type']}
- Config Files: {', '.join(context['config_files_found'])}
"""

    # Add language-specific implications
    if context['language'] == 'Python':
        prompt += """
IMPLICATIONS FOR YOUR WORK:
- Use snake_case for functions and variables
- Follow PEP 8 style guidelines
- Check pyproject.toml or requirements.txt for dependencies before importing
- Write async functions if the project uses async/await patterns
"""
        if 'FastMCP' in context['frameworks']:
            prompt += """- Follow FastMCP conventions: @mcp.tool decorator for tools
- Use .fn attribute when calling MCP tools from within other MCP tools
"""
        if context['testing_framework'] == 'pytest':
            prompt += """- Add tests in tests/ directory with test_*.py naming
- Use pytest fixtures and assertions
"""
        prompt += """
DO NOT:
- Use camelCase (this is Python, not JavaScript)
- Import libraries not in requirements.txt/pyproject.toml
- Write synchronous code if async patterns are used
"""

    elif context['language'] in ['JavaScript', 'TypeScript']:
        prompt += """
IMPLICATIONS FOR YOUR WORK:
- Use camelCase for variables and functions
- Follow modern ES6+ syntax
- Check package.json for dependencies before importing
"""
        if context['testing_framework'] == 'jest':
            prompt += """- Write tests with .test.js or .spec.js suffix
- Use Jest assertions and mocking
"""
        elif context['testing_framework'] == 'playwright':
            prompt += """- Write browser automation tests using Playwright
- Follow page object model patterns
"""
        prompt += """
DO NOT:
- Use snake_case (this is JavaScript, not Python)
- Import packages not in package.json
- Use outdated var declarations (use const/let)
"""

    elif context['language'] == 'Go':
        prompt += """
IMPLICATIONS FOR YOUR WORK:
- Use Go naming conventions (exported names start with capital letter)
- Handle errors explicitly (if err != nil pattern)
- Write tests in *_test.go files
- Use go fmt for formatting

DO NOT:
- Ignore error returns
- Use try/catch (Go uses error returns)
- Import packages without go.mod entry
"""

    elif context['language'] == 'Rust':
        prompt += """
IMPLICATIONS FOR YOUR WORK:
- Use snake_case for functions and variables
- Handle Result and Option types properly
- Write tests with #[test] attribute
- Use cargo fmt for formatting

DO NOT:
- Use unwrap() without good reason (handle errors properly)
- Ignore compiler warnings
- Import crates not in Cargo.toml
"""

    return prompt


def clear_context_cache() -> None:
    """Clear the project context cache."""
    global _project_context_cache
    _project_context_cache = {}


__all__ = [
    'parse_markdown_context',
    'detect_project_context',
    'format_project_context_prompt',
    'clear_context_cache',
]
