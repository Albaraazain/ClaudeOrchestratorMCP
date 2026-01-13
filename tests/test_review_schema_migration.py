import os
import sqlite3


def test_reviews_table_migrates_missing_reviewer_columns(tmp_path):
    """
    Regression test for older workspaces whose `reviews` table predates:
      - reviewer_agent_ids
      - critique_agent_id

    The MCP tool `get_review_status` queries those columns via
    `state_db.get_reviews_for_task`, so the schema must be auto-upgraded.
    """
    from orchestrator import state_db

    workspace_base = str(tmp_path)
    registry_dir = os.path.join(workspace_base, "registry")
    os.makedirs(registry_dir, exist_ok=True)
    db_path = os.path.join(registry_dir, "state.sqlite3")

    # Simulate an older schema where `reviews` exists but is missing the newer columns.
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys=ON;

            CREATE TABLE IF NOT EXISTS tasks (
              task_id TEXT PRIMARY KEY,
              workspace TEXT,
              workspace_base TEXT,
              description TEXT,
              status TEXT,
              priority TEXT,
              client_cwd TEXT,
              created_at TEXT,
              updated_at TEXT,
              current_phase_index INTEGER
            );

            CREATE TABLE IF NOT EXISTS reviews (
              review_id TEXT PRIMARY KEY,
              task_id TEXT NOT NULL,
              phase_index INTEGER NOT NULL,
              status TEXT,
              verdict TEXT,
              created_at TEXT,
              completed_at TEXT,
              reviewer_notes TEXT,
              num_reviewers INTEGER DEFAULT 2,
              auto_spawned INTEGER DEFAULT 0,
              phase_name TEXT,
              FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            "INSERT INTO tasks(task_id, workspace, workspace_base, description, status, created_at, updated_at, current_phase_index) VALUES(?,?,?,?,?,?,?,?)",
            ("TASK-OLD-REVIEWS", "/tmp/task", workspace_base, "desc", "ACTIVE", "2026-01-13T00:00:00", "2026-01-13T00:00:00", 0),
        )
        conn.execute(
            "INSERT INTO reviews(review_id, task_id, phase_index, status, verdict, created_at) VALUES(?,?,?,?,?,?)",
            ("review-1", "TASK-OLD-REVIEWS", 0, "in_progress", None, "2026-01-13T00:00:00"),
        )
        conn.commit()
    finally:
        conn.close()

    # Run auto-migrations.
    state_db.ensure_db(workspace_base)

    # Verify schema upgraded.
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(reviews)").fetchall()}
    finally:
        conn.close()

    assert "reviewer_agent_ids" in cols
    assert "critique_agent_id" in cols

    # Verify read path doesn't crash and normalizes `reviewer_agent_ids` to a list.
    reviews = state_db.get_reviews_for_task(workspace_base=workspace_base, task_id="TASK-OLD-REVIEWS")
    assert len(reviews) == 1
    assert reviews[0]["review_id"] == "review-1"
    assert reviews[0]["reviewer_agent_ids"] == []

