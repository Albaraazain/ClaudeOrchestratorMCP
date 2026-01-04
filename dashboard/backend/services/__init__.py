"""
Services module for Dashboard Backend

This module provides core services for accessing orchestrator data.
"""

from .workspace import WorkspaceService, get_workspace_service

__all__ = [
    'WorkspaceService',
    'get_workspace_service',
]