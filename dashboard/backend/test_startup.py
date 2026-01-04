#!/usr/bin/env python3
"""Test script to verify backend structure is complete."""

import sys
from pathlib import Path

# Check required files exist
required_files = [
    "main.py",
    "requirements.txt",
    "models/schemas.py",
    "api/routes/tasks.py",
    "api/routes/agents.py",
    "api/routes/phases.py",
    "api/routes/tmux.py",
    "websocket/manager.py",
    "services/workspace.py",
    "services/tmux_service.py",
    "services/watcher.py",
    "services/log_streamer.py",
]

print("=== FastAPI Backend Structure Check ===\n")

all_present = True
for file_path in required_files:
    path = Path(file_path)
    if path.exists():
        print(f"✓ {file_path}")
    else:
        print(f"✗ {file_path} - MISSING")
        all_present = False

print(f"\n=== Summary ===")
print(f"Total files checked: {len(required_files)}")
print(f"Files present: {sum(1 for f in required_files if Path(f).exists())}")

if all_present:
    print("\n✓ All required files are present!")
    print("\nTo run the server:")
    print("1. Install dependencies: pip install -r requirements.txt")
    print("2. Start server: python main.py")
    print("\nThe API will be available at:")
    print("- http://localhost:8000 (REST API)")
    print("- http://localhost:8000/docs (Interactive API docs)")
    print("- ws://localhost:8000/ws (WebSocket endpoint)")
else:
    print("\n✗ Some files are missing. Backend structure incomplete.")
    sys.exit(1)