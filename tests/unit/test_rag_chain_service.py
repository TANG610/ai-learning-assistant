import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))


class FakeDocument:
    def __init__(self, page_content, metadata=None):
        self.page_content = page_content
        self.metadata = metadata or {}


def test_hybrid_retriever_adapter_converts_results_to_documents(monkeypatch):
    from services.rag_chain_service import HybridRetrieverAdapter
    from services.document_service import DocumentService

    def fake_hybrid_search(query, doc_id=None, top_k=5, user_id=None):
        assert query == "what is rag"
        assert doc_id == 12
        assert top_k == 2
        assert user_id == 7
        return [
            {
                "text": "RAG retrieves external knowledge before generation.",
                "score": 0.88,
                "rerank_score": 0.88,
                "vector_score": 0.7,
                "keyword_score": 0.6,
                "bm25_score": -1.2,
                "retrieval_sources": ["vector", "keyword"],
                "matched_terms": ["rag"],
                "doc_id": 12,
                "chunk_index": 3,
            }
        ]

    monkeypatch.setattr(DocumentService, "hybrid_search_documents", staticmethod(fake_hybrid_search))

    adapter = HybridRetrieverAdapter(
        document_id=12,
        top_k=2,
        user_id=7,
        score_threshold=0.3,
        doc_name_resolver=lambda doc_id: f"doc-{doc_id}",
    )
    docs = adapter.search("what is rag", document_cls=FakeDocument)

    assert len(docs) == 1
    assert docs[0].page_content.startswith("RAG retrieves")
    assert docs[0].metadata["doc_id"] == 12
    assert docs[0].metadata["chunk_index"] == 3
    assert docs[0].metadata["retrieval_sources"] == ["vector", "keyword"]
    assert adapter.last_sources[0]["doc_name"] == "doc-12"
    assert adapter.build_debug("what is rag")["accepted_count"] == 1


def test_hybrid_retriever_adapter_respects_context_limit(monkeypatch):
    from services.rag_chain_service import HybridRetrieverAdapter
    from services.document_service import DocumentService

    monkeypatch.setattr(
        DocumentService,
        "hybrid_search_documents",
        staticmethod(lambda *args, **kwargs: [
            {"text": "abcdef", "score": 0.9, "doc_id": 1, "chunk_index": 0},
            {"text": "ghijkl", "score": 0.8, "doc_id": 1, "chunk_index": 1},
        ]),
    )

    adapter = HybridRetrieverAdapter(context_max_chars=8, score_threshold=0.3)
    docs = adapter.search("query", document_cls=FakeDocument)

    assert [doc.page_content for doc in docs] == ["abcdef", "gh"]
    assert adapter.last_sources[1]["reason"] == "truncated_to_context_limit"
