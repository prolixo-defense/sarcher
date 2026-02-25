"""
ChromaDB-based vector store for objection handling knowledge base.

Uses sentence-transformers (all-MiniLM-L6-v2) for local embeddings — zero cost.
Knowledge base lives in ./data/knowledge_base/ as .md files.
"""
import logging
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class RAGStore:
    """Vector store for objection handling knowledge base."""

    COLLECTION_NAME = "objection_kb"

    def __init__(self, persist_dir: str = "./data/chroma", settings=None):
        if settings is None:
            from src.infrastructure.config.settings import get_settings
            settings = get_settings()
        self._settings = settings
        self._persist_dir = persist_dir
        self._client = None
        self._collection = None
        self._embedder = None

    def _get_client(self):
        if self._client is None:
            try:
                import chromadb

                self._client = chromadb.PersistentClient(path=self._persist_dir)
                self._collection = self._client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
            except Exception as exc:
                logger.error("[RAGStore] ChromaDB init failed: %s", exc)
                raise
        return self._client

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

    def _embed(self, text: str) -> list[float]:
        embedder = self._get_embedder()
        return embedder.encode(text).tolist()

    async def add_document(self, text: str, metadata: dict) -> None:
        """Add a document to the knowledge base."""
        try:
            self._get_client()
            doc_id = str(uuid.uuid4())
            embedding = self._embed(text)
            self._collection.add(
                ids=[doc_id],
                documents=[text],
                embeddings=[embedding],
                metadatas=[metadata],
            )
            logger.debug("[RAGStore] Added document id=%s", doc_id)
        except Exception as exc:
            logger.error("[RAGStore] add_document failed: %s", exc)

    async def search(
        self,
        query: str,
        category: Optional[str] = None,
        top_k: int = 5,
    ) -> list[dict]:
        """Search for relevant knowledge base documents."""
        try:
            self._get_client()
            embedding = self._embed(query)
            where = {"category": category} if category else None
            results = self._collection.query(
                query_embeddings=[embedding],
                n_results=min(top_k, self._collection.count() or 1),
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]
            return [
                {
                    "text": doc,
                    "metadata": meta,
                    "score": 1.0 - dist,  # cosine similarity
                }
                for doc, meta, dist in zip(documents, metadatas, distances)
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
                # Derive category from filename (e.g. "objection_budget" → "budget")
                stem = md_file.stem
                if stem.startswith("objection_"):
                    category = stem[len("objection_"):]
                else:
                    category = stem

                import asyncio
                asyncio.get_event_loop().run_until_complete(
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
            self._get_client()
            return self._collection.count()
        except Exception:
            return 0
