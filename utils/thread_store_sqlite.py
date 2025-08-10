import os
import json
import sqlite3
import logging
import time

THREADS_DB_PATH = "data/threads.sqlite"
THREADS_JSON_PATH = "data/threads.json"
logger = logging.getLogger(__name__)


def _init_db(path: str) -> None:
    """Ensure the SQLite database and table exist."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                user_id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                last_used INTEGER NOT NULL
            )
            """
        )
        # try add column if existing DB lacks it
        try:
            conn.execute("SELECT last_used FROM threads LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute(
                "ALTER TABLE threads ADD COLUMN last_used INTEGER NOT NULL DEFAULT (strftime('%s','now'))"
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
            cursor = conn.execute("SELECT user_id, thread_id FROM threads")
            threads = {user_id: thread_id for user_id, thread_id in cursor.fetchall()}

        # Migrate legacy keys of the form "chat_id:sender_id" to just "chat_id"
        migrated: dict[str, str] = {}
        changed = False
        for key, value in threads.items():
            if ":" in key:
                new_key = key.split(":", 1)[0]
                # Keep the first thread_id encountered for a chat_id
                migrated.setdefault(new_key, value)
                changed = True
            else:
                migrated[key] = value

        if changed:
            save_threads(migrated, db_path)
            threads = migrated

        if not threads and os.path.isfile(THREADS_JSON_PATH):
            try:
                with open(THREADS_JSON_PATH, "r", encoding="utf-8") as f:
                    threads = json.load(f)
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
        now = int(time.time())
        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO threads (user_id, thread_id, last_used)
                VALUES (?, ?, ?)
                """,
                [(u, t, now) for u, t in threads.items()],
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to save threads to %s", db_path)


def get_thread(user_id: str, db_path: str = THREADS_DB_PATH) -> str | None:
    """Fetch thread_id for a single user_id from SQLite."""
    try:
        _init_db(db_path)
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "SELECT thread_id FROM threads WHERE user_id = ?", (user_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
    except Exception:
        logger.exception("Failed to get thread for %s", user_id)
        return None


def set_thread(user_id: str, thread_id: str | None, db_path: str = THREADS_DB_PATH) -> None:
    """Insert, update or delete a thread mapping for a single user_id."""
    try:
        _init_db(db_path)
        with sqlite3.connect(db_path) as conn:
            if thread_id is None:
                conn.execute("DELETE FROM threads WHERE user_id = ?", (user_id,))
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO threads (user_id, thread_id, last_used)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, thread_id, int(time.time())),
                )
            conn.commit()
    except Exception:
        logger.exception("Failed to set thread for %s", user_id)


def touch_thread(user_id: str, db_path: str = THREADS_DB_PATH) -> None:
    """Update last_used for the given user id."""
    try:
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE threads SET last_used = ? WHERE user_id = ?",
                (int(time.time()), user_id),
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to update last_used for %s", user_id)


def cleanup_old_threads(max_age_days: int, db_path: str = THREADS_DB_PATH) -> None:
    """Remove threads older than max_age_days."""
    try:
        _init_db(db_path)
        cutoff = int(time.time()) - max_age_days * 86400
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM threads WHERE last_used < ?", (cutoff,))
            conn.commit()
    except Exception:
        logger.exception("Failed to cleanup old threads")
