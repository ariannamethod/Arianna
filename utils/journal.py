import os
import json
from datetime import datetime
import logging

LOG_PATH = "data/journal.json"
WILDERNESS_PATH = "data/wilderness.md"

logger = logging.getLogger("journal")


def log_event(event):
    """
    Appends an event with a timestamp to the journal log in JSON format.
    Errors are logged.
    """
    try:
        if not os.path.isfile(LOG_PATH):
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                f.write("[]")
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            log = json.load(f)
        log.append({"ts": datetime.now().isoformat(), **event})
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
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
