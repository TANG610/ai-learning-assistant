import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))

import pytest


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    import config
    from backend.models.database import init_db, run_migrations

    monkeypatch.setattr(config, "DATABASE_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_BACKEND", "sqlite")
    monkeypatch.setattr(config, "VECTOR_INDEX_ENABLED", False)
    monkeypatch.setattr(config, "VECTOR_BACKEND", "none")
    init_db()
    run_migrations()


def test_dedupe_transcript_sections_removes_timestamp_copy():
    from backend.services.document_service import DocumentService

    content = """视频描述:
Agent 评估方法

完整文字稿:
第一段内容。第二段内容。

带时间戳片段:
[0:00] 第一段内容。
[0:10] 第二段内容。
"""

    cleaned = DocumentService._dedupe_transcript_sections(content)

    assert "完整文字稿" in cleaned
    assert "第一段内容。第二段内容。" in cleaned
    assert "带时间戳片段" not in cleaned
    assert "[0:00]" not in cleaned


def test_dedupe_transcript_sections_keeps_timestamp_only_content():
    from backend.services.document_service import DocumentService

    content = """视频描述:
Agent 评估方法

带时间戳片段:
[0:00] 第一段内容。
"""

    assert DocumentService._dedupe_transcript_sections(content) == content


def test_build_video_rag_content_does_not_duplicate_timestamp_segments():
    from backend.services.collector_service import CollectorService

    content = CollectorService._build_video_rag_content(
        content="Agent 评估方法",
        transcript="第一段内容。第二段内容。",
        segments=[
            {"start": 0, "text": "第一段内容。"},
            {"start": 10, "text": "第二段内容。"},
        ],
        record={"tag_list": ["AI产品"]},
    )

    assert "完整文字稿" in content
    assert "第一段内容。第二段内容。" in content
    assert "带时间戳片段" not in content
    assert "[0:00]" not in content


def test_process_markdown_stores_title_path_as_metadata(test_db, tmp_path):
    from backend.models.database import DocumentDAO, get_db
    from backend.services.document_service import DocumentService

    md_file = tmp_path / "guide.md"
    md_file.write_text("# Guide\n\nIntro text.\n\n## Step One\n\nDo the first thing.", encoding="utf-8")
    doc_id = DocumentDAO.create("guide.md", "md", str(md_file))

    result = DocumentService.process_document(doc_id)

    assert result["status"] == "parsed"
    conn = get_db()
    rows = conn.execute(
        "SELECT content, title_path FROM document_chunks WHERE document_id = ? ORDER BY chunk_index",
        (doc_id,),
    ).fetchall()
    conn.close()
    assert [row["title_path"] for row in rows] == ["Guide", "Guide > Step One"]
    assert [row["content"] for row in rows] == ["Intro text.", "Do the first thing."]
    assert all("[Title Path]" not in row["content"] for row in rows)
