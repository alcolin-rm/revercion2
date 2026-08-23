import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from config import Settings

DB_PATH = Path(Settings.data_dir) / "jobs.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        playlist_id TEXT NOT NULL,
        playlist_title TEXT,
        status TEXT NOT NULL,
        total_tracks INTEGER DEFAULT 0,
        completed INTEGER DEFAULT 0,
        failed INTEGER DEFAULT 0,
        skipped INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        log_path TEXT,
        input_csv_path TEXT
    )
    """)
    conn.commit()
    conn.close()

def create_job(job_id: str, playlist_id: str, playlist_title: str, total_tracks: int, input_csv_path: str):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    cur.execute(
        """
        INSERT INTO jobs (job_id, playlist_id, playlist_title, status, total_tracks, created_at, updated_at, input_csv_path)
        VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)
        """,
        (job_id, playlist_id, playlist_title, total_tracks, now, now, input_csv_path),
    )
    conn.commit()
    conn.close()

def update_job_status(job_id: str, status: str, completed: Optional[int] = None, failed: Optional[int] = None, skipped: Optional[int] = None, log_path: Optional[str] = None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    fields = ["status = ?", "updated_at = ?"]
    args = [status, now]
    if completed is not None:
        fields.append("completed = ?")
        args.append(completed)
    if failed is not None:
        fields.append("failed = ?")
        args.append(failed)
    if skipped is not None:
        fields.append("skipped = ?")
        args.append(skipped)
    if log_path is not None:
        fields.append("log_path = ?")
        args.append(log_path)
    args.append(job_id)
    cur.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?", args)
    conn.commit()
    conn.close()

def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))