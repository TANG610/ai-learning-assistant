"""
清空 learning.db 中知识库相关表，保留用户和设置
"""
import sqlite3

DB_PATH = "data/learning.db"

# 要清空的表（按外键依赖顺序）
TABLES_TO_CLEAR = [
    "assessment_questions",
    "assessments",
    "weekly_reports",
    "learning_progress",
    "study_sessions",
    "knowledge_points",
    "messages",
    "conversations",
    "document_chunks",
    "documents",
    "news_articles",
]

# 保留的表：users, user_settings, media_sources, rss_sources, sqlite_sequence

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# 关闭外键检查，避免删除顺序问题
c.execute("PRAGMA foreign_keys = OFF")

for table in TABLES_TO_CLEAR:
    c.execute(f"DELETE FROM {table}")
    print(f"  Cleared: {table}")

# 重置自增ID
c.execute("DELETE FROM sqlite_sequence WHERE name IN ({})".format(
    ",".join(f"'{t}'" for t in TABLES_TO_CLEAR)
))
print("  Reset auto-increment IDs")

c.execute("PRAGMA foreign_keys = ON")
conn.commit()
conn.close()

print("\nDone. Users, user_settings, media_sources preserved.")
