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
    from routes.quiz_routes import quiz_bp

    app = Flask(__name__)
    app.register_blueprint(quiz_bp)
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


def _create_parsed_doc(filename, content, user_id):
    from models.database import DocumentDAO, get_db

    doc_id = DocumentDAO.create(filename, "md", f"/tmp/{filename}", len(content), user_id=user_id)
    DocumentDAO.update_status(doc_id, "parsed", chunk_count=1)
    conn = get_db()
    conn.execute(
        "INSERT INTO document_chunks (document_id, chunk_index, content, user_id) VALUES (?, ?, ?, ?)",
        (doc_id, 0, content, user_id),
    )
    conn.commit()
    conn.close()
    return doc_id


def test_create_assessment_from_all_knowledge_base(client, monkeypatch):
    import routes.quiz_routes as quiz_routes

    user_id = _create_user(51)
    doc_a = _create_parsed_doc("a.md", "Alpha knowledge", user_id)
    doc_b = _create_parsed_doc("b.md", "Beta knowledge", user_id)
    seen = {}

    def fake_generate(content, count):
        seen["content"] = content
        seen["count"] = count
        return {
            "questions": [
                {
                    "type": "choice",
                    "question": "Which item appears?",
                    "options": {"A": "Alpha", "B": "Gamma"},
                    "answer": "A",
                    "explanation": "Alpha is present.",
                    "knowledge_point": "combined",
                    "difficulty": "easy",
                }
            ]
        }

    monkeypatch.setattr(quiz_routes.llm, "generate_assessment", fake_generate)
    monkeypatch.setattr(quiz_routes.llm, "extract_knowledge_points", lambda content: [{"name": "combined"}])

    response = client.post(
        "/api/assessments",
        json={"document_id": None, "question_count": 4},
        headers=_auth_headers(user_id),
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["document_id"] in {doc_a, doc_b}
    assert set(body["source_document_ids"]) == {doc_a, doc_b}
    assert body["scope_label"] == "全部知识库"
    assert "Alpha knowledge" in seen["content"]
    assert "Beta knowledge" in seen["content"]
    assert seen["count"] == 4
