import os
import json
import sqlite3
import logging
from filelock import FileLock

DB_PATH = "data/threads.db"
JSON_PATH = "data/threads.json"
logger = logging.getLogger(__name__)


def _init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS threads (thread_key TEXT PRIMARY KEY, thread_id TEXT)"
        )
        conn.commit()


def _migrate_from_json() -> None:
    if not os.path.isfile(JSON_PATH):
        return
    lock = FileLock(f"{JSON_PATH}.lock")
    try:
        with lock, open(JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        logger.exception("Failed to read threads JSON for migration")
        return
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO threads (thread_key, thread_id) VALUES (?, ?)",
                data.items(),
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to migrate threads to SQLite")
        return
    try:
        os.remove(JSON_PATH)
    except OSError:
        pass


_init_db()
_migrate_from_json()


def load_thread(key: str):
    """Load a thread ID for the given key."""
    lock = FileLock(f"{DB_PATH}.lock")
    with lock, sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT thread_id FROM threads WHERE thread_key = ?", (key,)
        ).fetchone()
    return row[0] if row else None


def save_thread(key: str, thread_id: str) -> None:
    """Persist a thread ID for the given key."""
    lock = FileLock(f"{DB_PATH}.lock")
    with lock, sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO threads (thread_key, thread_id) VALUES (?, ?)",
            (key, thread_id),
        )
        conn.commit()
