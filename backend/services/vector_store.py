"""
Vector database service backed by a standalone Chroma server.

The Flask app talks to Chroma over HTTP so Chroma's Rust runtime is isolated
from the web process. Vectors are stored in one collection per user; document
identity lives in metadata.
"""
from __future__ import annotations

import os
import threading
from typing import List

import config
from backend.utils.logger import log


class VectorStore:
    """Chroma HTTP client wrapper."""

    _client = None
    _embedding_fn = None
    _lock = threading.Lock()

    def __init__(self):
        self.last_embeddings = []
        if config.VECTOR_BACKEND == "pgvector":
            self._pgvector = PgVectorStore()
        else:
            self._pgvector = None
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    @classmethod
    def _get_client(cls):
        if cls._client is not None:
            return cls._client

        with cls._lock:
            if cls._client is not None:
                return cls._client

            try:
                import chromadb
                from chromadb.config import Settings

                cls._client = chromadb.HttpClient(
                    host=config.CHROMA_HOST,
                    port=config.CHROMA_PORT,
                    ssl=config.CHROMA_SSL,
                    settings=Settings(anonymized_telemetry=False),
                )
                cls._client.heartbeat()
                return cls._client
            except BaseException as exc:
                cls._client = None
                raise RuntimeError(
                    f"Chroma server unavailable at "
                    f"{config.CHROMA_HOST}:{config.CHROMA_PORT}: {exc}"
                ) from exc

    @classmethod
    def _get_embedding_function(cls):
        if cls._embedding_fn is not None:
            return cls._embedding_fn

        with cls._lock:
            if cls._embedding_fn is not None:
                return cls._embedding_fn

            from sentence_transformers import SentenceTransformer

            try:
                model = SentenceTransformer(config.EMBEDDING_MODEL, backend="onnx")
                log.info(f"[VectorStore] ONNX embedding backend enabled: {config.EMBEDDING_MODEL}")
            except Exception:
                model = SentenceTransformer(config.EMBEDDING_MODEL)
                log.info(f"[VectorStore] PyTorch embedding backend enabled: {config.EMBEDDING_MODEL}")

            cls._embedding_fn = model.encode
            return cls._embedding_fn

    @staticmethod
    def _collection_name(user_id: int = None) -> str:
        return f"user_{user_id}_knowledge" if user_id else "shared_knowledge"

    @classmethod
    def _get_or_create_collection(cls, user_id: int = None):
        return cls._get_client().get_or_create_collection(
            name=cls._collection_name(user_id),
            metadata={"hnsw:space": "cosine"},
        )

    def add_chunks(self, doc_id: int, chunks: List[str], user_id: int = None) -> List[str]:
        """Add document chunks to the user's unified knowledge collection."""
        if self._pgvector:
            ids = self._pgvector.add_chunks(doc_id, chunks, user_id=user_id)
            self.last_embeddings = self._pgvector.last_embeddings
            return ids

        if not chunks:
            return []

        collection = self._get_or_create_collection(user_id)
        self._delete_doc_from_collection(collection, doc_id)

        embeddings = self._get_embedding_function()(chunks).tolist()
        ids = [f"doc_{doc_id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "doc_id": int(doc_id),
                "chunk_index": i,
                "user_id": int(user_id) if user_id is not None else 0,
            }
            for i in range(len(chunks))
        ]

        batch_size = 100
        for start in range(0, len(chunks), batch_size):
            end = start + batch_size
            collection.add(
                ids=ids[start:end],
                embeddings=embeddings[start:end],
                documents=chunks[start:end],
                metadatas=metadatas[start:end],
            )

        return ids

    def search(self, query: str, doc_id: int = None, top_k: int = 5, user_id: int = None) -> List[dict]:
        """Semantic search in a single document or across the user's knowledge base."""
        if self._pgvector:
            return self._pgvector.search(query, doc_id, top_k, user_id=user_id)

        try:
            collection = self._get_client().get_collection(self._collection_name(user_id))
        except Exception:
            return []

        try:
            query_embedding = self._get_embedding_function()([query]).tolist()
            where = {"doc_id": int(doc_id)} if doc_id else None
            count = collection.count()
            n_results = min(max(1, int(top_k or 5)), count)
            if n_results <= 0:
                return []

            kwargs = {
                "query_embeddings": query_embedding,
                "n_results": n_results,
                "include": ["documents", "distances", "metadatas"],
            }
            if where:
                kwargs["where"] = where
            results = collection.query(**kwargs)
        except BaseException as exc:
            log.warning(f"[VectorStore] search failed: {exc}")
            return []

        return self._enrich_results(results)

    def delete_document(self, doc_id: int, user_id: int = None):
        if self._pgvector:
            self._pgvector.delete_document(doc_id, user_id=user_id)
            return

        try:
            collection = self._get_client().get_collection(self._collection_name(user_id))
            self._delete_doc_from_collection(collection, doc_id)
        except BaseException:
            pass

    def get_document_count(self, doc_id: int, user_id: int = None) -> int:
        if self._pgvector:
            return self._pgvector.get_document_count(doc_id, user_id=user_id)

        try:
            collection = self._get_client().get_collection(self._collection_name(user_id))
            result = collection.get(where={"doc_id": int(doc_id)}, include=[])
            return len(result.get("ids", []))
        except BaseException:
            return 0

    @staticmethod
    def _delete_doc_from_collection(collection, doc_id: int):
        try:
            collection.delete(where={"doc_id": int(doc_id)})
        except BaseException:
            pass

    @staticmethod
    def _enrich_results(results: dict) -> List[dict]:
        if not results or not results.get("documents") or not results["documents"][0]:
            return []

        documents = results["documents"][0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else [{}] * len(documents)

        enriched = []
        for i, (doc, dist) in enumerate(zip(documents, distances)):
            meta = metadatas[i] if i < len(metadatas) else {}
            enriched.append(
                {
                    "text": doc,
                    "score": round(1.0 - dist, 4),
                    "distance": round(dist, 4),
                    "doc_id": meta.get("doc_id"),
                    "chunk_index": meta.get("chunk_index"),
                }
            )
        return enriched


class PgVectorStore:
    """pgvector-backed vector search using PostgreSQL document_chunks."""

    def __init__(self):
        self.last_embeddings = []

    def add_chunks(self, doc_id: int, chunks: List[str], user_id: int = None) -> List[str]:
        self.last_embeddings = self._embed(chunks)
        return [f"doc_{doc_id}_chunk_{i}" for i in range(len(chunks))]

    def search(self, query: str, doc_id: int = None, top_k: int = 5, user_id: int = None) -> List[dict]:
        embeddings = self._embed([query])
        if not embeddings:
            return []

        where = ["embedding IS NOT NULL"]
        params = [_vector_literal(embeddings[0])]
        if doc_id:
            where.append("document_id = ?")
            params.append(int(doc_id))
        if user_id is not None:
            where.append("user_id = ?")
            params.append(int(user_id))

        sql = (
            "SELECT document_id, chunk_index, content, "
            "embedding <=> ?::vector AS distance "
            "FROM document_chunks "
            "WHERE " + " AND ".join(where) + " "
            "ORDER BY embedding <=> ?::vector "
            "LIMIT ?"
        )
        params.append(_vector_literal(embeddings[0]))
        params.append(max(1, int(top_k or 5)))

        try:
            from models.database import get_db

            conn = get_db()
            rows = conn.execute(sql, params).fetchall()
            conn.close()
        except BaseException as exc:
            log.warning(f"[PgVectorStore] search failed: {exc}")
            return []

        results = []
        for row in rows:
            distance = float(row["distance"] or 0.0)
            results.append({
                "text": row["content"],
                "score": round(1.0 - distance, 4),
                "distance": round(distance, 4),
                "doc_id": row["document_id"],
                "chunk_index": row["chunk_index"],
            })
        return results

    def delete_document(self, doc_id: int, user_id: int = None):
        return

    def get_document_count(self, doc_id: int, user_id: int = None) -> int:
        try:
            from models.database import get_db

            conn = get_db()
            row = conn.execute(
                "SELECT COUNT(*) FROM document_chunks WHERE document_id = ? AND embedding IS NOT NULL",
                (int(doc_id),),
            ).fetchone()
            conn.close()
            return row[0] if row else 0
        except BaseException:
            return 0

    def _embed(self, texts: List[str]) -> List[list[float]]:
        if not texts:
            return []
        api_key = config.EMBEDDING_API_KEY or config.LLM_API_KEY
        base_url = config.EMBEDDING_BASE_URL
        model = config.EMBEDDING_API_MODEL
        if not api_key:
            log.warning("[PgVectorStore] embedding API key is not configured")
            return []

        try:
            from openai import OpenAI

            client = OpenAI(api_key=api_key, base_url=base_url)
            response = client.embeddings.create(
                model=model,
                input=texts,
                dimensions=config.EMBEDDING_DIMENSION,
            )
            return [item.embedding for item in response.data]
        except BaseException as exc:
            log.warning(f"[PgVectorStore] embedding failed: {exc}")
            return []


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in values) + "]"
