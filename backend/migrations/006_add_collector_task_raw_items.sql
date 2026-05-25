-- 006_add_collector_task_raw_items.sql
-- 说明: 持久化采集任务，并把原始采集记录作为独立中间层保存

CREATE TABLE IF NOT EXISTS collector_tasks (
    task_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    source_id INTEGER NOT NULL,
    user_id INTEGER,
    source_name TEXT DEFAULT '',
    platform TEXT DEFAULT '',
    crawler_type TEXT DEFAULT '',
    status TEXT DEFAULT 'running',
    started_ts REAL DEFAULT 0,
    started_at TEXT DEFAULT (datetime('now','localtime')),
    completed_at TEXT,
    stopped_at TEXT,
    imported INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    article_count INTEGER DEFAULT 0,
    progress TEXT DEFAULT '{}',
    errors TEXT DEFAULT '[]',
    result_files TEXT DEFAULT '[]',
    crawler_result TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (source_id) REFERENCES media_sources(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS raw_collected_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    user_id INTEGER,
    platform TEXT DEFAULT '',
    source_name TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    record_index INTEGER DEFAULT 0,
    canonical_id TEXT DEFAULT '',
    url TEXT DEFAULT '',
    title TEXT DEFAULT '',
    content TEXT DEFAULT '',
    record_json TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    skip_reason TEXT DEFAULT '',
    error TEXT DEFAULT '',
    article_id INTEGER,
    document_id INTEGER,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    FOREIGN KEY (task_id) REFERENCES collector_tasks(task_id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES media_sources(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE(task_id, file_path, record_index)
);

CREATE INDEX IF NOT EXISTS idx_collector_tasks_user ON collector_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_collector_tasks_status ON collector_tasks(status);
CREATE INDEX IF NOT EXISTS idx_raw_items_task ON raw_collected_items(task_id);
CREATE INDEX IF NOT EXISTS idx_raw_items_status ON raw_collected_items(status);
