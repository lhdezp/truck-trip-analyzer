"""Logging setup.

Kept in a single function so no module ever configures logging on import.
"""

from __future__ import annotations

import logging

from app.config import Settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(settings: Settings) -> None:
    """Configure the root logger for the current process."""
    level = logging.DEBUG if settings.APP_DEBUG else logging.INFO

    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)
