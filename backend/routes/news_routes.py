"""
API 路由 - AI 资讯追踪
"""
from flask import Blueprint, request, jsonify, g, Response, stream_with_context
from services.news_service import NewsService
from models.database import NewsDAO, RssSourceDAO
from backend.middleware.auth import require_auth
from concurrent.futures import ThreadPoolExecutor
import json

news_bp = Blueprint("news", __name__)
_bg_executor = ThreadPoolExecutor(max_workers=2)


# ═══════════ 文章管理 ═══════════

@news_bp.route("/api/news/articles", methods=["GET"])
@require_auth
def list_articles():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    source_type = request.args.get("source_type")
    language = request.args.get("language")
    is_read = request.args.get("is_read", type=int)
    is_bookmarked = request.args.get("is_bookmarked", type=int)

    # 默认不显示 RSS 原文（综合报告才显示），明确传 source_type=rss 时才显示
    exclude_rss = None if source_type == 'rss' else (None if source_type else 'rss')
    articles = NewsDAO.get_all(
        page=page, per_page=per_page, source_type=source_type,
        language=language, is_read=is_read, is_bookmarked=is_bookmarked,
        user_id=g.user_id, exclude_source_type=exclude_rss
    )
    # 统计数也排除 RSS 原文
    stats = NewsDAO.get_stats(user_id=g.user_id)
    return jsonify({"articles": articles, "stats": stats})


@news_bp.route("/api/news/articles", methods=["POST"])
@require_auth
def import_article():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL 不能为空"}), 400

    try:
        result = NewsService.import_article(url, user_id=g.user_id)
        if result.get("error"):
            return jsonify(result), 500
        if result.get("skipped"):
            return jsonify(result), 200
        return jsonify(result), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@news_bp.route("/api/news/articles/batch", methods=["POST"])
@require_auth
def import_batch():
    """批量导入URL，后台执行"""
    data = request.get_json() or {}
    urls_text = data.get("urls", "").strip()
    if not urls_text:
        return jsonify({"error": "URL 不能为空"}), 400

    urls = [u.strip() for u in urls_text.split("\n") if u.strip()]

    def _run():
        results = []
        for url in urls:
            r = NewsService.import_article(url, user_id=g.user_id)
            results.append(r)
        NewsService._fetch_tasks[f"batch_{g.user_id}"] = {
            "status": "completed", "results": results,
            "total": len(urls),
            "imported": sum(1 for r in results if r.get("article_id")),
            "skipped": sum(1 for r in results if r.get("skipped")),
            "errors": sum(1 for r in results if r.get("error"))
        }

    _bg_executor.submit(_run)
    return jsonify({"status": "started", "total": len(urls)}), 202


@news_bp.route("/api/news/articles/<int:article_id>", methods=["GET"])
@require_auth
def get_article(article_id):
    article = NewsDAO.get_by_id(article_id)
    if not article:
        return jsonify({"error": "文章不存在"}), 404
    return jsonify({"article": article})


@news_bp.route("/api/news/articles/<int:article_id>", methods=["DELETE"])
@require_auth
def delete_article(article_id):
    article = NewsDAO.get_by_id(article_id)
    if not article:
        return jsonify({"error": "文章不存在"}), 404

    # 级联删除关联的 document
    if article.get("document_id"):
        from services.document_service import DocumentService
        DocumentService.delete_document(article["document_id"])

    NewsDAO.delete(article_id)
    return jsonify({"status": "deleted"})


@news_bp.route("/api/news/articles/<int:article_id>/save-to-library", methods=["POST"])
@require_auth
def save_to_library(article_id):
    """将资讯文章转存到知识库：创建文档 → 向量化 → 知识点提取"""
    try:
        result = NewsService.save_to_library(article_id)
        if "error" in result:
            return jsonify(result), 400
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@news_bp.route("/api/news/articles/<int:article_id>/read", methods=["POST"])
@require_auth
def mark_read(article_id):
    data = request.get_json() or {}
    is_read = data.get("is_read", 1)
    NewsDAO.mark_read(article_id, is_read)
    return jsonify({"status": "ok"})


