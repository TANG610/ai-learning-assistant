import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

import jwt
import pytest
from flask import Flask


@pytest.fixture
def test_db():
    import os
    import tempfile
    import config

    tmp = tempfile.mktemp(suffix=".db")
    original_path = config.DATABASE_PATH
    config.DATABASE_PATH = Path(tmp)

    from models.database import init_db, run_migrations

    init_db()
    run_migrations()
    yield

    config.DATABASE_PATH = original_path
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(tmp + suffix)
        except OSError:
            pass


@pytest.fixture
def client(test_db):
    from routes.chat_routes import chat_bp

    app = Flask(__name__)
    app.register_blueprint(chat_bp)
    return app.test_client()


def _create_user(user_id):
    from models.database import get_db

    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, email, password_hash) VALUES (?, ?, ?, ?)",
        (user_id, f"user_{user_id}", f"user_{user_id}@example.test", "hash"),
    )
    conn.commit()
    conn.close()
    return user_id


def _auth_headers(user_id):
    import config

    token = jwt.encode({"user_id": user_id, "username": f"user_{user_id}"}, config.JWT_SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {token}"}


def test_conversation_history_routes_persist_and_scope_by_user(client):
    from models.database import ConversationDAO

    user_id = _create_user(31)
    other_user_id = _create_user(32)
    conv_id = ConversationDAO.create("第一段对话", user_id=user_id)
    other_conv_id = ConversationDAO.create("别人的对话", user_id=other_user_id)
    ConversationDAO.add_message(conv_id, "user", "你好", user_id=user_id)
    ConversationDAO.add_message(conv_id, "assistant", "你好，有什么可以帮你？", user_id=user_id)
    ConversationDAO.add_message(other_conv_id, "user", "secret", user_id=other_user_id)

    listed = client.get("/api/conversations", headers=_auth_headers(user_id))

    assert listed.status_code == 200
    conversations = listed.get_json()["conversations"]
    assert [c["id"] for c in conversations] == [conv_id]
    assert conversations[0]["message_count"] == 2

    detail = client.get(f"/api/conversations/{conv_id}", headers=_auth_headers(user_id))
    blocked = client.get(f"/api/conversations/{other_conv_id}", headers=_auth_headers(user_id))

    assert detail.status_code == 200
    body = detail.get_json()
    assert body["conversation"]["title"] == "第一段对话"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert blocked.status_code == 404

    blocked_delete = client.delete(f"/api/conversations/{other_conv_id}", headers=_auth_headers(user_id))
    own_delete = client.delete(f"/api/conversations/{conv_id}", headers=_auth_headers(user_id))

    assert blocked_delete.status_code == 404
    assert own_delete.status_code == 200
    assert client.get("/api/conversations", headers=_auth_headers(user_id)).get_json()["conversations"] == []


def test_chat_null_document_id_searches_all_documents(client, monkeypatch):
    import routes.chat_routes as chat_routes
    from models.database import ConversationDAO

    user_id = _create_user(41)
    conv_id = ConversationDAO.create("All knowledge", user_id=user_id)
    calls = []

    def fake_search(query, doc_id=None, top_k=5, user_id=None):
        calls.append({"query": query, "doc_id": doc_id, "top_k": top_k, "user_id": user_id})
        return [
            {
                "text": "Chunk from document A",
                "score": 0.91,
                "rerank_score": 0.91,
                "doc_id": 101,
                "chunk_index": 0,
                "retrieval_sources": ["keyword"],
            },
            {
                "text": "Chunk from document B",
                "score": 0.82,
                "rerank_score": 0.82,
                "doc_id": 102,
                "chunk_index": 1,
                "retrieval_sources": ["vector"],
            },
        ]

    monkeypatch.setattr(chat_routes.DocumentService, "search_documents", staticmethod(fake_search))
    monkeypatch.setattr(chat_routes.llm_service, "chat", lambda *args, **kwargs: "answer")
    monkeypatch.setattr(chat_routes, "_get_doc_name", lambda doc_id: f"doc-{doc_id}")

    response = client.post(
        f"/api/conversations/{conv_id}/messages",
        json={"message": "search all", "document_id": None, "stream": False},
        headers=_auth_headers(user_id),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert calls == [{"query": "search all", "doc_id": None, "top_k": chat_routes.RAG_TOP_K, "user_id": user_id}]
    assert body["retrieval_debug"]["search_scope"] == "all_documents"
    assert body["retrieval_debug"]["document_id"] is None
    assert body["source_count"] == 2
    assert {source["doc_id"] for source in body["sources"]} == {101, 102}
