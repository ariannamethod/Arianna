import os
import sqlite3
import logging

THREADS_DB_PATH = "data/threads.sqlite"
logger = logging.getLogger(__name__)


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS threads ("
        "id TEXT PRIMARY KEY, thread_id TEXT)"
    )
    conn.commit()


def load_threads(path: str = THREADS_DB_PATH) -> dict:
    """Load stored thread mappings from SQLite."""
    if not os.path.isfile(path):
        return {}
    try:
        conn = sqlite3.connect(path)
        try:
            _ensure_table(conn)
            cur = conn.execute("SELECT id, thread_id FROM threads")
            return {row[0]: row[1] for row in cur.fetchall()}
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to load threads from %s", path)
        return {}


def save_threads(threads: dict, path: str = THREADS_DB_PATH) -> None:
    """Save thread mappings to SQLite."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = sqlite3.connect(path)
        try:
            _ensure_table(conn)
            conn.executemany(
                "INSERT OR REPLACE INTO threads (id, thread_id) VALUES (?, ?)",
                list(threads.items()),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to save threads to %s", path)
