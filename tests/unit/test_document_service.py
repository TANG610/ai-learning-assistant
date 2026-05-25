import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "backend"))


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
