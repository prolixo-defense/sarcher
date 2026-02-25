"""
SQLite + numpy vector store for objection handling knowledge base.

Replaces ChromaDB (which uses pydantic.v1, incompatible with Python 3.14).
Uses sentence-transformers (all-MiniLM-L6-v2) for local embeddings — zero cost.
Knowledge base lives in ./data/knowledge_base/ as .md files.

Storage: SQLite BLOB for float32 embeddings, cosine similarity via numpy.
"""
import json
import logging
import sqlite3
import uuid
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS documents (
    id       TEXT PRIMARY KEY,
    text     TEXT NOT NULL,
    embedding BLOB NOT NULL,
    metadata TEXT NOT NULL,
    category TEXT
)
"""


class RAGStore:
    """Vector store for objection handling knowledge base."""

    COLLECTION_NAME = "objection_kb"

    def __init__(self, persist_dir: str = "./data/chroma", settings=None):
        if settings is None:
            from src.infrastructure.config.settings import get_settings
            settings = get_settings()
        self._settings = settings
        self._persist_dir = persist_dir
        self._conn: Optional[sqlite3.Connection] = None
        self._embedder = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            Path(self._persist_dir).mkdir(parents=True, exist_ok=True)
            db_path = str(Path(self._persist_dir) / "rag_store.db")
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.execute(_CREATE_TABLE)
            self._conn.commit()
        return self._conn

    def _get_embedder(self):
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                model_name = getattr(self._settings, "embedding_model", "all-MiniLM-L6-v2")
                self._embedder = SentenceTransformer(model_name)
            except Exception as exc:
                logger.error("[RAGStore] SentenceTransformer init failed: %s", exc)
                raise
        return self._embedder

    def _embed(self, text: str) -> np.ndarray:
        return self._get_embedder().encode(text).astype(np.float32)

    @staticmethod
    def _to_blob(arr: np.ndarray) -> bytes:
        return arr.tobytes()

    @staticmethod
    def _from_blob(blob: bytes, dim: int) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32)

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        denom = np.linalg.norm(a) * np.linalg.norm(b)
        if denom == 0:
            return 0.0
        return float(np.dot(a, b) / denom)

    async def add_document(self, text: str, metadata: dict) -> None:
        """Add a document to the knowledge base."""
        try:
            conn = self._get_conn()
            doc_id = str(uuid.uuid4())
            embedding = self._embed(text)
            category = metadata.get("category")
            conn.execute(
                "INSERT INTO documents (id, text, embedding, metadata, category) VALUES (?, ?, ?, ?, ?)",
                (doc_id, text, self._to_blob(embedding), json.dumps(metadata), category),
            )
            conn.commit()
            logger.debug("[RAGStore] Added document id=%s", doc_id)
        except Exception as exc:
            logger.error("[RAGStore] add_document failed: %s", exc)

    async def search(
        self,
        query: str,
        category: Optional[str] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """Search for relevant knowledge base documents using cosine similarity."""
        try:
            conn = self._get_conn()
            query_vec = self._embed(query)

            if category:
                rows = conn.execute(
                    "SELECT text, embedding, metadata FROM documents WHERE category = ?",
                    (category,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT text, embedding, metadata FROM documents"
                ).fetchall()

            if not rows:
                return []

            scored = []
            for text, blob, meta_json in rows:
                doc_vec = self._from_blob(blob, len(query_vec))
                score = self._cosine_similarity(query_vec, doc_vec)
                scored.append((score, text, json.loads(meta_json)))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                {"text": text, "metadata": meta, "score": score}
                for score, text, meta in scored[:top_k]
            ]
        except Exception as exc:
            logger.warning("[RAGStore] search failed: %s", exc)
            return []

    def seed_from_directory(self, knowledge_dir: str = "./data/knowledge_base") -> int:
        """Load all .md files from directory into the knowledge base."""
        kb_dir = Path(knowledge_dir)
        if not kb_dir.exists():
            logger.warning("[RAGStore] Knowledge base directory not found: %s", knowledge_dir)
            return 0

        count = 0
        for md_file in sorted(kb_dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8").strip()
                if not text:
                    continue
                stem = md_file.stem
                category = stem[len("objection_"):] if stem.startswith("objection_") else stem

                import asyncio
                asyncio.run(
                    self.add_document(
                        text=text,
                        metadata={"category": category, "source": md_file.name},
                    )
                )
                count += 1
                logger.info("[RAGStore] Seeded %s (category=%s)", md_file.name, category)
            except Exception as exc:
                logger.warning("[RAGStore] Failed to seed %s: %s", md_file, exc)
        return count

    def count(self) -> int:
        """Return number of documents in the collection."""
        try:
            conn = self._get_conn()
            return conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        except Exception:
            return 0
