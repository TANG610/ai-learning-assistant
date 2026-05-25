"""
测试：DocumentDAO
使用 SQLite 内存数据库
"""
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
import sqlite3
import config


@pytest.fixture
def test_db():
    """创建临时文件数据库用于测试"""
    import tempfile, os
    tmp = tempfile.mktemp(suffix='.db')
    original_path = config.DATABASE_PATH
    config.DATABASE_PATH = Path(tmp)

    from backend.models.database import init_db, get_db, run_migrations
    init_db()
    run_migrations()
    yield
    config.DATABASE_PATH = original_path
    try:
        os.unlink(tmp)
        os.unlink(tmp + '-wal')
        os.unlink(tmp + '-shm')
    except:
        pass


class TestDocumentDAO:
    def test_create_document(self, test_db):
        from backend.models.database import DocumentDAO
        doc_id = DocumentDAO.create("test.pdf", "pdf", "/tmp/test.pdf", 1024)
        assert doc_id > 0

        doc = DocumentDAO.get_by_id(doc_id)
        assert doc is not None
        assert doc["filename"] == "test.pdf"
        assert doc["file_type"] == "pdf"
        assert doc["status"] == "uploaded"

    def test_get_all(self, test_db):
        from backend.models.database import DocumentDAO
        DocumentDAO.create("doc1.pdf", "pdf", "/tmp/doc1.pdf")
        DocumentDAO.create("doc2.md", "md", "/tmp/doc2.md")

        docs = DocumentDAO.get_all()
        assert len(docs) == 2

    def test_update_status(self, test_db):
        from backend.models.database import DocumentDAO
        doc_id = DocumentDAO.create("test.pdf", "pdf", "/tmp/test.pdf")
        DocumentDAO.update_status(doc_id, "parsed", chunk_count=5)

        doc = DocumentDAO.get_by_id(doc_id)
        assert doc["status"] == "parsed"
        assert doc["chunk_count"] == 5

    def test_delete(self, test_db):
        from backend.models.database import DocumentDAO
        doc_id = DocumentDAO.create("test.pdf", "pdf", "/tmp/test.pdf")
        DocumentDAO.delete(doc_id)

        doc = DocumentDAO.get_by_id(doc_id)
        assert doc is None


class TestConversationDAO:
    def _create_user(self, user_id):
        from backend.models.database import get_db
        conn = get_db()
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, email, password_hash) VALUES (?, ?, ?, ?)",
            (user_id, f"user_{user_id}", f"user_{user_id}@example.test", "hash"),
        )
        conn.commit()
        conn.close()
        return user_id

    def test_create_conversation(self, test_db):
        from backend.models.database import ConversationDAO
        conv_id = ConversationDAO.create(title="测试对话")
        assert conv_id > 0

        convs = ConversationDAO.get_all()
        assert len(convs) == 1
        assert convs[0]["title"] == "测试对话"

    def test_add_and_get_messages(self, test_db):
        from backend.models.database import ConversationDAO
        conv_id = ConversationDAO.create("测试对话")
        ConversationDAO.add_message(conv_id, "user", "你好")
        ConversationDAO.add_message(conv_id, "assistant", "你好！有什么可以帮你的？")

        msgs = ConversationDAO.get_messages(conv_id)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"

    def test_delete_conversation(self, test_db):
        from backend.models.database import ConversationDAO
        conv_id = ConversationDAO.create("测试对话")
        ConversationDAO.delete(conv_id)

        convs = ConversationDAO.get_all()
        assert len(convs) == 0

    def test_conversation_history_filters_by_user_and_counts_messages(self, test_db):
        from backend.models.database import ConversationDAO

        user_id = self._create_user(21)
        other_user_id = self._create_user(22)
        conv_id = ConversationDAO.create("用户对话", user_id=user_id)
        other_conv_id = ConversationDAO.create("其他用户对话", user_id=other_user_id)
        ConversationDAO.add_message(conv_id, "user", "你好", user_id=user_id)
        ConversationDAO.add_message(conv_id, "assistant", "你好", user_id=user_id)
        ConversationDAO.add_message(other_conv_id, "user", "hi", user_id=other_user_id)

        convs = ConversationDAO.get_all(user_id=user_id)

        assert len(convs) == 1
        assert convs[0]["id"] == conv_id
        assert convs[0]["message_count"] == 2
        assert ConversationDAO.get_by_id(conv_id, user_id=user_id)["title"] == "用户对话"
        assert ConversationDAO.get_by_id(conv_id, user_id=other_user_id) is None


class TestCollectorDAO:
    def _create_user(self):
        from backend.models.database import get_db
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            ("collector_user", "collector@example.test", "hash"),
        )
        user_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return user_id

    def test_collector_task_roundtrip(self, test_db):
        from backend.models.database import CollectorTaskDAO, MediaSourceDAO

        user_id = self._create_user()
        source_id = MediaSourceDAO.create(
            user_id=user_id,
            name="测试采集源",
            platform="douyin",
            crawler_type="search",
            keywords="AI产品经理",
        )
        task_id = "run_test_001"
        CollectorTaskDAO.create(
            task_id=task_id,
            run_id=task_id,
            source_id=source_id,
            user_id=user_id,
            source_name="测试采集源",
            platform="douyin",
            crawler_type="search",
            started_ts=123.0,
            started_at="2026-05-24 10:00:00",
            crawler_result={"status": "ok"},
            progress={"stage": "crawling", "stage_index": 0},
        )

        CollectorTaskDAO.update(
            task_id,
            status="completed",
            imported=2,
            skipped=1,
            errors=["e1"],
            result_files=["douyin/jsonl/search_contents.jsonl"],
        )

        task = CollectorTaskDAO.get(task_id)
        assert task["status"] == "completed"
        assert task["imported"] == 2
        assert task["errors"] == ["e1"]
        assert task["result_files"] == ["douyin/jsonl/search_contents.jsonl"]

    def test_raw_collected_item_roundtrip(self, test_db):
        from backend.models.database import CollectorTaskDAO, MediaSourceDAO, RawCollectedItemDAO

        user_id = self._create_user()
        source_id = MediaSourceDAO.create(
            user_id=user_id,
            name="测试采集源",
            platform="xhs",
            crawler_type="search",
            keywords="RAG",
        )
        CollectorTaskDAO.create(
            task_id="run_test_002",
            run_id="run_test_002",
            source_id=source_id,
            user_id=user_id,
            source_name="测试采集源",
            platform="xhs",
            crawler_type="search",
            started_ts=456.0,
            started_at="2026-05-24 10:00:00",
        )

        item_id = RawCollectedItemDAO.create(
            task_id="run_test_002",
            run_id="run_test_002",
            source_id=source_id,
            user_id=user_id,
            platform="xhs",
            source_name="测试采集源",
            file_path="xhs/jsonl/search_contents.jsonl",
            record_index=0,
            record={"note_id": "n1", "title": "标题", "desc": "正文"},
            canonical_id="n1",
            url="xhs://n1",
            title="标题",
            content="正文",
        )
        RawCollectedItemDAO.update_status(item_id, "imported", article_id=7, document_id=9)

        item = RawCollectedItemDAO.get(item_id)
        assert item["status"] == "imported"
        assert item["record"]["note_id"] == "n1"
        assert item["article_id"] == 7
