"""
embedding_db.py
===============
SQLite-backed face embedding database.

Default location: project-root/database/face_embeddings/faces.db
(matching the project folder structure)

Schema
------
faces
  id           INTEGER PRIMARY KEY AUTOINCREMENT
  name         TEXT NOT NULL
  relationship TEXT DEFAULT ''
  embedding    BLOB NOT NULL          — 512-d float32, L2-normalised
  enrolled_at  DATETIME NOT NULL

Key details
-----------
- Embeddings are L2-normalised on write → cosine similarity = dot product at query time.
- find_closest() loads all embeddings into a numpy matrix and does a single matmul.
  Fast for hundreds of people; migrate to faiss for thousands.
- Multiple rows per person are supported and recommended.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 512  # ArcFace / buffalo_l output dimension

# ── default DB path ────────────────────────────────────────────────────────
# __file__ = project-root/backend/ai_modules/face_recognition/embedding_db.py
# parents[3] = project-root/
_DEFAULT_DB_PATH = (
    Path(__file__).parents[3] / "database" / "face_embeddings" / "faces.db"
)


class EmbeddingDB:
    """
    Persistent face embedding store backed by SQLite.

    Parameters
    ----------
    db_path : Path to .db file — created (with parent dirs) automatically.
    """

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        logger.debug("EmbeddingDB ready at %s", self.db_path)

    # ──────────────────────────── schema ──────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS faces (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    name         TEXT    NOT NULL,
                    relationship TEXT    NOT NULL DEFAULT '',
                    embedding    BLOB    NOT NULL,
                    enrolled_at  TEXT    NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_faces_name ON faces(name)"
            )
            conn.commit()

    # ──────────────────────────── write ───────────────────────────────────────

    def add_face(
        self,
        name: str,
        embedding: np.ndarray,
        relationship: str = "",
    ) -> int:
        """
        Store one embedding. Returns the new row id.
        The embedding is L2-normalised before storage.
        """
        emb_norm = self._l2_normalise(embedding).astype(np.float32)
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO faces (name, relationship, embedding, enrolled_at) "
                "VALUES (?, ?, ?, ?)",
                (name, relationship, emb_norm.tobytes(), now),
            )
            conn.commit()

        logger.debug("Stored embedding for '%s' (row %d).", name, cur.lastrowid)
        return cur.lastrowid

    def delete_person(self, name: str) -> int:
        """Delete all embeddings for `name`. Returns rows removed."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM faces WHERE name = ?", (name,))
            conn.commit()
        logger.info("Deleted %d embedding(s) for '%s'.", cur.rowcount, name)
        return cur.rowcount

    def clear(self) -> None:
        """Wipe the entire table — use with care."""
        with self._connect() as conn:
            conn.execute("DELETE FROM faces")
            conn.commit()
        logger.warning("EmbeddingDB cleared.")

    # ──────────────────────────── search ──────────────────────────────────────

    def find_closest(
        self,
        query_embedding: np.ndarray,
    ) -> tuple[Optional[str], float]:
        """
        Return (name, cosine_similarity) of the closest stored face.
        Returns (None, 0.0) if the database is empty.

        Algorithm: load all embeddings as an (N, 512) matrix,
        normalise query, compute matrix @ query (vectorised dot product).
        """
        rows = self._load_all_rows()
        if rows is None:
            return None, 0.0

        names, matrix = rows
        query_norm = self._l2_normalise(query_embedding).astype(np.float32)
        similarities = matrix @ query_norm          # shape (N,)
        best = int(np.argmax(similarities))
        return names[best], float(similarities[best])

    def find_top_k(
        self,
        query_embedding: np.ndarray,
        k: int = 3,
    ) -> list[tuple[str, float]]:
        """Return the top-k matches as [(name, similarity), …] sorted descending."""
        rows = self._load_all_rows()
        if rows is None:
            return []

        names, matrix = rows
        query_norm = self._l2_normalise(query_embedding).astype(np.float32)
        sims = matrix @ query_norm
        top = np.argsort(sims)[::-1][:k]
        return [(names[i], float(sims[i])) for i in top]

    def list_all(self) -> list[dict]:
        """Summary list of all enrolled persons (no embedding blobs)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, relationship, enrolled_at FROM faces ORDER BY name"
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM faces").fetchone()[0]

    def person_count(self) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(DISTINCT name) FROM faces"
            ).fetchone()[0]

    # ──────────────────────────── internals ───────────────────────────────────

    def _load_all_rows(self) -> Optional[tuple[list[str], np.ndarray]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, embedding FROM faces"
            ).fetchall()
        if not rows:
            return None
        names = [r["name"] for r in rows]
        matrix = np.stack([
            np.frombuffer(r["embedding"], dtype=np.float32).reshape(EMBEDDING_DIM)
            for r in rows
        ])  # (N, 512)
        return names, matrix

    @staticmethod
    def _l2_normalise(vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        return vec if norm < 1e-10 else vec / norm