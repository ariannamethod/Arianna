import os
import sqlite3
import logging
from contextlib import closing
from typing import Optional

DB_PATH = "data/threads.db"
logger = logging.getLogger(__name__)


def _get_connection():
    """Return a SQLite connection, creating the database and table if needed."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS threads (
            user_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL
        )
        """
    )
    return conn


def load_thread(user_id: str) -> Optional[str]:
    """Load thread_id for a given user_id."""
    try:
        with closing(_get_connection()) as conn:
            cur = conn.execute(
                "SELECT thread_id FROM threads WHERE user_id = ?",
                (user_id,),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception:
        logger.exception("Failed to load thread for %s", user_id)
        return None


def save_thread(user_id: str, thread_id: str) -> None:
    """Persist thread_id for a given user_id."""
    try:
        with closing(_get_connection()) as conn:
            conn.execute(
                "REPLACE INTO threads (user_id, thread_id) VALUES (?, ?)",
                (user_id, thread_id),
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to save thread %s for %s", thread_id, user_id)

