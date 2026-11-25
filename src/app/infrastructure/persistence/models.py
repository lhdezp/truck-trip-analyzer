"""SQLAlchemy models for persistence.

The analysis result is stored as a JSON blob keyed by a UUID. This keeps the domain
model free of ORM annotations: the result is a Pydantic object that serializes to
JSON on write and deserializes on read.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, String, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Analysis(Base):
    """One finished analysis, stored as a JSON payload."""

    __tablename__ = "analysis"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=text("(datetime('now'))")
    )
