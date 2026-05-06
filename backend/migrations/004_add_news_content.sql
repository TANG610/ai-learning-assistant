-- 004: news_articles 添加 content 字段，存储文章正文
ALTER TABLE news_articles ADD COLUMN content TEXT DEFAULT '';
