-- 003: 新增AI资讯追踪功能表
-- news_articles: 资讯文章
-- rss_sources: RSS订阅源

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
    fetched_at TEXT DEFAULT (datetime('now','localtime')),
    user_id INTEGER,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

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

CREATE INDEX IF NOT EXISTS idx_news_user ON news_articles(user_id);
CREATE INDEX IF NOT EXISTS idx_news_doc ON news_articles(document_id);
CREATE INDEX IF NOT EXISTS idx_news_url ON news_articles(url);
CREATE INDEX IF NOT EXISTS idx_rss_user ON rss_sources(user_id);
