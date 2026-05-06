"""
SQLite 数据模型与初始化
"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
import config
from backend.utils.logger import log


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(str(config.DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _column_exists(conn, table_name, column_name):
    """检查表中是否存在某列"""
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(r[1] == column_name for r in rows)


def run_migrations():
    """执行数据库迁移"""
    migration_dir = config.BASE_DIR / "backend" / "migrations"
    if not migration_dir.exists():
        return

    conn = get_db()
    try:
        for sql_file in sorted(migration_dir.glob("*.sql")):
            log.info(f"执行迁移: {sql_file.name}")
            sql = sql_file.read_text(encoding="utf-8")

            # 逐条执行（跳过因列已存在导致的错误）
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if not stmt:
                    continue
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    err_msg = str(e).lower()
                    if "duplicate column" in err_msg or "already exists" in err_msg:
                        log.debug(f"跳过（列已存在）: {stmt[:60]}...")
                    else:
                        log.warning(f"迁移语句执行失败: {e} | SQL: {stmt[:80]}...")

        conn.commit()
        log.info("迁移执行完毕")
    except Exception as e:
        log.error(f"迁移失败: {e}")
        raise
    finally:
        conn.close()


def init_db():
    """初始化数据库表结构"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        -- 文档表：记录上传的学习资料
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            chunk_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'uploaded',
            file_category TEXT DEFAULT 'text',
            ocr_text TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 文档片段表：解析后的文本块
        CREATE TABLE IF NOT EXISTS document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            vector_id TEXT,
            user_id INTEGER,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        -- 对话会话表
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT DEFAULT '新对话',
            document_id INTEGER,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (document_id) REFERENCES documents(id)
        );

        -- 对话消息表
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
            content TEXT NOT NULL,
            source_chunks TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        -- 学习进度表
        CREATE TABLE IF NOT EXISTS learning_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            status TEXT DEFAULT 'not_started' CHECK(status IN ('not_started', 'in_progress', 'completed', 'review_needed')),
            notes TEXT DEFAULT '',
            confidence_score REAL DEFAULT 0.0,
            question_count INTEGER DEFAULT 0,
            last_studied_at TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        -- 学习记录表（细粒度）
        CREATE TABLE IF NOT EXISTS study_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            session_type TEXT DEFAULT 'qa' CHECK(session_type IN ('qa', 'review', 'practice', 'report')),
            duration_minutes INTEGER DEFAULT 0,
            questions_asked INTEGER DEFAULT 0,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        -- 知识点表：追踪掌握状态
        CREATE TABLE IF NOT EXISTS knowledge_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            topic TEXT NOT NULL,
            mastery_level TEXT DEFAULT 'unknown' CHECK(mastery_level IN ('unknown', 'learning', 'familiar', 'mastered', 'weak')),
            mastery_score REAL DEFAULT 0.0,
            encounter_count INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0,
            last_encountered_at TEXT,
            notes TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        -- 测评表：每次测评会话
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed')),
            total_questions INTEGER DEFAULT 0,
            correct_count INTEGER DEFAULT 0,
            score REAL DEFAULT 0.0,
            knowledge_summary TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            completed_at TEXT,
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        -- 测评题目表
        CREATE TABLE IF NOT EXISTS assessment_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assessment_id INTEGER NOT NULL,
            question_type TEXT NOT NULL CHECK(question_type IN ('choice', 'multi_choice', 'true_false', 'short_answer')),
            question_text TEXT NOT NULL,
            options TEXT,
            correct_answer TEXT NOT NULL,
            explanation TEXT DEFAULT '',
            knowledge_point TEXT DEFAULT '',
            difficulty TEXT DEFAULT 'medium' CHECK(difficulty IN ('easy', 'medium', 'hard')),
            user_answer TEXT DEFAULT '',
            is_correct INTEGER DEFAULT -1,
            score REAL DEFAULT 0.0,
            ai_feedback TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
        );

        -- 周报表
        CREATE TABLE IF NOT EXISTS weekly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT NOT NULL,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            total_study_time INTEGER DEFAULT 0,
            total_questions INTEGER DEFAULT 0,
            documents_studied INTEGER DEFAULT 0,
            content TEXT NOT NULL,
            file_path TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 用户表
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        -- 资讯文章表
        CREATE TABLE IF NOT EXISTS news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER,
            title TEXT NOT NULL,
            url TEXT NOT NULL UNIQUE,
            source_name TEXT DEFAULT '',
            source_type TEXT DEFAULT 'manual' CHECK(source_type IN ('manual','rss','digest')),
            language TEXT DEFAULT 'zh' CHECK(language IN ('zh','en','unknown')),
            summary TEXT DEFAULT '',
            key_points TEXT DEFAULT '',
            topics TEXT DEFAULT '',
            is_read INTEGER DEFAULT 0,
            is_bookmarked INTEGER DEFAULT 0,
            published_at TEXT,
            content TEXT DEFAULT '',
            fetched_at TEXT DEFAULT (datetime('now','localtime')),
            user_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        -- RSS订阅源表
        CREATE TABLE IF NOT EXISTS rss_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            language TEXT DEFAULT 'zh',
            is_active INTEGER DEFAULT 1,
            last_fetched_at TEXT,
            article_count INTEGER DEFAULT 0,
            user_id INTEGER,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        -- 用户设置表
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            preferences TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        -- 索引
        CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id);
        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_progress_doc ON learning_progress(document_id);
        CREATE INDEX IF NOT EXISTS idx_knowledge_doc ON knowledge_points(document_id);
        CREATE INDEX IF NOT EXISTS idx_sessions_doc ON study_sessions(document_id);
        CREATE INDEX IF NOT EXISTS idx_reports_date ON weekly_reports(week_start);
        CREATE INDEX IF NOT EXISTS idx_assessments_doc ON assessments(document_id);
        CREATE INDEX IF NOT EXISTS idx_aq_assessment ON assessment_questions(assessment_id);
        CREATE INDEX IF NOT EXISTS idx_news_user ON news_articles(user_id);
        CREATE INDEX IF NOT EXISTS idx_news_doc ON news_articles(document_id);
        CREATE INDEX IF NOT EXISTS idx_news_url ON news_articles(url);
        CREATE INDEX IF NOT EXISTS idx_rss_user ON rss_sources(user_id);
    """)

    conn.commit()
    conn.close()


# ============ 数据操作层 ============

class DocumentDAO:
    """文档数据操作"""

    @staticmethod
    def create(filename, file_type, file_path, file_size=0, user_id=None, file_category='text'):
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO documents (filename, file_type, file_path, file_size, user_id, file_category) VALUES (?, ?, ?, ?, ?, ?)",
            (filename, file_type, str(file_path), file_size, user_id, file_category)
        )
        doc_id = cursor.lastrowid
        # 自动创建学习进度记录
        conn.execute(
            "INSERT INTO learning_progress (document_id, user_id) VALUES (?, ?)",
            (doc_id, user_id)
        )
        conn.commit()
        conn.close()
        return doc_id

    @staticmethod
    def get_all(user_id=None):
        conn = get_db()
        if user_id:
            rows = conn.execute(
                "SELECT d.*, lp.status as progress_status, lp.confidence_score "
                "FROM documents d LEFT JOIN learning_progress lp ON d.id = lp.document_id "
                "WHERE d.user_id = ? "
                "ORDER BY d.created_at DESC",
                (user_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT d.*, lp.status as progress_status, lp.confidence_score "
                "FROM documents d LEFT JOIN learning_progress lp ON d.id = lp.document_id "
                "ORDER BY d.created_at DESC"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def get_by_id(doc_id):
        conn = get_db()
        row = conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def update_status(doc_id, status, chunk_count=0):
        conn = get_db()
        conn.execute(
            "UPDATE documents SET status=?, chunk_count=?, updated_at=datetime('now','localtime') WHERE id=?",
            (status, chunk_count, doc_id)
        )
        conn.commit()
        conn.close()

    @staticmethod
    def delete(doc_id):
        conn = get_db()
        conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        conn.commit()
        conn.close()


class ConversationDAO:
    """对话数据操作"""

    @staticmethod
    def create(title="新对话", document_id=None, user_id=None):
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO conversations (title, document_id, user_id) VALUES (?, ?, ?)",
            (title, document_id, user_id)
        )
        conv_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return conv_id

    @staticmethod
    def get_all(user_id=None):
        conn = get_db()
        if user_id:
            rows = conn.execute(
                "SELECT c.*, COUNT(m.id) as message_count "
                "FROM conversations c LEFT JOIN messages m ON c.id = m.conversation_id "
                "WHERE c.user_id = ? "
                "GROUP BY c.id ORDER BY c.updated_at DESC",
                (user_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT c.*, COUNT(m.id) as message_count "
                "FROM conversations c LEFT JOIN messages m ON c.id = m.conversation_id "
                "GROUP BY c.id ORDER BY c.updated_at DESC"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def get_messages(conv_id):
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
            (conv_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def add_message(conv_id, role, content, source_chunks=None, user_id=None):
        conn = get_db()
        chunks_json = json.dumps(source_chunks) if source_chunks else None
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, source_chunks, user_id) VALUES (?, ?, ?, ?, ?)",
            (conv_id, role, content, chunks_json, user_id)
        )
        conn.execute(
            "UPDATE conversations SET updated_at=datetime('now','localtime') WHERE id=?",
            (conv_id,)
        )
        conn.commit()
        conn.close()

    @staticmethod
    def update_title(conv_id, title):
        conn = get_db()
        conn.execute("UPDATE conversations SET title=? WHERE id=?", (title, conv_id))
        conn.commit()
        conn.close()

    @staticmethod
    def delete(conv_id):
        conn = get_db()
        conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        conn.commit()
        conn.close()


class ProgressDAO:
    """学习进度数据操作"""

    @staticmethod
    def get_all(user_id=None):
        conn = get_db()
        if user_id:
            rows = conn.execute(
                "SELECT lp.*, d.filename, d.file_type "
                "FROM learning_progress lp JOIN documents d ON lp.document_id = d.id "
                "WHERE lp.user_id = ? "
                "ORDER BY lp.updated_at DESC",
                (user_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT lp.*, d.filename, d.file_type "
                "FROM learning_progress lp JOIN documents d ON lp.document_id = d.id "
                "ORDER BY lp.updated_at DESC"
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def update(doc_id, status=None, confidence=None, notes=None):
        conn = get_db()
        sets = []
        params = []
        if status is not None:
            sets.append("status=?")
            params.append(status)
        if confidence is not None:
            sets.append("confidence_score=?")
            params.append(confidence)
        if notes is not None:
            sets.append("notes=?")
            params.append(notes)
        sets.append("updated_at=datetime('now','localtime')")
        if status in ('in_progress', 'completed'):
            sets.append("last_studied_at=datetime('now','localtime')")
        params.append(doc_id)
        conn.execute(f"UPDATE learning_progress SET {', '.join(sets)} WHERE document_id=?", params)
        conn.commit()
        conn.close()

    @staticmethod
    def record_question(doc_id):
        conn = get_db()
        conn.execute(
            "UPDATE learning_progress SET question_count = question_count + 1, "
            "updated_at=datetime('now','localtime') WHERE document_id=?",
            (doc_id,)
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_stats(user_id=None):
        """获取总体学习统计"""
        conn = get_db()
        if user_id:
            total_docs = conn.execute("SELECT COUNT(*) FROM documents WHERE status='parsed' AND user_id=?", (user_id,)).fetchone()[0]
            completed = conn.execute("SELECT COUNT(*) FROM learning_progress WHERE status='completed' AND user_id=?", (user_id,)).fetchone()[0]
            review_needed = conn.execute("SELECT COUNT(*) FROM learning_progress WHERE status='review_needed' AND user_id=?", (user_id,)).fetchone()[0]
            in_progress = conn.execute("SELECT COUNT(*) FROM learning_progress WHERE status='in_progress' AND user_id=?", (user_id,)).fetchone()[0]
            total_questions = conn.execute("SELECT SUM(question_count) FROM learning_progress WHERE user_id=?", (user_id,)).fetchone()[0] or 0
            weak_points = conn.execute("SELECT COUNT(*) FROM knowledge_points WHERE mastery_level='weak' AND user_id=?", (user_id,)).fetchone()[0]
            total_assessments = conn.execute("SELECT COUNT(*) FROM assessments WHERE status='completed' AND user_id=?", (user_id,)).fetchone()[0] or 0
            avg_score = conn.execute("SELECT AVG(score) FROM assessments WHERE status='completed' AND user_id=?", (user_id,)).fetchone()[0] or 0
        else:
            total_docs = conn.execute("SELECT COUNT(*) FROM documents WHERE status='parsed'").fetchone()[0]
            completed = conn.execute("SELECT COUNT(*) FROM learning_progress WHERE status='completed'").fetchone()[0]
            review_needed = conn.execute("SELECT COUNT(*) FROM learning_progress WHERE status='review_needed'").fetchone()[0]
            in_progress = conn.execute("SELECT COUNT(*) FROM learning_progress WHERE status='in_progress'").fetchone()[0]
            total_questions = conn.execute("SELECT SUM(question_count) FROM learning_progress").fetchone()[0] or 0
            weak_points = conn.execute("SELECT COUNT(*) FROM knowledge_points WHERE mastery_level='weak'").fetchone()[0]
            total_assessments = conn.execute("SELECT COUNT(*) FROM assessments WHERE status='completed'").fetchone()[0] or 0
            avg_score = conn.execute("SELECT AVG(score) FROM assessments WHERE status='completed'").fetchone()[0] or 0
        avg_score = round(float(avg_score), 1)

        conn.close()

        # "活跃学习" = in_progress + review_needed（做过测评但分数不够的文档仍在学习中）
        active_learning = in_progress + review_needed
        # 完成率 = (completed + review_needed) / total（做过测评就算有进展）
        has_progress = completed + review_needed
        completion_rate = round(has_progress / total_docs * 100, 1) if total_docs > 0 else 0

        return {
            "total_documents": total_docs,
            "completed": completed,
            "in_progress": active_learning,  # 包含 review_needed
            "total_questions": total_questions,
            "weak_points": weak_points,
            "completion_rate": completion_rate,
            "total_assessments": total_assessments,
            "avg_score": avg_score
        }


class KnowledgeDAO:
    """知识点掌握状态"""

    @staticmethod
    def upsert(document_id, topic, mastery="learning", is_correct=None, user_id=None):
        """
        更新或插入知识点记录。
        """
        conn = get_db()
        existing = conn.execute(
            "SELECT id, encounter_count, correct_count FROM knowledge_points WHERE document_id=? AND topic=? AND user_id=?",
            (document_id, topic, user_id)
        ).fetchone()
        if existing:
            new_correct = (existing["correct_count"] or 0) + (1 if is_correct else 0)
            conn.execute(
                "UPDATE knowledge_points SET encounter_count=encounter_count+1, "
                "correct_count=?, "
                "mastery_level=?, last_encountered_at=datetime('now','localtime'), "
                "updated_at=datetime('now','localtime') WHERE id=?",
                (new_correct, mastery, existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO knowledge_points (document_id, topic, mastery_level, encounter_count, correct_count, last_encountered_at, user_id) "
                "VALUES (?, ?, ?, 1, ?, datetime('now','localtime'), ?)",
                (document_id, topic, mastery, 1 if is_correct else 0, user_id)
            )
        conn.commit()
        conn.close()

    @staticmethod
    def get_weak_points(limit=10, user_id=None):
        conn = get_db()
        if user_id:
            rows = conn.execute(
                "SELECT kp.*, d.filename FROM knowledge_points kp "
                "JOIN documents d ON kp.document_id = d.id "
                "WHERE (kp.mastery_level='weak' OR kp.encounter_count >= 3) AND kp.user_id = ? "
                "ORDER BY kp.encounter_count DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT kp.*, d.filename FROM knowledge_points kp "
                "JOIN documents d ON kp.document_id = d.id "
                "WHERE kp.mastery_level='weak' OR kp.encounter_count >= 3 "
                "ORDER BY kp.encounter_count DESC LIMIT ?",
                (limit,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


class StudySessionDAO:
    """学习会话记录"""

    @staticmethod
    def create(doc_id, session_type="qa", duration=0, questions=0, notes="", user_id=None):
        conn = get_db()
        conn.execute(
            "INSERT INTO study_sessions (document_id, session_type, duration_minutes, questions_asked, notes, user_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, session_type, duration, questions, notes, user_id)
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_week_stats(week_start, week_end, user_id=None):
        """获取指定周的学习统计"""
        conn = get_db()
        if user_id:
            row = conn.execute(
                "SELECT COALESCE(SUM(duration_minutes),0) as total_time, "
                "COALESCE(SUM(questions_asked),0) as total_questions, "
                "COUNT(DISTINCT document_id) as docs_studied "
                "FROM study_sessions WHERE created_at BETWEEN ? AND ? AND user_id=?",
                (week_start, week_end, user_id)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COALESCE(SUM(duration_minutes),0) as total_time, "
                "COALESCE(SUM(questions_asked),0) as total_questions, "
                "COUNT(DISTINCT document_id) as docs_studied "
                "FROM study_sessions WHERE created_at BETWEEN ? AND ?",
                (week_start, week_end)
            ).fetchone()
        conn.close()
        return dict(row) if row else {"total_time": 0, "total_questions": 0, "docs_studied": 0}


class ReportDAO:
    """周报数据操作"""

    @staticmethod
    def create(week_start, week_end, content, stats, file_path=None, user_id=None):
        conn = get_db()
        c = conn.execute(
            "INSERT INTO weekly_reports (report_date, week_start, week_end, "
            "total_study_time, total_questions, documents_studied, content, file_path, user_id) "
            "VALUES (datetime('now','localtime'), ?, ?, ?, ?, ?, ?, ?, ?)",
            (week_start, week_end, stats.get("total_time", 0),
             stats.get("total_questions", 0), stats.get("docs_studied", 0),
             content, str(file_path) if file_path else None, user_id)
        )
        report_id = c.lastrowid
        conn.commit()
        conn.close()
        return report_id

    @staticmethod
    def get_latest(limit=5, user_id=None):
        conn = get_db()
        if user_id:
            rows = conn.execute(
                "SELECT * FROM weekly_reports WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM weekly_reports ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


class AssessmentDAO:
    """测评数据操作"""

    @staticmethod
    def create(document_id, user_id=None):
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO assessments (document_id, user_id) VALUES (?, ?)", (document_id, user_id)
        )
        aid = cursor.lastrowid
        conn.commit()
        conn.close()
        return aid

    @staticmethod
    def get_by_id(assessment_id):
        conn = get_db()
        row = conn.execute("SELECT * FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def get_by_document(document_id, limit=10):
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM assessments WHERE document_id = ? ORDER BY created_at DESC LIMIT ?",
            (document_id, limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def update_completed(assessment_id, correct_count, score, knowledge_summary=""):
        conn = get_db()
        conn.execute(
            "UPDATE assessments SET status='completed', correct_count=?, score=?, "
            "knowledge_summary=?, completed_at=datetime('now','localtime') WHERE id=?",
            (correct_count, score, knowledge_summary, assessment_id)
        )
        conn.commit()
        conn.close()

    @staticmethod
    def update_status(assessment_id, status):
        conn = get_db()
        conn.execute(
            "UPDATE assessments SET status=? WHERE id=?", (status, assessment_id)
        )
        conn.commit()
        conn.close()

    @staticmethod
    def add_question(assessment_id, q_type, question_text, options, correct_answer,
                     explanation, knowledge_point, difficulty, sort_order):
        conn = get_db()
        conn.execute(
            "INSERT INTO assessment_questions "
            "(assessment_id, question_type, question_text, options, correct_answer, "
            "explanation, knowledge_point, difficulty, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (assessment_id, q_type, question_text, options, correct_answer,
             explanation, knowledge_point, difficulty, sort_order)
        )
        conn.commit()
        conn.close()

    @staticmethod
    def get_questions(assessment_id):
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM assessment_questions WHERE assessment_id = ? ORDER BY sort_order",
            (assessment_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def submit_answer(question_id, user_answer, is_correct, score, ai_feedback=""):
        conn = get_db()
        conn.execute(
            "UPDATE assessment_questions SET user_answer=?, is_correct=?, score=?, ai_feedback=? WHERE id=?",
            (user_answer, is_correct, score, ai_feedback, question_id)
        )
        conn.commit()
        conn.close()


class NewsDAO:
    """资讯文章数据操作"""

    @staticmethod
    def create(document_id, title, url, source_name='', source_type='manual',
               summary='', key_points='', topics='', published_at=None,
               language='zh', user_id=None, content=''):
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO news_articles (document_id, title, url, source_name, source_type, "
            "summary, key_points, topics, published_at, language, user_id, content) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (document_id, title, url, source_name, source_type,
             summary, key_points, topics, published_at, language, user_id, content)
        )
        aid = cursor.lastrowid
        conn.commit()
        conn.close()
        return aid

    @staticmethod
    def get_all(page=1, per_page=20, source_type=None, language=None,
                is_read=None, is_bookmarked=None, user_id=None,
                exclude_source_type=None):
        conn = get_db()
        where = ["n.user_id = ?"]
        params = [user_id]
        if source_type:
            where.append("n.source_type = ?")
            params.append(source_type)
        if exclude_source_type:
            where.append("n.source_type != ?")
            params.append(exclude_source_type)
        if language:
            where.append("n.language = ?")
            params.append(language)
        if is_read is not None:
            where.append("n.is_read = ?")
            params.append(is_read)
        if is_bookmarked is not None:
            where.append("n.is_bookmarked = ?")
            params.append(is_bookmarked)
        clause = " AND ".join(where)
        offset = (page - 1) * per_page
        rows = conn.execute(
            f"SELECT n.*, d.filename, d.status "
            f"FROM news_articles n LEFT JOIN documents d ON n.document_id = d.id "
            f"WHERE {clause} ORDER BY n.created_at DESC LIMIT ? OFFSET ?",
            params + [per_page, offset]
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def get_by_id(article_id):
        conn = get_db()
        row = conn.execute(
            "SELECT n.*, d.filename, d.status "
            "FROM news_articles n LEFT JOIN documents d ON n.document_id = d.id "
            "WHERE n.id = ?", (article_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def get_by_url(url, user_id=None):
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM news_articles WHERE url = ? AND user_id = ?",
            (url, user_id)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def mark_read(article_id, is_read=1):
        conn = get_db()
        conn.execute("UPDATE news_articles SET is_read = ? WHERE id = ?", (is_read, article_id))
        conn.commit()
        conn.close()

    @staticmethod
    def toggle_bookmark(article_id):
        conn = get_db()
        conn.execute(
            "UPDATE news_articles SET is_bookmarked = CASE WHEN is_bookmarked = 0 THEN 1 ELSE 0 END WHERE id = ?",
            (article_id,)
        )
        conn.commit()
        conn.close()

    @staticmethod
    def delete(article_id):
        conn = get_db()
        conn.execute("DELETE FROM news_articles WHERE id = ?", (article_id,))
        conn.commit()
        conn.close()

    @staticmethod
    def get_stats(user_id=None):
        conn = get_db()
        # 排除 RSS 原文，只统计用户可见的文章
        total = conn.execute(
            "SELECT COUNT(*) FROM news_articles WHERE user_id = ? AND source_type != 'rss'", (user_id,)
        ).fetchone()[0]
        unread = conn.execute(
            "SELECT COUNT(*) FROM news_articles WHERE user_id = ? AND is_read = 0 AND source_type != 'rss'", (user_id,)
        ).fetchone()[0]
        bookmarked = conn.execute(
            "SELECT COUNT(*) FROM news_articles WHERE user_id = ? AND is_bookmarked = 1 AND source_type != 'rss'", (user_id,)
        ).fetchone()[0]
        by_source = conn.execute(
            "SELECT source_type, COUNT(*) as cnt FROM news_articles "
            "WHERE user_id = ? AND source_type != 'rss' GROUP BY source_type", (user_id,)
        ).fetchall()
        by_language = conn.execute(
            "SELECT language, COUNT(*) as cnt FROM news_articles "
            "WHERE user_id = ? AND source_type != 'rss' GROUP BY language", (user_id,)
        ).fetchall()
        conn.close()
        return {
            "total": total,
            "unread": unread,
            "bookmarked": bookmarked,
            "by_source": {r["source_type"]: r["cnt"] for r in by_source},
            "by_language": {r["language"]: r["cnt"] for r in by_language}
        }

    @staticmethod
    def get_recent(days=7, limit=100, user_id=None):
        """获取最近N天的文章，用于生成摘要/趋势"""
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM news_articles WHERE user_id = ? "
            "AND created_at >= datetime('now', 'localtime', ?) "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, f'-{days} days', limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


class RssSourceDAO:
    """RSS订阅源数据操作"""

    @staticmethod
    def create(name, url, language='zh', user_id=None):
        conn = get_db()
        cursor = conn.execute(
            "INSERT INTO rss_sources (name, url, language, user_id) VALUES (?, ?, ?, ?)",
            (name, url, language, user_id)
        )
        sid = cursor.lastrowid
        conn.commit()
        conn.close()
        return sid

    @staticmethod
    def get_all(user_id=None):
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM rss_sources WHERE user_id = ? ORDER BY created_at",
            (user_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def get_by_id(source_id):
        conn = get_db()
        row = conn.execute("SELECT * FROM rss_sources WHERE id = ?", (source_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def get_active(user_id=None):
        conn = get_db()
        rows = conn.execute(
            "SELECT * FROM rss_sources WHERE is_active = 1 AND user_id = ?", (user_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    @staticmethod
    def update(source_id, **kwargs):
        conn = get_db()
        allowed = {'name', 'url', 'language', 'is_active', 'last_fetched_at', 'article_count'}
        sets = []
        params = []
        for k, v in kwargs.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                params.append(v)
        if not sets:
            conn.close()
            return
        params.append(source_id)
        conn.execute(f"UPDATE rss_sources SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        conn.close()

    @staticmethod
    def delete(source_id):
        conn = get_db()
        conn.execute("DELETE FROM rss_sources WHERE id = ?", (source_id,))
        conn.commit()
        conn.close()
