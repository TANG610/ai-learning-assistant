import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

import pytest


@pytest.fixture
def test_db():
    import os
    import tempfile
    import config

    tmp = tempfile.mktemp(suffix=".db")
    original_path = config.DATABASE_PATH
    config.DATABASE_PATH = Path(tmp)

    from backend.models.database import init_db, run_migrations

    init_db()
    run_migrations()
    yield

    config.DATABASE_PATH = original_path
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(tmp + suffix)
        except OSError:
            pass


def _create_doc_with_chunks(filename, chunks, user_id=7):
    from backend.models.database import DocumentDAO, get_db

    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, email, password_hash) VALUES (?, ?, ?, ?)",
        (user_id, f"user_{user_id}", f"user_{user_id}@example.test", "hash"),
    )
    conn.commit()
    conn.close()

    doc_id = DocumentDAO.create(filename, "txt", f"/tmp/{filename}", user_id=user_id)
    conn = get_db()
    for index, content in enumerate(chunks):
        conn.execute(
            "INSERT INTO document_chunks (document_id, chunk_index, content, vector_id, user_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (doc_id, index, content, f"doc_{doc_id}_chunk_{index}", user_id),
        )
    conn.commit()
    conn.close()
    return doc_id


def test_keyword_route_recalls_chunk_when_vector_route_is_empty(monkeypatch, test_db):
    from backend.services.document_service import DocumentService

    doc_id = _create_doc_with_chunks(
        "agent_eval.txt",
        [
            "Agent评估需要看任务成功率、工具调用准确率、幻觉率和多轮稳定性。",
            "这是一个完全无关的个人学习计划片段。",
        ],
    )
    monkeypatch.setattr(DocumentService, "_safe_vector_search", staticmethod(lambda *args, **kwargs: []))

    results = DocumentService.search_documents("Agent评估要看什么指标", top_k=3, user_id=7)

    assert results
    assert results[0]["doc_id"] == doc_id
    assert results[0]["chunk_index"] == 0
    assert results[0]["retrieval_sources"] == ["keyword"]
    assert results[0]["keyword_score"] > 0


def test_rerank_prefers_dual_route_over_vector_only_match(monkeypatch, test_db):
    from backend.services.document_service import DocumentService

    doc_id = _create_doc_with_chunks(
        "rag_vs_finetune.txt",
        [
            "RAG适合知识频繁变化的场景，因为它先检索外部知识，再交给大模型生成回答。",
            "微调会调整模型参数，更适合稳定改变模型风格、格式或任务行为。",
        ],
    )
    other_doc_id = _create_doc_with_chunks(
        "generic_ai.txt",
        ["这段内容泛泛讨论AI学习助手，但没有解释RAG和微调的区别。"],
    )

    def fake_vector_search(query, scoped_doc_id=None, top_k=5, user_id=None):
        return [
            {
                "text": "这段内容泛泛讨论AI学习助手，但没有解释RAG和微调的区别。",
                "score": 0.62,
                "distance": 0.38,
                "doc_id": other_doc_id,
                "chunk_index": 0,
            },
            {
                "text": "RAG适合知识频繁变化的场景，因为它先检索外部知识，再交给大模型生成回答。",
                "score": 0.46,
                "distance": 0.54,
                "doc_id": doc_id,
                "chunk_index": 0,
            },
        ]

    monkeypatch.setattr(DocumentService, "_safe_vector_search", staticmethod(fake_vector_search))

    results = DocumentService.search_documents("RAG为什么适合知识频繁变化", top_k=2, user_id=7)

    assert results[0]["doc_id"] == doc_id
    assert results[0]["chunk_index"] == 0
    assert set(results[0]["retrieval_sources"]) == {"vector", "keyword"}
    assert results[0]["rerank_score"] > results[1]["rerank_score"]


def test_keyword_route_respects_document_scope(monkeypatch, test_db):
    from backend.services.document_service import DocumentService

    scoped_doc_id = _create_doc_with_chunks(
        "scoped.txt",
        ["RAG在企业知识库问答中可以减少模型重新训练成本。"],
    )
    _create_doc_with_chunks(
        "outside.txt",
        ["RAG在另一个文档里也出现了，但单文档检索不应该返回它。"],
    )
    monkeypatch.setattr(DocumentService, "_safe_vector_search", staticmethod(lambda *args, **kwargs: []))

    results = DocumentService.search_documents("RAG企业知识库", doc_id=scoped_doc_id, top_k=5, user_id=7)

    assert results
    assert {item["doc_id"] for item in results} == {scoped_doc_id}
