import os
import json
import sqlite3
import logging
import time
from typing import Optional

THREADS_DB_PATH = "data/threads.sqlite"
THREADS_JSON_PATH = "data/threads.json"
logger = logging.getLogger(__name__)


def _init_db(path: str) -> None:
    """Ensure the SQLite database and required tables exist."""
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

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                thread_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT,
                created_at INTEGER NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                summary TEXT,
                embedding TEXT,
                created_at INTEGER NOT NULL
            )
            """
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


def get_thread(user_id: str, db_path: str = THREADS_DB_PATH) -> Optional[str]:
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


def set_thread(
    user_id: str, thread_id: Optional[str], db_path: str = THREADS_DB_PATH
) -> None:
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


def save_message(
    thread_id: str,
    role: str,
    content: str,
    embedding: Optional[list[float]] = None,
    created_at: Optional[int] = None,
    db_path: str = THREADS_DB_PATH,
) -> None:
    """Store a single message in the messages table."""
    try:
        _init_db(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO messages (thread_id, role, content, embedding, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    role,
                    content,
                    json.dumps(embedding) if embedding is not None else None,
                    created_at or int(time.time()),
                ),
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to save message for thread %s", thread_id)


def get_messages_by_date(date_str: str, db_path: str = THREADS_DB_PATH) -> list[dict]:
    """Return messages created on the given YYYY-MM-DD date."""
    try:
        _init_db(db_path)
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                """
                SELECT thread_id, role, content, embedding, created_at
                FROM messages
                WHERE date(created_at, 'unixepoch') = ?
                ORDER BY created_at
                """,
                (date_str,),
            )
            rows = cursor.fetchall()
        messages = []
        for tid, role, content, emb, created_at in rows:
            messages.append(
                {
                    "thread_id": tid,
                    "role": role,
                    "content": content,
                    "embedding": json.loads(emb) if emb else None,
                    "created_at": created_at,
                }
            )
        return messages
    except Exception:
        logger.exception("Failed to fetch messages by date")
        return []


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return -1.0
    return dot / (norm_a * norm_b)


def search_messages_by_embedding(
    query_embedding: list[float],
    top_k: int = 5,
    db_path: str = THREADS_DB_PATH,
) -> list[dict]:
    """Return up to top_k messages semantically close to the query embedding."""
    try:
        _init_db(db_path)
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "SELECT thread_id, role, content, embedding, created_at FROM messages WHERE embedding IS NOT NULL"
            )
            rows = cursor.fetchall()
        scored = []
        for tid, role, content, emb, created_at in rows:
            emb_list = json.loads(emb)
            sim = _cosine_similarity(query_embedding, emb_list)
            scored.append(
                (
                    sim,
                    {
                        "thread_id": tid,
                        "role": role,
                        "content": content,
                        "embedding": emb_list,
                        "created_at": created_at,
                    },
                )
            )
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:top_k]]
    except Exception:
        logger.exception("Failed to perform semantic search over messages")
        return []


def save_snapshot(
    snapshot_date: str,
    summary: str,
    embedding: Optional[list[float]] = None,
    created_at: Optional[int] = None,
    db_path: str = THREADS_DB_PATH,
) -> None:
    """Save metadata about a daily snapshot."""
    try:
        _init_db(db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO snapshots (snapshot_date, summary, embedding, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    snapshot_date,
                    summary,
                    json.dumps(embedding) if embedding is not None else None,
                    created_at or int(time.time()),
                ),
            )
            conn.commit()
    except Exception:
        logger.exception("Failed to save snapshot for %s", snapshot_date)


def get_snapshots_by_date(date_str: str, db_path: str = THREADS_DB_PATH) -> list[dict]:
    """Return snapshots created on the given date (YYYY-MM-DD)."""
    try:
        _init_db(db_path)
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                """
                SELECT snapshot_date, summary, embedding, created_at
                FROM snapshots
                WHERE snapshot_date = ?
                ORDER BY created_at
                """,
                (date_str,),
            )
            rows = cursor.fetchall()
        snapshots = []
        for s_date, summary, emb, created_at in rows:
            snapshots.append(
                {
                    "snapshot_date": s_date,
                    "summary": summary,
                    "embedding": json.loads(emb) if emb else None,
                    "created_at": created_at,
                }
            )
        return snapshots
    except Exception:
        logger.exception("Failed to fetch snapshots by date")
        return []


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
