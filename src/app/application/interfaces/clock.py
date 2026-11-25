"""Clock port.

Injected instead of calling ``datetime.now()`` so analyses are reproducible and
timestamps are testable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    """Source of the current time."""

    def now(self) -> datetime: ...