@news_bp.route("/api/news/articles/<int:article_id>/bookmark", methods=["POST"])
@require_auth
def toggle_bookmark(article_id):
    NewsDAO.toggle_bookmark(article_id)
    return jsonify({"status": "ok"})


# ═══════════ RSS 源管理 ═══════════

@news_bp.route("/api/news/sources", methods=["GET"])
@require_auth
def list_sources():
    # 首次访问时初始化预制源
    NewsService.init_preset_sources(user_id=g.user_id)
    sources = RssSourceDAO.get_all(user_id=g.user_id)
    return jsonify({"sources": sources})


@news_bp.route("/api/news/sources", methods=["POST"])
@require_auth
def add_source():
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    url = data.get("url", "").strip()
    if not name or not url:
        return jsonify({"error": "名称和URL不能为空"}), 400
    language = data.get("language", "zh")
    sid = RssSourceDAO.create(name=name, url=url, language=language, user_id=g.user_id)
    return jsonify({"id": sid, "status": "created"}), 201


@news_bp.route("/api/news/sources/<int:source_id>", methods=["PUT"])
@require_auth
def update_source(source_id):
    data = request.get_json() or {}
    allowed = {"name", "url", "language", "is_active"}
    kwargs = {k: v for k, v in data.items() if k in allowed}
    if kwargs:
        RssSourceDAO.update(source_id, **kwargs)
    return jsonify({"status": "ok"})


@news_bp.route("/api/news/sources/<int:source_id>", methods=["DELETE"])
@require_auth
def delete_source(source_id):
    RssSourceDAO.delete(source_id)
    return jsonify({"status": "deleted"})


@news_bp.route("/api/news/sources/<int:source_id>/fetch", methods=["POST"])
@require_auth
def fetch_source(source_id):
    """抓取单个RSS源，后台执行"""
    _bg_executor.submit(NewsService.fetch_rss_feed, source_id)
    src = RssSourceDAO.get_by_id(source_id)
    return jsonify({"status": "started", "source_name": src["name"] if src else "unknown"})


@news_bp.route("/api/news/fetch-all", methods=["POST"])
@require_auth
def fetch_all():
    """抓取全部活跃RSS源，后台执行"""
    result = NewsService.fetch_all_active_feeds(user_id=g.user_id)
    return jsonify(result)


@news_bp.route("/api/news/fetch-status", methods=["GET"])
@require_auth
def fetch_status():
    """查询后台任务状态"""
    status = NewsService.get_fetch_status(user_id=g.user_id)
    return jsonify(status)


# ═══════════ 综合报告（流式） ═══════════

@news_bp.route("/api/news/consolidate-stream", methods=["POST"])
@require_auth
def consolidate_stream():
    """流式生成综合报告"""
    data = request.get_json() or {}
    article_ids = data.get("article_ids") or []
    days = data.get("days", 0)

    def generate():
        full_text = ""
        try:
            for chunk in NewsService.consolidate_articles_stream(
                article_ids=article_ids, days=days, user_id=g.user_id
            ):
                full_text += chunk
                yield f"data: {json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"

            if full_text.strip():
                result = NewsService.save_consolidated_document(full_text, g.user_id)
                yield f"data: {json.dumps({'done': True, 'doc_id': result.get('doc_id'), 'article_id': result.get('article_id'), 'title': result.get('title')}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'done': True, 'doc_id': None, 'article_id': None}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ═══════════ AI 摘要/分析 ═══════════

@news_bp.route("/api/news/digest", methods=["POST"])
@require_auth
def generate_digest():
    data = request.get_json() or {}
    days = data.get("days", 1)
    if days not in (1, 7):
        days = 1
    digest = NewsService.generate_digest(days=days, user_id=g.user_id)
    return jsonify({"digest": digest, "days": days})


@news_bp.route("/api/news/trends", methods=["GET"])
@require_auth
def get_trends():
    days = request.args.get("days", 14, type=int)
    trends = NewsService.detect_trends(days=days, user_id=g.user_id)
    return jsonify(trends)


@news_bp.route("/api/news/stats", methods=["GET"])
@require_auth
def get_stats():
    stats = NewsDAO.get_stats(user_id=g.user_id)
    return jsonify({"stats": stats})
