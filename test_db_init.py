#!/usr/bin/env python3
"""Test database initialization"""

import sys
import os

# Add orchestrator to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from orchestrator import state_db

    # Test database initialization
    workspace = "/Users/albaraa/.agent-workspace"
    print(f"Initializing database in: {workspace}")

    # Delete existing empty db
    db_path = state_db.get_state_db_path(workspace)
    print(f"Database path: {db_path}")

    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"Removed existing empty database")

    # Initialize
    result = state_db.ensure_db(workspace)
    print(f"Database initialized: {result}")

    # Check file size
    if os.path.exists(db_path):
        size = os.path.getsize(db_path)
        print(f"Database size: {size} bytes")

        # Test connection
        import sqlite3
        conn = sqlite3.connect(db_path)

        # List tables
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Tables in database: {tables}")

        conn.close()
    else:
        print("ERROR: Database file not created!")

except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()