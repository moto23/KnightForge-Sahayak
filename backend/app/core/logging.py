"""
Logging configuration.

Provides a single `setup_logging()` call that the app runs once at startup so
every module can just do `logging.getLogger(__name__)` and get consistent,
timestamped output. Log level is driven by settings (LOG_LEVEL / DEBUG).
"""

import logging
import sys

from app.core.config import settings

# Human-readable log line: time, level, logger name, message.
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """
    Configure the root logger once, writing to stdout.

    Called from app startup. Safe to call multiple times — it resets handlers so
    uvicorn's --reload doesn't stack duplicate log lines.
    """
    level = logging.DEBUG if settings.DEBUG else getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # Clear existing handlers to avoid duplicate lines on reload.
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(handler)

    # Align uvicorn's own loggers with our level/format instead of its defaults.
    for uvicorn_logger in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(uvicorn_logger).setLevel(level)

    logging.getLogger(__name__).debug("Logging configured at level %s", logging.getLevelName(level))
