import os
import json
import sqlite3
import logging
import time

THREADS_DB_PATH = "data/threads.sqlite"
THREADS_JSON_PATH = "data/threads.json"
logger = logging.getLogger(__name__)


def _init_db(path: str) -> None:
    """Ensure the SQLite database and table exist.

    If the table is missing the ``last_access`` column (from older versions),
    it will be added automatically.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                user_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                last_access INTEGER NOT NULL
            )
            """
        )
        # Ensure ``last_access`` column exists for legacy databases
        cols = {
            row[1] for row in conn.execute("PRAGMA table_info(threads)")
        }
        if "last_access" not in cols:
            conn.execute(
                "ALTER TABLE threads ADD COLUMN last_access INTEGER DEFAULT (strftime('%s','now'))"
            )
        conn.commit()

def load_threads(db_path: str = THREADS_DB_PATH) -> dict:
    """Load stored thread mappings from SQLite.

    If the database is empty and a legacy JSON file exists, migrate the data
    from JSON into SQLite.
    """
    try:
        _init_db(db_path)
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "SELECT user_id, thread_id, last_access FROM threads"
            )
            threads = {
                user_id: {"thread_id": thread_id, "last_access": last_access}
                for user_id, thread_id, last_access in cursor.fetchall()
            }

        if not threads and os.path.isfile(THREADS_JSON_PATH):
            try:
                with open(THREADS_JSON_PATH, "r", encoding="utf-8") as f:
                    legacy = json.load(f)
                now = int(time.time())
                threads = {
                    user_id: {"thread_id": tid, "last_access": now}
                    for user_id, tid in legacy.items()
                }
                save_threads(threads, db_path)
                os.remove(THREADS_JSON_PATH)
            except Exception:
                logger.exception("Failed to migrate threads from JSON")
        return threads
    except Exception:
        logger.exception("Failed to load threads from %s", db_path)
        return {}

def save_threads(threads: dict, db_path: str = THREADS_DB_PATH) -> None:
    """Save thread mappings to SQLite."""
    try:
        _init_db(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM threads")
            conn.executemany(
                "INSERT OR REPLACE INTO threads (user_id, thread_id, last_access) VALUES (?, ?, ?)",
                [
                    (user_id, data["thread_id"], data["last_access"])
                    for user_id, data in threads.items()
                ],
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to save threads to %s", db_path)
