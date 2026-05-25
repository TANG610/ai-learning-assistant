import io
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

import pytest
from werkzeug.datastructures import FileStorage


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


def _create_user(user_id=9):
    from backend.models.database import get_db

    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, email, password_hash) VALUES (?, ?, ?, ?)",
        (user_id, f"user_{user_id}", f"user_{user_id}@example.test", "hash"),
    )
    conn.commit()
    conn.close()
    return user_id


def test_hash_upload_stream_rewinds_file():
    from backend.routes.document_routes import _hash_upload_stream

    upload = FileStorage(stream=io.BytesIO(b"same content"), filename="a.md")

    file_hash, file_size = _hash_upload_stream(upload)

    assert file_size == len(b"same content")
    assert len(file_hash) == 64
    assert upload.stream.read() == b"same content"


def test_find_duplicate_upload_detects_same_content_with_different_name(tmp_path, test_db):
    from backend.models.database import DocumentDAO
    from backend.routes.document_routes import _file_sha256, _find_duplicate_upload

    user_id = _create_user()
    existing = tmp_path / "existing.md"
    existing.write_bytes(b"same content")
    doc_id = DocumentDAO.create(
        "original.md",
        "md",
        str(existing),
        existing.stat().st_size,
        user_id=user_id,
    )
    DocumentDAO.update_status(doc_id, "parsed", chunk_count=2)

    duplicate = _find_duplicate_upload(
        "renamed.md",
        existing.stat().st_size,
        _file_sha256(existing),
        user_id,
    )

    assert duplicate is not None
    assert duplicate["id"] == doc_id


def test_find_duplicate_upload_allows_same_size_different_content(tmp_path, test_db):
    from backend.models.database import DocumentDAO
    from backend.routes.document_routes import _file_sha256, _find_duplicate_upload

    user_id = _create_user()
    existing = tmp_path / "existing.md"
    incoming = tmp_path / "incoming.md"
    existing.write_bytes(b"abc")
    incoming.write_bytes(b"xyz")
    DocumentDAO.create(
        "original.md",
        "md",
        str(existing),
        existing.stat().st_size,
        user_id=user_id,
    )

    duplicate = _find_duplicate_upload(
        "renamed.md",
        incoming.stat().st_size,
        _file_sha256(incoming),
        user_id,
    )

    assert duplicate is None


def test_get_reparse_candidates_skips_processing_documents(test_db):
    from backend.models.database import DocumentDAO
    from backend.routes.document_routes import _get_reparse_candidates

    user_id = _create_user()
    parsed_id = DocumentDAO.create("parsed.md", "md", "/tmp/parsed.md", user_id=user_id)
    error_id = DocumentDAO.create("error.md", "md", "/tmp/error.md", user_id=user_id)
    processing_id = DocumentDAO.create("processing.md", "md", "/tmp/processing.md", user_id=user_id)
    other_user_id = _create_user(10)
    other_id = DocumentDAO.create("other.md", "md", "/tmp/other.md", user_id=other_user_id)
    DocumentDAO.update_status(parsed_id, "parsed", chunk_count=3)
    DocumentDAO.update_status(error_id, "error", chunk_count=0)
    DocumentDAO.update_status(processing_id, "processing", chunk_count=1)
    DocumentDAO.update_status(other_id, "parsed", chunk_count=1)

    candidates = _get_reparse_candidates(user_id)

    assert {doc["id"] for doc in candidates} == {parsed_id, error_id}


def test_queue_reparse_document_marks_processing_without_running_worker(monkeypatch, test_db):
    from backend.models.database import DocumentDAO
    from backend.routes import document_routes

    submitted = []

    class DummyExecutor:
        def submit(self, fn, doc_id):
            submitted.append((fn, doc_id))

    monkeypatch.setattr(document_routes, "executor", DummyExecutor())
    user_id = _create_user()
    doc_id = DocumentDAO.create("parsed.md", "md", "/tmp/parsed.md", user_id=user_id)
    DocumentDAO.update_status(doc_id, "parsed", chunk_count=2)
    doc = DocumentDAO.get_by_id(doc_id)

    queued_id = document_routes._queue_reparse_document(doc)
    updated = DocumentDAO.get_by_id(doc_id)

    assert queued_id == doc_id
    assert updated["status"] == "processing"
    assert document_routes._doc_progress[doc_id]["stage"] == "queued"
    assert submitted == [(document_routes._process_in_background, doc_id)]
