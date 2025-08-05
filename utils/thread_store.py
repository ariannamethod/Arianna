import os
import json
import logging
from filelock import FileLock

THREADS_PATH = "data/threads.json"
logger = logging.getLogger(__name__)

# TODO: consider migrating to SQLite for better durability before introducing
# client-id–based multi-user flows.


def load_threads(path: str = THREADS_PATH) -> dict:
    """Load stored thread mappings from JSON."""
    lock = FileLock(f"{path}.lock")
    try:
        with lock:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
    except Exception:
        logger.exception("Failed to load threads from %s", path)
    return {}


def save_threads(threads: dict, path: str = THREADS_PATH) -> None:
    """Save thread mappings to JSON."""
    lock = FileLock(f"{path}.lock")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with lock, open(path, "w", encoding="utf-8") as f:
            json.dump(threads, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception("Failed to save threads to %s", path)
