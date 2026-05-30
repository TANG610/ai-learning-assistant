CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_settings (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    preferences TEXT DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    chunk_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'uploaded',
    file_category TEXT DEFAULT 'text',
    ocr_text TEXT DEFAULT NULL,
    raw_text TEXT DEFAULT '',
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    vector_id TEXT,
    embedding vector({{EMBEDDING_DIMENSION}}),
    embedding_model TEXT,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS conversations (
    id BIGSERIAL PRIMARY KEY,
    title TEXT DEFAULT '新对话',
    document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    source_chunks TEXT,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS learning_progress (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'not_started' CHECK(status IN ('not_started', 'in_progress', 'completed', 'review_needed')),
    notes TEXT DEFAULT '',
    confidence_score REAL DEFAULT 0.0,
    question_count INTEGER DEFAULT 0,
    last_studied_at TIMESTAMPTZ,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(document_id, user_id)
);

CREATE TABLE IF NOT EXISTS study_sessions (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    session_type TEXT DEFAULT 'qa' CHECK(session_type IN ('qa', 'review', 'practice', 'report')),
    duration_minutes INTEGER DEFAULT 0,
    questions_asked INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS knowledge_points (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    mastery_level TEXT DEFAULT 'unknown' CHECK(mastery_level IN ('unknown', 'learning', 'familiar', 'mastered', 'weak')),
    mastery_score REAL DEFAULT 0.0,
    encounter_count INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    last_encountered_at TIMESTAMPTZ,
    notes TEXT DEFAULT '',
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS assessments (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    source_document_ids TEXT DEFAULT '',
    scope_label TEXT DEFAULT '',
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed')),
    total_questions INTEGER DEFAULT 0,
    correct_count INTEGER DEFAULT 0,
    score REAL DEFAULT 0.0,
    knowledge_summary TEXT DEFAULT '',
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS assessment_questions (
    id BIGSERIAL PRIMARY KEY,
    assessment_id BIGINT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
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
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS weekly_reports (
    id BIGSERIAL PRIMARY KEY,
    report_date TEXT NOT NULL,
    week_start TEXT NOT NULL,
    week_end TEXT NOT NULL,
    total_study_time INTEGER DEFAULT 0,
    total_questions INTEGER DEFAULT 0,
    documents_studied INTEGER DEFAULT 0,
    content TEXT NOT NULL,
    file_path TEXT,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS news_articles (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source_name TEXT DEFAULT '',
    source_type TEXT DEFAULT 'manual' CHECK(source_type IN ('manual','rss','digest','xhs_api','douyin_api')),
    language TEXT DEFAULT 'zh' CHECK(language IN ('zh','en','unknown')),
    summary TEXT DEFAULT '',
    key_points TEXT DEFAULT '',
    topics TEXT DEFAULT '',
    is_read INTEGER DEFAULT 0,
    is_bookmarked INTEGER DEFAULT 0,
    published_at TIMESTAMPTZ,
    content TEXT DEFAULT '',
    fetched_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    media_type TEXT DEFAULT 'text',
    media_url TEXT DEFAULT '',
    transcript TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(url, user_id)
);

CREATE TABLE IF NOT EXISTS rss_sources (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    language TEXT DEFAULT 'zh',
    is_active INTEGER DEFAULT 1,
    last_fetched_at TIMESTAMPTZ,
    article_count INTEGER DEFAULT 0,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    source_platform TEXT DEFAULT 'rss',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS media_sources (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
    last_fetched_at TIMESTAMPTZ,
    article_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS collector_tasks (
    task_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    source_id BIGINT NOT NULL REFERENCES media_sources(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    source_name TEXT DEFAULT '',
    platform TEXT DEFAULT '',
    crawler_type TEXT DEFAULT '',
    status TEXT DEFAULT 'running',
    started_ts REAL DEFAULT 0,
    started_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    stopped_at TIMESTAMPTZ,
    imported INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    article_count INTEGER DEFAULT 0,
    progress TEXT DEFAULT '{}',
    errors TEXT DEFAULT '[]',
    result_files TEXT DEFAULT '[]',
    crawler_result TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS raw_collected_items (
    id BIGSERIAL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES collector_tasks(task_id) ON DELETE CASCADE,
    run_id TEXT NOT NULL,
    source_id BIGINT NOT NULL REFERENCES media_sources(id) ON DELETE CASCADE,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
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
    article_id BIGINT REFERENCES news_articles(id) ON DELETE SET NULL,
    document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, file_path, record_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_user ON document_chunks(user_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON document_chunks USING hnsw (embedding vector_cosine_ops);
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
CREATE INDEX IF NOT EXISTS idx_media_sources_user ON media_sources(user_id);
CREATE INDEX IF NOT EXISTS idx_collector_tasks_user ON collector_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_collector_tasks_status ON collector_tasks(status);
CREATE INDEX IF NOT EXISTS idx_raw_items_task ON raw_collected_items(task_id);
CREATE INDEX IF NOT EXISTS idx_raw_items_status ON raw_collected_items(status);
