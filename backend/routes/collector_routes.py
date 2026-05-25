"""
API 路由 - 社交媒体内容采集（MediaCrawler 集成）
"""
from flask import Blueprint, request, jsonify, g
from services.collector_service import CollectorService
from models.database import MediaSourceDAO, NewsDAO
from backend.middleware.auth import require_auth

collector_bp = Blueprint("collector", __name__)


# ═══════════ 采集源管理 ═══════════

@collector_bp.route("/api/collector/sources", methods=["GET"])
@require_auth
def list_sources():
    """列出用户的所有采集源"""
    sources = MediaSourceDAO.get_all(user_id=g.user_id)
    return jsonify({"sources": sources, "total": len(sources)})


@collector_bp.route("/api/collector/sources", methods=["POST"])
@require_auth
def create_source():
    """创建新的采集源"""
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    platform = data.get("platform", "").strip().lower()

    if not name:
        return jsonify({"error": "采集源名称不能为空"}), 400
    if platform not in ("xhs", "xiaohongshu", "douyin", "dy", "kuaishou", "bilibili", "weibo"):
        return jsonify({"error": f"不支持的平台: {platform}，支持: xhs/xiaohongshu, douyin/dy, kuaishou, bilibili, weibo"}), 400

    crawler_type = data.get("crawler_type", "search")
    if crawler_type not in ("search", "creator", "detail"):
        return jsonify({"error": "crawler_type 必须是 search 或 creator"}), 400

    keywords = data.get("keywords", "")
    creator_ids = data.get("creator_ids", "")

    if crawler_type == "search" and not keywords:
        return jsonify({"error": "关键词搜索模式下 keywords 不能为空"}), 400
    if crawler_type == "creator" and not creator_ids:
        return jsonify({"error": "博主采集模式下 creator_ids 不能为空"}), 400

    if crawler_type == "detail" and not (creator_ids or keywords):
        return jsonify({"error": "detail mode requires a video URL or ID"}), 400

    source_id = MediaSourceDAO.create(
        user_id=g.user_id,
        name=name,
        platform=platform,
        crawler_type=crawler_type,
        keywords=keywords,
        creator_ids=creator_ids,
        login_type=data.get("login_type", "qrcode"),
        cookies=data.get("cookies", ""),
        enable_comments=data.get("enable_comments", 1),
        max_results=data.get("max_results", 1),
    )

    return jsonify({"status": "created", "source_id": source_id}), 201


@collector_bp.route("/api/collector/sources/<int:source_id>", methods=["GET"])
@require_auth
def get_source(source_id):
    """获取单个采集源详情"""
    source = MediaSourceDAO.get_by_id(source_id)
    if not source:
        return jsonify({"error": "采集源不存在"}), 404
    return jsonify({"source": source})


@collector_bp.route("/api/collector/sources/<int:source_id>", methods=["PUT"])
@require_auth
def update_source(source_id):
    """更新采集源配置"""
    source = MediaSourceDAO.get_by_id(source_id)
    if not source:
        return jsonify({"error": "采集源不存在"}), 404

    data = request.get_json(silent=True) or {}
    allowed_fields = {
        "name", "platform", "crawler_type", "keywords", "creator_ids",
        "login_type", "cookies", "enable_comments", "max_results", "is_active"
    }
    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if not updates:
        return jsonify({"error": "没有有效的更新字段"}), 400

    MediaSourceDAO.update(source_id, **updates)
    updated = MediaSourceDAO.get_by_id(source_id)
    return jsonify({"status": "updated", "source": updated})


@collector_bp.route("/api/collector/sources/<int:source_id>", methods=["DELETE"])
@require_auth
def delete_source(source_id):
    """删除采集源"""
    source = MediaSourceDAO.get_by_id(source_id)
    if not source:
        return jsonify({"error": "采集源不存在"}), 404
    MediaSourceDAO.delete(source_id)
    return jsonify({"status": "deleted", "source_id": source_id})


