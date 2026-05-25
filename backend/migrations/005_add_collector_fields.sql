-- 005_add_collector_fields.sql
-- 日期: 2026-05-18
-- 说明: 为 MediaCrawler 集成扩展数据模型

-- 1. news_articles 新增字段
ALTER TABLE news_articles ADD COLUMN media_type TEXT DEFAULT 'text';
ALTER TABLE news_articles ADD COLUMN media_url TEXT DEFAULT '';
ALTER TABLE news_articles ADD COLUMN transcript TEXT DEFAULT '';

-- 2. 移除 news_articles.source_type 旧 CHECK 约束 (SQLite 不支持 ALTER CHECK)
--    方案: 创建新表 → 复制数据 → 删旧表 → 重命名
CREATE TABLE IF NOT EXISTS news_articles_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    source_name TEXT DEFAULT '',
    source_type TEXT DEFAULT 'manual' CHECK(source_type IN ('manual','rss','digest','xhs_api','douyin_api')),
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
    media_type TEXT DEFAULT 'text',
    media_url TEXT DEFAULT '',
    transcript TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

INSERT OR IGNORE INTO news_articles_new (
    id, document_id, title, url, source_name, source_type, language,
    summary, key_points, topics, is_read, is_bookmarked, published_at,
    content, fetched_at, user_id, media_type, media_url, transcript, created_at
) SELECT
    id, document_id, title, url, source_name, source_type, language,
    summary, key_points, topics, is_read, is_bookmarked, published_at,
    content, fetched_at, user_id, media_type, media_url, transcript, created_at
FROM news_articles;

DROP TABLE news_articles;

ALTER TABLE news_articles_new RENAME TO news_articles;

-- 重建索引
CREATE INDEX IF NOT EXISTS idx_news_user ON news_articles(user_id);
CREATE INDEX IF NOT EXISTS idx_news_doc ON news_articles(document_id);
CREATE INDEX IF NOT EXISTS idx_news_url ON news_articles(url);

-- 3. rss_sources 新增字段
ALTER TABLE rss_sources ADD COLUMN source_platform TEXT DEFAULT 'rss';

-- 4. 新建采集源表
CREATE TABLE IF NOT EXISTS media_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    crawler_type TEXT DEFAULT 'search',
    keywords TEXT DEFAULT '',
    creator_ids TEXT DEFAULT '',
    login_type TEXT DEFAULT 'qrcode',
    cookies TEXT DEFAULT '',
    enable_comments INTEGER DEFAULT 1,
    max_results INTEGER DEFAULT 1,
    is_active INTEGER DEFAULT 1,
    last_fetched_at TEXT,
    article_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_media_sources_user ON media_sources(user_id);
