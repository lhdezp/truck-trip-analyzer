"""Persistence adapters: storage behind the ``AnalysisRepository`` port."""

from app.infrastructure.persistence.sqlite import SqliteAnalysisRepository

__all__ = ["SqliteAnalysisRepository"]
