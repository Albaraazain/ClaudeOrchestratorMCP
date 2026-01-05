"""
FastAPI routes for tmux session management.

Provides REST endpoints for listing, monitoring, and controlling
agent tmux sessions with proper security validation.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any, Optional
import logging

from services.tmux_service import get_tmux_service, TmuxSession

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["tmux"],
    responses={
        404: {"description": "Session not found"},
        500: {"description": "Internal server error"}
    }
)


@router.get("/sessions", response_model=List[Dict[str, Any]])
async def list_tmux_sessions() -> List[Dict[str, Any]]:
    """
    List all agent tmux sessions.

    Returns a list of active tmux sessions for agents, including:
    - Session name
    - Session ID
    - Creation timestamp
    - Process PIDs
    - Session status
    """
    try:
        service = get_tmux_service()
        sessions = service.list_sessions()

        # Convert to dict format for API response
        return [
            {
                "name": session.name,
                "session_id": session.session_id,
                "created_at": session.created_at.isoformat(),
                "pid": session.pid,
                "agent_id": session.name.replace("agent_", "") if session.name.startswith("agent_") else None,
                "status": "active" if session.pid else "unknown"
            }
            for session in sessions
        ]

    except Exception as e:
        logger.error(f"Failed to list tmux sessions: {e}")
        raise HTTPException(status_code=500, detail="Failed to list tmux sessions")


@router.get("/sessions/{session_name}", response_model=Dict[str, Any])
async def get_session_info(session_name: str) -> Dict[str, Any]:
    """
    Get detailed information about a specific tmux session.

    Args:
        session_name: Name of the tmux session (e.g., agent_xyz)

    Returns:
        Detailed session information including PIDs, creation time, and status
    """
    try:
        service = get_tmux_service()

        # Validate session name
        if not session_name.startswith("agent_"):
            raise HTTPException(
                status_code=400,
                detail="Invalid session name. Must start with 'agent_'"
            )

        info = service.get_session_info(session_name)

        if not info:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{session_name}' not found"
            )

        return info

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Invalid session name: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get session info: {e}")
        raise HTTPException(status_code=500, detail="Failed to get session information")


@router.get("/sessions/{session_name}/output")
async def get_session_output(
    session_name: str,
    lines: int = Query(100, ge=1, le=10000, description="Number of lines to capture")
) -> Dict[str, Any]:
    """
    Get output from a tmux session pane.

    Args:
        session_name: Name of the tmux session
        lines: Number of lines to capture (1-10000, default 100)

    Returns:
        Dictionary containing the captured output and metadata
    """
    try:
        service = get_tmux_service()

        # Validate session name
        if not session_name.startswith("agent_"):
            raise HTTPException(
                status_code=400,
                detail="Invalid session name. Must start with 'agent_'"
            )

        # Check if session exists
        if not service.check_session_exists(session_name):
            raise HTTPException(
                status_code=404,
                detail=f"Session '{session_name}' not found"
            )

        # Capture output
        output = service.get_session_output(session_name, lines)

        # Return structured response
        return {
            "session_name": session_name,
            "lines_requested": lines,
            "output": output,
            "line_count": len(output.split('\n')),
            "agent_id": session_name.replace("agent_", "") if session_name.startswith("agent_") else None
        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Invalid request: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error(f"Runtime error capturing output: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to get session output: {e}")
        raise HTTPException(status_code=500, detail="Failed to capture session output")


@router.delete("/sessions/{session_name}")
async def kill_tmux_session(session_name: str) -> Dict[str, Any]:
    """
    Terminate a tmux session.

    This is a destructive operation that will kill the agent process.
    Use with caution. Requires proper authorization in production.

    Args:
        session_name: Name of the tmux session to kill

    Returns:
        Status of the kill operation
    """
    try:
        service = get_tmux_service()

        # Validate session name
        if not session_name.startswith("agent_"):
            raise HTTPException(
                status_code=400,
                detail="Invalid session name. Must start with 'agent_'"
            )

        # Check if session exists
        if not service.check_session_exists(session_name):
            # Already gone, consider it successful
            return {
                "session_name": session_name,
                "status": "success",
                "message": "Session already terminated"
            }

        # Kill the session
        success = service.kill_session(session_name)

        if success:
            logger.info(f"Successfully killed tmux session: {session_name}")
            return {
                "session_name": session_name,
                "status": "success",
                "message": "Session terminated successfully"
            }
        else:
            logger.error(f"Failed to kill tmux session: {session_name}")
            raise HTTPException(
                status_code=500,
                detail="Failed to terminate session"
            )

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Invalid session name: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to kill session: {e}")
        raise HTTPException(status_code=500, detail="Failed to terminate session")


@router.get("/sessions/{session_name}/exists")
async def check_session_exists(session_name: str) -> Dict[str, bool]:
    """
    Check if a tmux session exists.

    Args:
        session_name: Name of the tmux session

    Returns:
        Dictionary with exists status
    """
    try:
        service = get_tmux_service()

        # Validate session name
        if not session_name.startswith("agent_"):
            raise HTTPException(
                status_code=400,
                detail="Invalid session name. Must start with 'agent_'"
            )

        exists = service.check_session_exists(session_name)

        return {
            "session_name": session_name,
            "exists": exists
        }

    except HTTPException:
        raise
    except ValueError as e:
        logger.warning(f"Invalid session name: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to check session: {e}")
        raise HTTPException(status_code=500, detail="Failed to check session existence")


@router.get("/health")
async def tmux_health_check() -> Dict[str, Any]:
    """
    Health check for tmux service.

    Verifies that tmux is available and can list sessions.
    """
    try:
        service = get_tmux_service()
        sessions = service.list_sessions()

        return {
            "status": "healthy",
            "tmux_available": True,
            "active_sessions": len(sessions),
            "message": "tmux service is operational"
        }

    except Exception as e:
        logger.error(f"tmux health check failed: {e}")
        return {
            "status": "unhealthy",
            "tmux_available": False,
            "active_sessions": 0,
            "message": str(e)
        }