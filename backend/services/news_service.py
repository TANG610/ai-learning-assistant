"""
AI 资讯追踪服务 — 抓取、导入、摘要、RSS、文摘生成
"""
import json
import re
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup
import feedparser

import config
from models.database import NewsDAO, RssSourceDAO, KnowledgeDAO, get_db
from services.document_service import DocumentService
from services.claude_service import LLMService
from backend.utils.logger import log


# 后台任务状态追踪 {user_id: {"status": "running"|"completed"|"error", ...}}
_fetch_tasks = {}
_executor = ThreadPoolExecutor(max_workers=2)

PRESET_SOURCES = [
    # 中文 AI 资讯
    {"name": "机器之心", "url": "https://www.jiqizhixin.com/rss", "language": "zh"},
    {"name": "量子位", "url": "https://www.qbitai.com/feed", "language": "zh"},
    {"name": "36氪", "url": "https://36kr.com/feed", "language": "zh"},
    {"name": "虎嗅", "url": "https://www.huxiu.com/rss/0.xml", "language": "zh"},
    {"name": "雷锋网", "url": "https://www.leiphone.com/feed", "language": "zh"},
    {"name": "极客公园", "url": "https://www.geekpark.net/feed", "language": "zh"},
    {"name": "少数派", "url": "https://sspai.com/feed", "language": "zh"},
    # 英文 AI 资讯
    {"name": "ArXiv cs.AI", "url": "https://rss.arxiv.org/rss/cs.AI", "language": "en"},
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "language": "en"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/ai-artificial-intelligence/rss/index.xml", "language": "en"},
    {"name": "Hacker News", "url": "https://hnrss.org/frontpage", "language": "en"},
    {"name": "VentureBeat AI", "url": "https://venturebeat.com/category/ai/feed/", "language": "en"},
    {"name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml", "language": "en"},
    {"name": "Anthropic Blog", "url": "https://www.anthropic.com/blog/rss.xml", "language": "en"},
]


