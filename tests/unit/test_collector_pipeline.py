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
    original_data_dir = config.DATA_DIR
    config.DATABASE_PATH = Path(tmp)
    config.DATA_DIR = Path(tempfile.mkdtemp())

    from backend.models.database import init_db, run_migrations

    init_db()
    run_migrations()
    yield

    config.DATABASE_PATH = original_path
    config.DATA_DIR = original_data_dir
    try:
        os.unlink(tmp)
        os.unlink(tmp + "-wal")
        os.unlink(tmp + "-shm")
    except OSError:
        pass


def test_import_from_crawl_persists_raw_then_imports(monkeypatch, test_db):
    from backend.models.database import (
        CollectorTaskDAO,
        MediaSourceDAO,
        NewsDAO,
        RawCollectedItemDAO,
        get_db,
    )
    from backend.services.collector_service import CollectorService, _collect_tasks

    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
        ("pipeline_user", "pipeline@example.test", "hash"),
    )
    user_id = cursor.lastrowid
    conn.commit()
    conn.close()

    source_id = MediaSourceDAO.create(
        user_id=user_id,
        name="抖音测试源",
        platform="douyin",
        crawler_type="search",
        keywords="AI产品经理",
        max_results=1,
    )
    task_id = "run_pipeline_001"
    CollectorTaskDAO.create(
        task_id=task_id,
        run_id=task_id,
        source_id=source_id,
        user_id=user_id,
        source_name="抖音测试源",
        platform="douyin",
        crawler_type="search",
        started_ts=100.0,
        started_at="2026-05-24 10:00:00",
    )
    _collect_tasks.clear()

    monkeypatch.setattr(
        CollectorService,
        "list_data_files",
        staticmethod(lambda: [
            {
                "path": "douyin/jsonl/search_contents_2026-05-24.jsonl",
                "name": "search_contents_2026-05-24.jsonl",
                "modified_at": 120.0,
            }
        ]),
    )
    monkeypatch.setattr(
        CollectorService,
        "read_data_file",
        staticmethod(lambda path: [
            {
                "aweme_id": "a1",
                "title": "AI产品经理面试",
                "desc": "这是一段足够长的产品经理知识内容，用于进入知识库。",
                "aweme_url": "https://example.test/a1",
                "nickname": "作者A",
            }
        ]),
    )

    def fake_import_text(title, content, user_id=None, file_category="news"):
        from backend.models.database import DocumentDAO

        doc_id = DocumentDAO.create(
            title,
            "txt",
            str(Path("fake_import.txt")),
            len(content.encode("utf-8")),
            user_id=user_id,
            file_category=file_category,
        )
        DocumentDAO.update_status(doc_id, "parsed", chunk_count=1)
        return {"doc_id": doc_id, "chunks": 1, "status": "parsed"}

    monkeypatch.setattr(
        "backend.services.collector_service.DocumentService.import_text",
        staticmethod(fake_import_text),
    )
    monkeypatch.setattr(
        "backend.services.collector_service.NewsService.summarize_article",
        staticmethod(lambda title, content: {
            "summary": "摘要",
            "key_points": ["要点"],
            "topics": ["AI产品"],
        }),
    )
    monkeypatch.setattr(
        "backend.services.collector_service.save_transcript_file",
        lambda **kwargs: None,
    )

    result = CollectorService.import_from_crawl(task_id, user_id=user_id)

    assert result["imported"] == 1
    assert result["skipped"] == 0

    task = CollectorTaskDAO.get(task_id)
    assert task["status"] == "completed"
    assert task["result_files"] == ["douyin/jsonl/search_contents_2026-05-24.jsonl"]

    raw_items = RawCollectedItemDAO.list_by_task(task_id)
    assert len(raw_items) == 1
    assert raw_items[0]["status"] == "imported"
    assert raw_items[0]["canonical_id"] == "a1"

    article = NewsDAO.get_by_url("https://example.test/a1", user_id=user_id)
    assert article is not None
    assert article["document_id"] is not None
