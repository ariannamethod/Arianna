import os
import json
from datetime import datetime
import logging

LOG_PATH = "data/journal.json"
WILDERNESS_PATH = "data/wilderness.md"

# Rotate log when exceeding this size (in bytes)
MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB

logger = logging.getLogger("journal")


def _rotate_log(path):
    """Rotate log if it exceeds ``MAX_LOG_SIZE``."""
    if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_SIZE:
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        os.rename(path, f"{path}.{ts}")


def log_event(event):
    """
    Append an event with a timestamp to the journal log in JSON Lines format.
    Errors are logged. Performs size-based rotation.
    """
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        _rotate_log(LOG_PATH)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(
                json.dumps({"ts": datetime.now().isoformat(), **event}, ensure_ascii=False)
                + "\n"
            )
    except Exception:
        logger.exception("Error writing log event")

def wilderness_log(fragment):
    """
    Appends a fragment of text to the wilderness markdown log.
    Errors are logged.
    """
    try:
        with open(WILDERNESS_PATH, "a", encoding="utf-8") as f:
            f.write(fragment.strip() + "\n\n")
    except Exception:
        logger.exception("Error writing wilderness fragment")