class NewsService:
    """资讯抓取、导入、摘要、分析"""

    # ── RSS 源初始化 ──

    @staticmethod
    def init_preset_sources(user_id: int = None):
        """首次使用插入预制 RSS 源（URL 去重）"""
        existing = {s["url"] for s in RssSourceDAO.get_all(user_id=user_id)}
        added = 0
        for preset in PRESET_SOURCES:
            if preset["url"] not in existing:
                RssSourceDAO.create(
                    name=preset["name"],
                    url=preset["url"],
                    language=preset["language"],
                    user_id=user_id
                )
                added += 1
        if added:
            log.info(f"为用户 {user_id} 初始化了 {added} 个预制 RSS 源")

    # ── URL 抓取 ──

    @staticmethod
    def fetch_article_from_url(url: str) -> dict:
        """
        从 URL 抓取文章标题和正文。
        Returns: {"title": str, "content": str, "error": str|None}
        """
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=config.NEWS_FETCH_TIMEOUT)
            resp.raise_for_status()

            # 尝试从响应中检测编码
            content_type = resp.headers.get("content-type", "")
            if "charset" in content_type.lower():
                resp.encoding = resp.apparent_encoding

            html = resp.text
            soup = BeautifulSoup(html, "html.parser")

            # 提取标题
            title = ""
            og_title = soup.find("meta", property="og:title")
            if og_title:
                title = og_title.get("content", "")
            if not title:
                title_tag = soup.find("title")
                if title_tag:
                    title = title_tag.get_text(strip=True)
            if not title:
                h1 = soup.find("h1")
                if h1:
                    title = h1.get_text(strip=True)
            title = title or url

            # 提取正文（优先语义标签，回退 body）
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            content = ""
            for candidate in soup.select("article, main, .article-content, .post-content, .entry-content"):
                content = candidate.get_text(separator="\n", strip=True)
                if len(content) > 200:
                    break

            if not content or len(content) < 200:
                body = soup.find("body")
                content = body.get_text(separator="\n", strip=True) if body else ""

            # 清洗空白行
            content = re.sub(r"\n{3,}", "\n\n", content).strip()

            if not content:
                return {"title": title, "content": "", "error": "无法提取正文内容"}

            log.info(f"抓取文章成功: {title[:50]}... ({len(content)} 字符)")
            return {"title": title, "content": content, "error": None}

        except requests.RequestException as e:
            log.error(f"抓取 URL 失败: {url} | {e}")
            return {"title": url, "content": "", "error": f"网络请求失败: {e}"}
        except Exception as e:
            log.error(f"解析 URL 失败: {url} | {e}")
            return {"title": url, "content": "", "error": f"解析失败: {e}"}

    # ── 文章导入 ──

    @staticmethod
    def import_article(url: str, user_id: int = None, source_name: str = '',
                       source_type: str = 'manual', language: str = 'unknown',
                       pre_summary: dict = None, skip_knowledge: bool = False) -> dict:
        """
        完整导入流程：抓取 → 去重 → 入库(Document+ChromaDB) → LLM摘要

        Args:
            pre_summary: 预计算的摘要数据（用于批量导入时避免重复LLM调用）
            skip_knowledge: 跳过知识点提取（RSS批量导入时节省时间）

        Returns:
            {"article_id": int, "document_id": int, "title": str, "summary": str, ...}
        """
        # 1. 去重检查
        existing = NewsDAO.get_by_url(url, user_id=user_id)
        if existing:
            return {"skipped": True, "article_id": existing["id"],
                    "title": existing["title"], "reason": "URL 已存在"}

        # 2. 抓取
        fetched = NewsService.fetch_article_from_url(url)
        if fetched["error"]:
            return {"error": fetched["error"], "title": fetched.get("title", url)}

        title = fetched["title"]
        content = fetched["content"]

        # 3. LLM 摘要（优先使用预计算）
        if pre_summary:
            summary_data = pre_summary
        else:
            try:
                summary_data = NewsService.summarize_article(title, content)
            except Exception as e:
                log.warning(f"LLM 摘要生成失败: {e}")
                summary_data = {"summary": "", "key_points": [], "topics": []}

        # 4. 导入为文档（进入 RAG 管道）
        try:
            doc_result = DocumentService.import_text(
                title=title, content=content, user_id=user_id, file_category="news"
            )
            document_id = doc_result.get("doc_id")
        except Exception as e:
            log.error(f"文档导入失败: {e}")
            return {"error": f"文档导入失败: {e}", "title": title}

        # 5. 写入 news_articles
        key_points_json = json.dumps(summary_data.get("key_points", []), ensure_ascii=False)
        topics_json = json.dumps(summary_data.get("topics", []), ensure_ascii=False)

        article_id = NewsDAO.create(
            document_id=document_id,
            title=title,
            url=url,
            source_name=source_name,
            source_type=source_type,
            summary=summary_data.get("summary", ""),
            key_points=key_points_json,
            topics=topics_json,
            language=language,
            user_id=user_id
        )

        # 6. AI 提取知识点（RSS批量导入时可跳过）
        knowledge_data = []
        if not skip_knowledge:
            try:
                knowledge_data = NewsService._extract_and_save_knowledge(document_id, content, user_id)
            except Exception as e:
                log.warning(f"知识点提取失败: {e}")

        return {
            "article_id": article_id,
            "document_id": document_id,
            "title": title,
            "summary": summary_data.get("summary", ""),
            "key_points": summary_data.get("key_points", []),
            "topics": summary_data.get("topics", []),
            "knowledge_points": knowledge_data,
            "language": language,
            "source_name": source_name
        }

    # ── LLM 摘要 ──

    @staticmethod
    def summarize_article(title: str, content: str) -> dict:
        """
        LLM 生成摘要、关键要点和话题标签。
        Returns: {"summary": str, "key_points": [str], "topics": [str]}
        """
        llm = LLMService()
        prompt = f"""请为以下AI行业资讯生成摘要和要点。

标题：{title}
内容：{content[:4000]}

要求：
1. 用3句话写中文摘要（每句不超过60字），概括文章核心内容
2. 提炼3-5个关键要点（每条不超过50字）
3. 标注3-5个话题标签（如：LLM、Agent、RAG、多模态、产品化、开源、融资、政策、应用落地等）

输出JSON格式（不要Markdown代码块）：
{{"summary": "3句话摘要，用空格连接", "key_points": ["要点1", "要点2", "要点3"], "topics": ["标签1", "标签2", "标签3"]}}"""

        raw = llm._call(
            [{"role": "system", "content": "你是AI行业分析专家，擅长提炼资讯要点。只输出JSON，不要任何额外内容。"},
             {"role": "user", "content": prompt}],
            max_tokens=1024
        )

        # 解析 JSON
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:]) if len(lines) > 1 else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        try:
            data = json.loads(raw)
            return {
                "summary": data.get("summary", ""),
                "key_points": data.get("key_points", []),
                "topics": data.get("topics", [])
            }
        except json.JSONDecodeError:
            log.warning(f"LLM 输出无法解析为JSON: {raw[:200]}")
            return {"summary": raw[:200], "key_points": [], "topics": []}

    @staticmethod
    def batch_summarize_articles(articles: list) -> list:
        """
        一次 LLM 调用来批量摘要多篇文章（大幅减少 LLM 调用次数）。

        Args:
            articles: [{"title": str, "content": str, "index": int}, ...]

        Returns:
            [{"summary": str, "key_points": [str], "topics": [str]}, ...] 按 index 排序
        """
        if not articles:
            return []

        llm = LLMService()
        articles_text = "\n\n---\n\n".join([
            f"## 文章 {a['index']+1}: {a['title']}\n{a['content'][:1500]}"
            for a in articles
        ])

        prompt = f"""请为以下{len(articles)}篇AI行业资讯批量生成摘要。对每篇文章输出：

1. 一句话中文摘要（不超过40字）
2. 2-3个关键要点
3. 2-3个话题标签

{articles_text}

输出JSON数组格式（不要Markdown代码块）：
[
  {{"summary": "摘要", "key_points": ["要点"], "topics": ["标签"]}},
  ...
]

严格按文章顺序输出{len(articles)}个对象，只输出JSON数组。"""

        try:
            raw = llm._call(
                [{"role": "system", "content": "你是AI行业分析专家，擅长提炼资讯要点。只输出JSON数组。"},
                 {"role": "user", "content": prompt}],
                max_tokens=2048
            )
            raw = raw.strip()
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:]) if len(lines) > 1 else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()
            data = json.loads(raw)
            # 确保数量匹配
            while len(data) < len(articles):
                data.append({"summary": "", "key_points": [], "topics": []})
            return data[:len(articles)]
        except Exception as e:
            log.warning(f"批量摘要失败: {e}，回退空摘要")
            return [{"summary": "", "key_points": [], "topics": []} for _ in articles]

    @staticmethod
    def _extract_and_save_knowledge(document_id: int, content: str, user_id: int = None) -> list:
        """从文章提取知识点并写入数据库"""
        llm = LLMService()
        try:
            points = llm.extract_knowledge_points(content)
        except Exception:
            return []

        saved = []
        for p in points[:8]:
            topic = p.get("name", "") or p.get("topic", "")
            if not topic:
                continue
            KnowledgeDAO.upsert(
                document_id=document_id, topic=topic,
                mastery="learning", is_correct=None, user_id=user_id
            )
            saved.append(topic)
        return saved

    @staticmethod
    def save_to_library(article_id: int) -> dict:
        """
        将资讯文章转存到知识库：创建 document → 分块 → 向量化 → 知识点提取。
        """
        article = NewsDAO.get_by_id(article_id)
        if not article:
            return {"error": "文章不存在"}

        if article.get("document_id"):
            return {"error": "已存入知识库", "document_id": article["document_id"]}

        content = article.get("content", "")
        if not content:
            return {"error": "文章没有正文内容"}

        # 1. 创建文档 + 分块 + 向量化
        doc_result = DocumentService.import_text(
            title=article["title"], content=content,
            user_id=article.get("user_id"), file_category="news"
        )
        document_id = doc_result.get("doc_id")
        if not document_id:
            return {"error": "文档创建失败"}

        # 2. 更新 news_articles 关联
        conn = get_db()
        conn.execute("UPDATE news_articles SET document_id = ? WHERE id = ?", (document_id, article_id))
        conn.commit()
        conn.close()

        # 3. 知识点提取
        knowledge = []
        try:
            knowledge = NewsService._extract_and_save_knowledge(
                document_id, content, article.get("user_id")
            )
        except Exception as e:
            log.warning(f"知识点提取失败 (article {article_id}): {e}")

        return {
            "article_id": article_id,
            "document_id": document_id,
            "knowledge_points": knowledge,
            "status": "saved"
        }

    # ── 综合报告（流式生成） ──

    @staticmethod
    def consolidate_articles_stream(article_ids: list = None, days: int = 0, user_id: int = None):
        """
        将多篇资讯原文整合为一份详尽的综合报告（流式生成器）。

        Args:
            article_ids: 指定文章ID列表，为空则取最近导入的（无摘要的）
            days: 最近N天（两者皆空时默认取最近1天未摘要文章）
        """
        if article_ids:
            articles = []
            for aid in article_ids:
                a = NewsDAO.get_by_id(aid)
                if a and a.get("content"):
                    articles.append(a)
        else:
            # 取最近一批未生成摘要的文章（有正文的文章）
            articles = NewsDAO.get_recent(
                days=days or 1, limit=40, user_id=user_id
            )

        if not articles:
            yield "没有找到可整合的文章。请先抓取RSS或导入URL。"
            return

        # 构建文章内容块
        parts = []
        for i, a in enumerate(articles):
            content = (a.get("content") or "").strip()
            if not content:
                continue
            source_info = a.get("source_name", "手动导入")
            source_url = a.get("url", "")
            parts.append(
                f"## 文章 {i+1}: {a['title']}\n"
                f"来源: {source_info} | 语言: {a.get('language', 'zh')} | 链接: {source_url}\n\n"
                f"{content[:2500]}"
            )

        if not parts:
            yield "所有文章都没有正文内容。"
            return

        articles_text = "\n\n---\n\n".join(parts)
        today = datetime.now().strftime("%Y-%m-%d")

        system_prompt = "你是AI行业首席分析师，擅长为产品经理撰写详尽、有洞见的资讯报告。"

        user_prompt = f"""请基于以下{len(articles)}篇AI行业资讯原文，生成一份详尽的AI资讯综合报告。

要求：
1. 标题用"AI资讯综合报告 ({today})"
2. 按主题自动聚类（如大模型技术突破、AI产品发布与商业化、行业应用落地、融资并购、政策监管、开源动态等）
3. 每个主题下列出相关资讯，每条必须包含：
   - 原文标题、来源和链接（原文中标注的"链接: xxx"必须带上）
   - 详细要点：禁止笼统概括。如果原文提到具体数字、原则、方法论、预测等，必须完整列出每一条的具体内容（比如"五项原则"就要全部五项写出来，"三个关键发现"就要三个都列出来）
   - 对AI产品经理的意义（1-2句）
4. 末尾列出 TOP 3 最值得深度阅读的文章及简短理由
5. 使用 Markdown 格式，层级分明（## 主题名、### 分项、- 列表），专业但不枯燥
6. 用中文撰写，英文文章翻译其核心要点
7. 报告末尾注明数据来源：共整合{len(articles)}篇资讯

以下是{len(articles)}篇原文：
---
{articles_text}
---"""

        llm = LLMService()
        for chunk in llm.stream_generate(system_prompt, user_prompt, max_tokens=4096):
            yield chunk

    @staticmethod
    def save_consolidated_document(full_text: str, user_id: int = None) -> dict:
        """将综合报告存入知识库 + 创建 news_article 条目（出现在资讯列表）"""
        today = datetime.now().strftime("%Y-%m-%d")
        title = f"AI资讯综合报告 {today}"

        try:
            doc_result = DocumentService.import_text(
                title=title, content=full_text, user_id=user_id, file_category="news"
            )
            doc_id = doc_result.get("doc_id")

            # 同时创建 news_article（用时间戳确保URL唯一）
            ts = datetime.now().strftime("%H%M%S")
            summary = full_text[:300].replace("\n", " ").strip()
            article_id = NewsDAO.create(
                document_id=doc_id,
                title=title,
                url=f"digest://{today}/{ts}",
                source_name="AI综合报告",
                source_type="digest",
                summary=summary,
                key_points="[]",
                topics="[]",
                language="zh",
                user_id=user_id,
                content=full_text
            )

            return {"doc_id": doc_id, "article_id": article_id, "title": title}
        except Exception as e:
            log.error(f"综合报告存库失败: {e}")
            return {"error": str(e), "title": title}

    # ── RSS 抓取 ──

    @staticmethod
    def fetch_rss_feed(source_id: int) -> dict:
        """
        抓取单个 RSS 源的文章。只存原文，不调LLM摘要（由后续 consolidate 统一处理）。
        Returns: {"source_name": str, "imported": int, "skipped": int, "errors": [str]}
        """
        source = RssSourceDAO.get_by_id(source_id)
        if not source:
            return {"error": "RSS源不存在"}

        user_id = source.get("user_id")
        language = source.get("language", "unknown")

        try:
            feed = feedparser.parse(source["url"])
            if feed.bozo:
                log.warning(f"RSS 解析警告 ({source['name']}): {feed.bozo_exception}")

            entries = feed.entries[:5]  # 每个源取5篇
            if not entries:
                log.info(f"RSS 源 ({source['name']}) 没有新条目")
                RssSourceDAO.update(source_id, last_fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                return {"source_name": source["name"], "imported": 0, "skipped": 0, "errors": []}

            imported = 0
            skipped = 0
            errors = []

            for entry in entries:
                url = entry.get("link", "")
                if not url:
                    continue
                if NewsDAO.get_by_url(url, user_id=user_id):
                    skipped += 1
                    continue

                title = entry.get("title", "未命名")
                content = ""
                if hasattr(entry, "content") and entry.content:
                    content = entry.content[0].get("value", "")
                elif hasattr(entry, "summary"):
                    content = BeautifulSoup(entry.summary, "html.parser").get_text()
                else:
                    content = entry.get("description", "")

                if len(content) < 50:
                    skipped += 1
                    continue

                try:
                    NewsDAO.create(
                        document_id=None,
                        title=title, url=url,
                        source_name=source["name"],
                        source_type="rss",
                        summary="", key_points="[]", topics="[]",
                        language=language, user_id=user_id,
                        content=content
                    )
                    imported += 1
                except Exception as e:
                    errors.append(f"{title}: {e}")

            RssSourceDAO.update(source_id,
                last_fetched_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                article_count=(source.get("article_count", 0) + imported)
            )

            log.info(f"RSS 抓取完成 ({source['name']}): 导入 {imported}, 跳过 {skipped}")
            return {
                "source_name": source["name"], "source_id": source_id,
                "imported": imported, "skipped": skipped,
                "total_entries": len(entries), "errors": errors
            }

        except Exception as e:
            log.error(f"RSS 抓取异常 ({source['name']}): {e}")
            return {"source_name": source["name"], "source_id": source_id, "error": str(e)}

    @staticmethod
    def fetch_all_active_feeds(user_id: int = None) -> dict:
        """
        抓取所有活跃 RSS 源（在后台线程中执行）。
        首次调用立即返回，状态通过 get_fetch_status() 查询。
        """
        sources = RssSourceDAO.get_active(user_id=user_id)
        if not sources:
            return {"status": "completed", "total_sources": 0, "total_imported": 0, "message": "没有活跃的RSS源"}

        task_key = str(user_id)
        _fetch_tasks[task_key] = {
            "status": "running", "done": 0, "total": len(sources),
            "current_source": "", "imported": 0, "skipped": 0,
            "errors": [], "results": []
        }

        def _run():
            all_results = []
            total_imported = 0
            total_skipped = 0
            all_errors = []

            for i, src in enumerate(sources):
                _fetch_tasks[task_key]["current_source"] = src["name"]
                _fetch_tasks[task_key]["done"] = i

                result = NewsService.fetch_rss_feed(src["id"])
                all_results.append(result)

                if not result.get("error"):
                    total_imported += result.get("imported", 0)
                    total_skipped += result.get("skipped", 0)
                    for e in result.get("errors", []):
                        all_errors.append(f"[{src['name']}] {e}")
                else:
                    all_errors.append(f"[{src['name']}] {result['error']}")

            _fetch_tasks[task_key] = {
                "status": "completed",
                "done": len(sources),
                "total": len(sources),
                "current_source": "",
                "imported": total_imported,
                "skipped": total_skipped,
                "errors": all_errors,
                "results": all_results
            }

        _executor.submit(_run)

        return {
            "status": "started",
            "total_sources": len(sources),
            "source_names": [s["name"] for s in sources]
        }

    @staticmethod
    def get_fetch_status(user_id: int = None) -> dict:
        """查询后台抓取任务状态"""
        task = _fetch_tasks.get(str(user_id))
        if not task:
            return {"status": "idle"}
        return task

    # ── AI 文摘 ──

    @staticmethod
    def generate_digest(days: int = 1, user_id: int = None) -> str:
        """生成 AI 资讯摘要（日报 days=1，周报 days=7）"""
        articles = NewsDAO.get_recent(days=days, limit=30, user_id=user_id)
        if not articles:
            label = "今天" if days == 1 else f"过去{days}天"
            return f"{label}还没有导入资讯文章。"

        llm = LLMService()
        articles_text = "\n\n---\n\n".join([
            f"### {a['title']}\n"
            f"来源: {a['source_name'] or '手动导入'} | "
            f"摘要: {a['summary'] or '无'}\n"
            f"话题: {a['topics'] or '无'}"
            for a in articles
        ])

        label = "今日" if days == 1 else "本周"
        prompt = f"""以下是{label}导入的AI行业资讯文章，请生成一份{label}AI资讯摘要。

{articles_text}

要求：
1. 用一段话概括{label}AI行业的整体动态（2-3句）
2. 列出3-5个最重要的资讯要点（每条简述+为什么重要）
3. 如果多篇文章涉及同一话题，进行综合归纳
4. 对于产品经理，标注1-2篇最值得深度阅读的文章
5. 用 Markdown 格式输出，语气专业但不枯燥"""

        return llm._call(
            [{"role": "system", "content": "你是AI行业首席分析师，擅长为产品经理撰写精炼的资讯摘要。用Markdown格式输出。"},
             {"role": "user", "content": prompt}],
            max_tokens=2048
        )

    @staticmethod
    def detect_trends(days: int = 14, user_id: int = None) -> dict:
        """
        LLM 分析近期文章识别热点趋势。
        Returns: {"trends": [{"topic": str, "momentum": str, "articles": int}]}
        """
        articles = NewsDAO.get_recent(days=days, limit=50, user_id=user_id)
        if len(articles) < 3:
            return {"trends": [], "message": f"过去{days}天资讯不足（需要至少3篇）"}

        llm = LLMService()
        articles_summary = "\n".join([
            f"- [{a['title']}] 话题: {a['topics'] or '未标注'} | 来源: {a['source_name']}"
            for a in articles
        ])

        prompt = f"""分析以下过去{days}天的AI行业文章列表，识别热点趋势。

文章列表：
{articles_summary}

要求：
1. 识别2-5个最热的话题方向
2. 每个话题标注热度（上升中/持续高热/降温中）
3. 说明该话题相关的文章数量
4. 简要说明该话题对AI产品经理的意义

输出JSON格式（不要Markdown代码块）：
{{"trends": [{{"topic": "话题名", "momentum": "上升中/持续高热/降温中", "article_count": 数字, "pm_relevance": "对PM的一句话意义"}}]}}"""

        raw = llm._call(
            [{"role": "system", "content": "你是AI行业趋势分析师。只输出JSON，不要任何额外内容。"},
             {"role": "user", "content": prompt}],
            max_tokens=1024
        )

        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:]) if len(lines) > 1 else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"trends": [], "message": "趋势分析解析失败，请重试"}
