"""
向量数据库服务 - 使用 ChromaDB 实现本地向量存储与检索
"""
import json
from typing import List, Tuple, Optional
from pathlib import Path
import config


class VectorStore:
    """ChromaDB 向量存储封装"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # 强制 HuggingFace 离线模式，避免每次初始化都联网
        import os
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

        import chromadb
        from chromadb.config import Settings

        self.client = chromadb.PersistentClient(
            path=str(config.VECTOR_DB_DIR),
            settings=Settings(anonymized_telemetry=False)
        )
        self.embedding_model = config.EMBEDDING_MODEL
        self._embedding_fn = None
        self._initialized = True

    def _get_embedding_function(self):
        """延迟加载 embedding 函数（优先 ONNX 加速）"""
        if self._embedding_fn is None:
            from sentence_transformers import SentenceTransformer
            # 尝试 ONNX 加速
            try:
                model = SentenceTransformer(self.embedding_model, backend="onnx")
                print(f"[VectorStore] ONNX 加速已启用: {self.embedding_model}")
            except Exception:
                model = SentenceTransformer(self.embedding_model)
                print(f"[VectorStore] 使用 PyTorch 后端: {self.embedding_model}")
            self._embedding_fn = model.encode
        return self._embedding_fn

    def _get_or_create_collection(self, doc_id: int, user_id: int = None):
        """获取或创建文档对应的 collection（按用户隔离）"""
        if user_id:
            collection_name = f"user_{user_id}_doc_{doc_id}"
        else:
            collection_name = f"doc_{doc_id}"
        return self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def add_chunks(self, doc_id: int, chunks: List[str], user_id: int = None) -> List[str]:
        """
        将文本片段添加到向量数据库
        """
        if not chunks:
            return []

        collection = self._get_or_create_collection(doc_id, user_id)
        embedding_fn = self._get_embedding_function()

        embeddings = embedding_fn(chunks).tolist()
        ids = [f"chunk_{doc_id}_{i}" for i in range(len(chunks))]
        metadatas = [{"doc_id": doc_id, "chunk_index": i, "user_id": user_id} for i in range(len(chunks))]

        # 分批添加（ChromaDB 有批次限制）
        batch_size = 100
        for start in range(0, len(chunks), batch_size):
            end = start + batch_size
            collection.add(
                ids=ids[start:end],
                embeddings=embeddings[start:end],
                documents=chunks[start:end],
                metadatas=metadatas[start:end]
            )

        return ids

    def search(self, query: str, doc_id: int = None, top_k: int = 5, user_id: int = None) -> List[dict]:
        """
        语义搜索最相关的文本片段

        Returns:
            [{"text": str, "score": float, "doc_id": int, "chunk_index": int}, ...]
        """
        embedding_fn = self._get_embedding_function()
        query_embedding = embedding_fn([query]).tolist()

        if doc_id:
            collection_name = f"user_{user_id}_doc_{doc_id}" if user_id else f"doc_{doc_id}"
            try:
                collection = self.client.get_collection(collection_name)
            except Exception:
                return []
            results = collection.query(
                query_embeddings=query_embedding,
                n_results=top_k,
                include=["documents", "distances", "metadatas"]
            )
        else:
            # 跨该用户所有 collection 搜索
            prefix = f"user_{user_id}_" if user_id else "doc_"
            all_collections = [c for c in self.client.list_collections() if c.name.startswith(prefix)]
            all_results = []
            for coll in all_collections:
                try:
                    result = coll.query(query_embeddings=query_embedding, n_results=top_k,
                                        include=["documents", "distances", "metadatas"])
                    all_results.append(result)
                except Exception:
                    continue
            results = self._merge_results(all_results, top_k)

        if not results or not results.get("documents") or not results["documents"][0]:
            return []

        documents = results["documents"][0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else [{}] * len(documents)

        enriched = []
        for i, (doc, dist) in enumerate(zip(documents, distances)):
            meta = metadatas[i] if i < len(metadatas) else {}
            enriched.append({
                "text": doc,
                "score": round(1.0 - dist, 4),
                "doc_id": meta.get("doc_id"),
                "chunk_index": meta.get("chunk_index")
            })
        return enriched

    def _merge_results(self, all_results: list, top_k: int) -> dict:
        """合并多个 collection 的搜索结果"""
        merged_docs = []
        merged_dists = []
        merged_metas = []
        for result in all_results:
            if result.get("documents") and result["documents"][0]:
                merged_docs.extend(result["documents"][0])
                merged_dists.extend(result.get("distances", [[]])[0])
                metas = result.get("metadatas", [[]])[0] if result.get("metadatas") else [{}] * len(result["documents"][0])
                merged_metas.extend(metas)

        # 按距离排序，取 top_k
        paired = sorted(zip(merged_docs, merged_dists, merged_metas), key=lambda x: x[1])
        paired = paired[:top_k]

        return {
            "documents": [[p[0] for p in paired]],
            "distances": [[p[1] for p in paired]],
            "metadatas": [[p[2] for p in paired]]
        }

    def delete_document(self, doc_id: int, user_id: int = None):
        """删除文档的所有向量"""
        collection_name = f"user_{user_id}_doc_{doc_id}" if user_id else f"doc_{doc_id}"
        try:
            self.client.delete_collection(collection_name)
        except Exception:
            pass

    def get_document_count(self, doc_id: int, user_id: int = None) -> int:
        """获取文档的向量数量"""
        collection_name = f"user_{user_id}_doc_{doc_id}" if user_id else f"doc_{doc_id}"
        try:
            collection = self.client.get_collection(collection_name)
            return collection.count()
        except Exception:
            return 0
