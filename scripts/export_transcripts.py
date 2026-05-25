"""
一次性迁移脚本：从 SQLite news_articles 导出全部文字稿到 data/transcripts/

用法: python scripts/export_transcripts.py
"""
import sys
from pathlib import Path

# 确保项目根目录和 backend 在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import sqlite3
from services.transcript_file_service import save_transcript_file


def main():
    db_path = PROJECT_ROOT / "data" / "learning.db"
    if not db_path.exists():
        print(f"数据库不存在: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, source_name, media_type, url, fetched_at, content, transcript "
        "FROM news_articles ORDER BY id"
    ).fetchall()
    conn.close()

    print(f"共 {len(rows)} 条记录待导出")
    exported = 0
    skipped = 0

    for row in rows:
        path = save_transcript_file(
            article_id=row["id"],
            title=row["title"] or "",
            source_name=row["source_name"] or "",
            media_type=row["media_type"] or "text",
            url=row["url"] or "",
            fetched_at=row["fetched_at"] or "",
            content=row["content"] or "",
            transcript=row["transcript"] or "",
        )
        if path:
            exported += 1
            print(f"  ✅ id={row['id']}: {path.name}")
        else:
            skipped += 1
            print(f"  ⏭️ id={row['id']}: 无内容，跳过")

    print(f"\n完成: 导出 {exported} 条, 跳过 {skipped} 条")


if __name__ == "__main__":
    main()
