"""FastAPI backend server for Claude Orchestrator Dashboard."""

import time
import sys
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add orchestrator to path for imports
orchestrator_path = Path(__file__).parent.parent.parent
sys.path.insert(0, str(orchestrator_path))

# Import routers (conditionally to avoid errors if not all created yet)
try:
    from api.routes import tasks, agents, phases, tmux
except ImportError as e:
    print(f"[Warning] Some route modules not found yet: {e}")
    tasks = agents = phases = tmux = None

# Import WebSocket components
from api.websocket import connection_manager, websocket_route

# Import schemas if available
try:
    from models.schemas import HealthResponse
except ImportError:
    HealthResponse = None

# Server start time for health check
server_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    print("[Dashboard API] Starting FastAPI server...")
    print(f"[Dashboard API] Orchestrator path: {orchestrator_path}")

    # Initialize any required services here
    yield

    # Shutdown
    print("[Dashboard API] Shutting down FastAPI server...")
    # Broadcast shutdown to all connected clients
    await connection_manager.broadcast({
        "type": "server_shutdown",
        "message": "Server is shutting down"
    })


# Create FastAPI app
app = FastAPI(
    title="Claude Orchestrator Dashboard API",
    description="REST API and WebSocket server for Claude Orchestrator Dashboard",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include routers (if available)
if tasks:
    app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
if agents:
    app.include_router(agents.router, prefix="/api/agents", tags=["agents"])
if phases:
    app.include_router(phases.router, prefix="/api/phases", tags=["phases"])
if tmux:
    app.include_router(tmux.router, prefix="/api/tmux", tags=["tmux"])


@app.get("/health", tags=["health"])
async def health_check():
    """Health check endpoint."""
    if HealthResponse:
        return HealthResponse(
            status="healthy",
            version="1.0.0",
            uptime=time.time() - server_start_time,
            timestamp=datetime.now()
        )
    else:
        return {
            "status": "healthy",
            "version": "1.0.0",
            "uptime": time.time() - server_start_time,
            "timestamp": datetime.now().isoformat()
        }


@app.get("/", tags=["root"])
async def root():
    """Root endpoint."""
    return {
        "message": "Claude Orchestrator Dashboard API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "websocket": "/ws"
    }


@app.get("/api/stats", tags=["monitoring"])
async def get_stats():
    """Get WebSocket connection statistics."""
    return {
        "websocket_connections": connection_manager.get_connection_stats(),
        "server_uptime": time.time() - server_start_time
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Main WebSocket endpoint for real-time updates.

    Uses the enhanced WebSocket manager with subscription management.
    """
    await websocket_route(websocket)


@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Custom 404 handler."""
    return JSONResponse(
        status_code=404,
        content={"detail": "Resource not found"}
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Custom 500 handler."""
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"}
    )


if __name__ == "__main__":
    import uvicorn

    # Run server
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )