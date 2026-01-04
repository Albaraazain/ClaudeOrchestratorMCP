"""
tmux integration service for agent session management.

This service provides secure, controlled access to tmux sessions
for monitoring and managing Claude agents. It implements the
read-only approach (Option C) from tmux_integration.md with
security hardening.
"""

import re
import subprocess
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

# Security pattern for validating agent session names
AGENT_SESSION_PATTERN = re.compile(r'^agent_[a-zA-Z0-9_-]+$')

# Maximum output lines to prevent memory exhaustion
MAX_OUTPUT_LINES = 10000


@dataclass
class TmuxSession:
    """Data class representing a tmux session."""
    name: str
    session_id: str
    created_at: datetime
    pid: Optional[int] = None
    current_path: Optional[str] = None


class TmuxService:
    """Service for managing tmux sessions for agent monitoring."""

    def __init__(self):
        """Initialize the tmux service."""
        self._validate_tmux_available()

    def _validate_tmux_available(self) -> None:
        """Check if tmux is available on the system."""
        try:
            result = subprocess.run(
                ['which', 'tmux'],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                raise RuntimeError("tmux is not installed on this system")
            logger.info("tmux is available")
        except Exception as e:
            logger.error(f"Failed to validate tmux availability: {e}")
            raise

    def _validate_session_name(self, session_name: str) -> None:
        """
        Validate session name to prevent command injection.

        Args:
            session_name: The tmux session name to validate

        Raises:
            ValueError: If session name is invalid or potentially malicious
        """
        if not session_name:
            raise ValueError("Session name cannot be empty")

        if not AGENT_SESSION_PATTERN.match(session_name):
            raise ValueError(
                f"Invalid session name: {session_name}. "
                f"Must match pattern: agent_[alphanumeric-_]"
            )

        # Additional length check to prevent buffer overflow attempts
        if len(session_name) > 100:
            raise ValueError("Session name too long (max 100 characters)")

    def list_sessions(self) -> List[TmuxSession]:
        """
        List all agent tmux sessions with metadata.

        Returns:
            List of TmuxSession objects containing session information
        """
        try:
            # Get session list with metadata
            result = subprocess.run(
                ['tmux', 'list-sessions', '-F',
                 '#{session_name}:#{session_id}:#{session_created}'],
                capture_output=True,
                text=True,
                check=False
            )

            if result.returncode != 0:
                if "no server running" in result.stderr:
                    logger.info("No tmux server running")
                    return []
                logger.warning(f"tmux list-sessions failed: {result.stderr}")
                return []

            sessions = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue

                parts = line.split(':')
                if len(parts) >= 3:
                    session_name = parts[0]

                    # Only include agent sessions for security
                    if not session_name.startswith('agent_'):
                        continue

                    try:
                        session = TmuxSession(
                            name=session_name,
                            session_id=parts[1],
                            created_at=datetime.fromtimestamp(int(parts[2]))
                        )

                        # Get PID for the session
                        pid = self.get_session_pids(session_name)
                        if pid:
                            session.pid = pid[0] if pid else None

                        sessions.append(session)
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Failed to parse session line '{line}': {e}")

            logger.info(f"Found {len(sessions)} agent sessions")
            return sessions

        except Exception as e:
            logger.error(f"Failed to list tmux sessions: {e}")
            return []

    def get_session_output(self, session_name: str, lines: int = 100) -> str:
        """
        Capture output from a tmux session pane.

        Args:
            session_name: Name of the tmux session
            lines: Number of lines to capture (default 100, max 10000)

        Returns:
            Captured output as string

        Raises:
            ValueError: If session name is invalid
            RuntimeError: If capture fails
        """
        self._validate_session_name(session_name)

        # Enforce maximum line limit
        lines = min(lines, MAX_OUTPUT_LINES)

        try:
            result = subprocess.run(
                ['tmux', 'capture-pane', '-t', session_name, '-p', '-S', f'-{lines}'],
                capture_output=True,
                text=True,
                check=False,
                timeout=5  # Prevent hanging
            )

            if result.returncode != 0:
                if "session not found" in result.stderr:
                    raise ValueError(f"Session {session_name} not found")
                raise RuntimeError(f"Failed to capture pane: {result.stderr}")

            output = result.stdout

            # Log capture stats for monitoring
            line_count = len(output.split('\n'))
            logger.debug(f"Captured {line_count} lines from {session_name}")

            return output

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout capturing output from {session_name}")
            raise RuntimeError("Operation timed out")
        except Exception as e:
            logger.error(f"Failed to capture output from {session_name}: {e}")
            raise

    def get_session_pids(self, session_name: str) -> List[int]:
        """
        Get process PIDs for a tmux session.

        Args:
            session_name: Name of the tmux session

        Returns:
            List of process PIDs in the session

        Raises:
            ValueError: If session name is invalid
        """
        self._validate_session_name(session_name)

        try:
            result = subprocess.run(
                ['tmux', 'list-panes', '-t', session_name, '-F', '#{pane_pid}'],
                capture_output=True,
                text=True,
                check=False,
                timeout=5
            )

            if result.returncode != 0:
                logger.warning(f"Failed to get PIDs for {session_name}: {result.stderr}")
                return []

            pids = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    try:
                        pids.append(int(line))
                    except ValueError:
                        logger.warning(f"Invalid PID value: {line}")

            return pids

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout getting PIDs for {session_name}")
            return []
        except Exception as e:
            logger.error(f"Failed to get PIDs for {session_name}: {e}")
            return []

    def kill_session(self, session_name: str) -> bool:
        """
        Kill a tmux session.

        Args:
            session_name: Name of the tmux session to kill

        Returns:
            True if successful, False otherwise

        Raises:
            ValueError: If session name is invalid
        """
        self._validate_session_name(session_name)

        try:
            # Log the kill attempt for audit trail
            logger.warning(f"Attempting to kill tmux session: {session_name}")

            result = subprocess.run(
                ['tmux', 'kill-session', '-t', session_name],
                capture_output=True,
                text=True,
                check=False,
                timeout=5
            )

            if result.returncode == 0:
                logger.info(f"Successfully killed session: {session_name}")
                return True
            else:
                if "session not found" in result.stderr:
                    logger.info(f"Session {session_name} not found (already dead?)")
                    return True  # Consider it successful if already gone
                logger.error(f"Failed to kill session {session_name}: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout killing session {session_name}")
            return False
        except Exception as e:
            logger.error(f"Failed to kill session {session_name}: {e}")
            return False

    def check_session_exists(self, session_name: str) -> bool:
        """
        Check if a tmux session exists.

        Args:
            session_name: Name of the tmux session

        Returns:
            True if session exists, False otherwise

        Raises:
            ValueError: If session name is invalid
        """
        self._validate_session_name(session_name)

        try:
            result = subprocess.run(
                ['tmux', 'has-session', '-t', session_name],
                capture_output=True,
                text=True,
                check=False,
                timeout=2
            )

            exists = result.returncode == 0
            logger.debug(f"Session {session_name} exists: {exists}")
            return exists

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout checking session {session_name}")
            return False
        except Exception as e:
            logger.error(f"Failed to check session {session_name}: {e}")
            return False

    def get_session_info(self, session_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a tmux session.

        Args:
            session_name: Name of the tmux session

        Returns:
            Dictionary with session details or None if not found
        """
        self._validate_session_name(session_name)

        if not self.check_session_exists(session_name):
            return None

        try:
            # Get comprehensive session info
            result = subprocess.run(
                ['tmux', 'list-sessions', '-t', session_name, '-F',
                 '#{session_name}:#{session_id}:#{session_created}:'
                 '#{session_windows}:#{session_attached}'],
                capture_output=True,
                text=True,
                check=False,
                timeout=5
            )

            if result.returncode != 0:
                logger.warning(f"Failed to get info for {session_name}")
                return None

            parts = result.stdout.strip().split(':')
            if len(parts) >= 5:
                pids = self.get_session_pids(session_name)

                return {
                    'name': parts[0],
                    'session_id': parts[1],
                    'created_at': datetime.fromtimestamp(int(parts[2])).isoformat(),
                    'windows': int(parts[3]),
                    'attached': int(parts[4]) > 0,
                    'pids': pids,
                    'alive': len(pids) > 0
                }

            return None

        except Exception as e:
            logger.error(f"Failed to get session info for {session_name}: {e}")
            return None


# Singleton instance for the service
_tmux_service: Optional[TmuxService] = None


def get_tmux_service() -> TmuxService:
    """Get the singleton tmux service instance."""
    global _tmux_service
    if _tmux_service is None:
        _tmux_service = TmuxService()
    return _tmux_service