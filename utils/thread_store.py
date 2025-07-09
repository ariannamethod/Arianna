import os
import json
import logging

THREADS_PATH = os.path.join('data', 'threads.json')

logger = logging.getLogger(__name__)

def load_threads():
    """Load thread dictionary from file."""
    if os.path.isfile(THREADS_PATH):
        try:
            with open(THREADS_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            logger.exception('Failed to load threads')
    return {}


def save_threads(threads: dict):
    """Persist thread dictionary to file."""
    try:
        os.makedirs(os.path.dirname(THREADS_PATH), exist_ok=True)
        with open(THREADS_PATH, 'w', encoding='utf-8') as f:
            json.dump(threads, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception('Failed to save threads')

