import os
import logging
import logging.config
import contextvars
from contextlib import contextmanager

try:
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration
except ImportError:  # pragma: no cover - sentry optional
    sentry_sdk = None
    LoggingIntegration = None

chat_id_var = contextvars.ContextVar("chat_id", default="N/A")
user_id_var = contextvars.ContextVar("user_id", default="N/A")


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - simple filter
        record.chat_id = chat_id_var.get()
        record.user_id = user_id_var.get()
        return True


def setup_logging() -> None:
    """Configure logging with rotating file handlers and optional Sentry."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_dir = os.getenv("LOG_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s [%(levelname)s] %(name)s [chat_id=%(chat_id)s user_id=%(user_id)s]: %(message)s",
            }
        },
        "filters": {
            "context": {"()": ContextFilter},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "filters": ["context"],
                "level": log_level,
            },
            "file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "default",
                "filters": ["context"],
                "filename": os.path.join(log_dir, "app.log"),
                "maxBytes": 5 * 1024 * 1024,
                "backupCount": 5,
                "level": log_level,
            },
        },
        "root": {"handlers": ["console", "file"], "level": log_level},
    }

    logging.config.dictConfig(config)

    dsn = os.getenv("SENTRY_DSN")
    if dsn and sentry_sdk:
        logging_integration = LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)
        sentry_sdk.init(dsn=dsn, integrations=[logging_integration])


@contextmanager
def logging_context(chat_id=None, user_id=None):
    tokens = []
    if chat_id is not None:
        tokens.append((chat_id_var, chat_id_var.set(chat_id)))
    if user_id is not None:
        tokens.append((user_id_var, user_id_var.set(user_id)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
