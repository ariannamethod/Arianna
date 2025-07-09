import os
import json
import logging

THREADS_PATH = "data/threads.json"
logger = logging.getLogger(__name__)


def load_threads():
    """Load persisted thread mappings from JSON."""
    if os.path.isfile(THREADS_PATH):
        try:
            with open(THREADS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load threads", exc_info=e)
    return {}


def save_threads(threads):
    """Persist thread mappings to JSON."""
    try:
        os.makedirs(os.path.dirname(THREADS_PATH), exist_ok=True)
        with open(THREADS_PATH, "w", encoding="utf-8") as f:
            json.dump(threads, f)
    except Exception as e:
        logger.error("Failed to save threads", exc_info=e)
