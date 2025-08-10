import os
import json
from datetime import datetime
import logging

LOG_PATH = "data/journal.json"
WILDERNESS_PATH = "data/wilderness.md"

logger = logging.getLogger("journal")


def log_event(event):
    """
    Append an event with a timestamp to the journal log in JSON Lines format.
    Errors are logged.
    """
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
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
