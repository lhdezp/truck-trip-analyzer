"""SQLite repository for finished analyses.

The repository is async-friendly: it uses ``sqlite3`` synchronously but the public
methods are async so the use case can ``await`` them without knowing the storage.
SQLite is the right default for the MVP; a Postgres implementation would sit behind
the same port.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from app.application.interfaces.persistence import AnalysisRepository
from app.application.schemas.result import LoadAnalysisResult


class SqliteAnalysisRepository(AnalysisRepository):
    """Stores :class:`LoadAnalysisResult` objects in a SQLite database."""

    def __init__(self, database_url: str) -> None:
        """``database_url`` is a SQLAlchemy-style URL (``sqlite:///./data/data.db``)."""
        path = self._resolve_path(database_url)
        self._path = path

    @staticmethod
    def _resolve_path(database_url: str) -> Path:
        """Extract the file path from a SQLAlchemy URL.

        The MVP only supports ``sqlite:///`` URLs; a ``:memory:`` URL is mapped to a
        file so the repository has a stable location.
        """
        if database_url.startswith("sqlite://"):
            tail = database_url[len("sqlite://") :]
            if tail.startswith("./"):
                return Path(tail)
            if tail == ":memory:":
                return Path("data/memory.db")
            return Path(tail)
        raise ValueError(f"Unsupported database URL scheme: {database_url}")

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis (
                id TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        return conn

    async def save(self, result: LoadAnalysisResult) -> str:
        """Persist one analysis and return its identifier.

        The id is generated here, not in the domain: the use case does not know the
        storage scheme, so the repository owns the identity.
        """
        analysis_id = str(uuid.uuid4())
        payload = json.dumps(result.model_dump(mode="json"), default=str)
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO analysis (id, payload) VALUES (?, ?)",
                (analysis_id, payload),
            )
            conn.commit()
        finally:
            conn.close()
        return analysis_id

    async def get(self, analysis_id: str) -> LoadAnalysisResult | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT payload FROM analysis WHERE id = ?", (analysis_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return LoadAnalysisResult.model_validate(json.loads(row[0]))

    async def list_recent(self, *, limit: int = 20) -> list[LoadAnalysisResult]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT payload FROM analysis ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [LoadAnalysisResult.model_validate(json.loads(row[0])) for row in rows]