# ═══════════ 采集任务控制 ═══════════

@collector_bp.route("/api/collector/crawl/start", methods=["POST"])
@require_auth
def start_crawl():
    """启动采集任务"""
    data = request.get_json(silent=True) or {}
    source_id = data.get("source_id")
    auto_import = data.get("auto_import", True)

    if not source_id:
        return jsonify({"error": "source_id 不能为空"}), 400

    if auto_import:
        # 后台自动采集并导入
        result = CollectorService.collect_and_import_async(source_id, user_id=g.user_id)
    else:
        # 仅启动采集，不自动导入
        result = CollectorService.start_crawl(source_id, user_id=g.user_id)

    if result.get("error"):
        return jsonify(result), 500

    return jsonify(result)


@collector_bp.route("/api/collector/crawl/status", methods=["GET"])
@require_auth
def crawl_status():
    """查询采集任务状态"""
    task_id = request.args.get("task_id")
    status = CollectorService.get_collect_status(task_id=task_id, user_id=g.user_id)
    return jsonify(status)


@collector_bp.route("/api/collector/crawl/stop", methods=["POST"])
@require_auth
def stop_crawl():
    """停止当前采集任务。"""
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id")
    result = CollectorService.stop_crawl(task_id=task_id)
    return jsonify(result)


@collector_bp.route("/api/collector/crawl/import", methods=["POST"])
@require_auth
def import_crawl_data():
    """手动导入采集结果到知识库"""
    data = request.get_json(silent=True) or {}
    task_id = data.get("task_id", "")

    if not task_id:
        return jsonify({"error": "task_id 不能为空"}), 400

    result = CollectorService.import_from_crawl(task_id, user_id=g.user_id)
    if result.get("error"):
        return jsonify(result), 500

    return jsonify(result)


@collector_bp.route("/api/collector/crawl/collect-all", methods=["POST"])
@require_auth
def collect_all():
    """一键采集所有活跃源"""
    result = CollectorService.collect_all_active(user_id=g.user_id)
    return jsonify(result)


# ═══════════ MediaCrawler 服务状态 ═══════════

@collector_bp.route("/api/collector/service/status", methods=["GET"])
@require_auth
def service_status():
    """查询 MediaCrawler 服务运行状态"""
    status = CollectorService.get_crawler_status()
    return jsonify(status)


@collector_bp.route("/api/collector/service/files", methods=["GET"])
@require_auth
def list_files():
    """列出 MediaCrawler 数据文件"""
    files = CollectorService.list_data_files()
    return jsonify({"files": files, "total": len(files)})


# ═══════════ GitHub Star 查询（MediaCrawler 项目热度） ═══════════

@collector_bp.route("/api/collector/info", methods=["GET"])
@require_auth
def collector_info():
    """获取采集系统概要信息"""
    sources = MediaSourceDAO.get_all(user_id=g.user_id)
    active_sources = [s for s in sources if s["is_active"]]

    # 统计各平台采集数量
    platform_stats = {}
    for s in sources:
        p = s["platform"]
        platform_stats[p] = platform_stats.get(p, 0) + 1

    # 统计已采集文章数
    article_count = 0
    for st in ("xhs_api", "douyin_api"):
        articles = NewsDAO.get_all(
            page=1, per_page=1, source_type=st, user_id=g.user_id
        )
        # 通过stats获取精确计数
        pass

    stats = NewsDAO.get_stats(user_id=g.user_id)
    xhs_count = stats.get("by_source", {}).get("xhs_api", 0)
    dy_count = stats.get("by_source", {}).get("douyin_api", 0)

    return jsonify({
        "media_crawler_url": "http://localhost:8080",
        "total_sources": len(sources),
        "active_sources": len(active_sources),
        "platforms": platform_stats,
        "articles_collected": {
            "xhs": xhs_count,
            "douyin": dy_count,
            "total": xhs_count + dy_count,
        },
    })
