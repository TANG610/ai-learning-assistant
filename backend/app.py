"""
Flask 应用入口
"""
import sys
import os
from pathlib import Path

# 确保项目根目录在路径中
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import json as _json
import config
from models.database import init_db, run_migrations
from backend.middleware.auth import require_auth
from backend.utils.logger import log

# 注册蓝图
from routes.document_routes import document_bp
from routes.chat_routes import chat_bp
from routes.progress_routes import progress_bp
from routes.quiz_routes import quiz_bp
from routes.auth_routes import auth_bp
from routes.news_routes import news_bp
from routes.collector_routes import collector_bp


def create_app():
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB 文件上传限制

    # CORS 跨域（允许 Authorization header）
    CORS(app, resources={r"/*": {"origins": "*", "expose_headers": ["Authorization"]}})

    # 注册路由（必须在通配路由之前，确保 API 优先）
    app.register_blueprint(auth_bp)
    app.register_blueprint(document_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(progress_bp)
    app.register_blueprint(quiz_bp)
    app.register_blueprint(news_bp)
    app.register_blueprint(collector_bp)

    # 前端静态文件服务
    frontend_dir = project_root / "frontend"

    @app.route("/")
    def serve_index():
        return send_from_directory(frontend_dir, "index.html")

    @app.route("/<path:path>", methods=["GET"])
    def serve_static(path):
        if path.startswith("api/"):
            return jsonify({"error": "Not found"}), 404
        file_path = frontend_dir / path
        if file_path.exists():
            resp = send_from_directory(frontend_dir, path)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp
        return send_from_directory(frontend_dir, "index.html")

    # 初始化数据库
    init_db()
    run_migrations()

    # 健康检查
    @app.route("/api/health", methods=["GET"])
    def health_check():
        multimodal_configured = bool(config.MULTIMODAL_API_KEY)
        return jsonify({
            "status": "healthy",
            "version": "2.2.0",
            "llm_configured": bool(config.LLM_API_KEY),
            "llm_model": config.LLM_MODEL,
            "multimodal_configured": multimodal_configured
        })

    # ── 模型切换 API ──

    @app.route("/api/models", methods=["GET"])
    @require_auth
    def list_models():
        from services.claude_service import LLMService, get_current_model
        llm = LLMService()
        models = llm.get_available_models()
        return jsonify({"models": models, "current": get_current_model()})

    @app.route("/api/models/switch", methods=["POST"])
    @require_auth
    def switch_model():
        data = request.get_json(silent=True) or {}
        model_id = data.get("model", "")
        from services.claude_service import LLMService, set_global_model
        llm = LLMService()
        if llm.set_model(model_id):
            return jsonify({"status": "switched", "model": model_id})
        return jsonify({"error": f"模型 {model_id} 不可用"}), 400

    # ── API Key 配置（模型提供商管理）──
    @app.route("/api/settings/providers", methods=["GET"])
    @require_auth
    def get_providers():
        def mask_key(k):
            if not k: return ""
            return k[:6] + "****" + k[-4:] if len(k) > 10 else "****"
        providers = config.MODEL_PROVIDERS if config.MODEL_PROVIDERS else []
        # 如果 MODEL_PROVIDERS 为空，从旧式 env var 构建
        if not providers:
            if os.getenv("LLM_API_KEY"):
                providers.append({
                    "name": "DeepSeek V4 Flash",
                    "base_url": os.getenv("LLM_BASE_URL", ""),
                    "api_key": os.getenv("LLM_API_KEY", ""),
                    "model": os.getenv("LLM_MODEL", ""),
                    "type": "text"
                })
            if os.getenv("MULTIMODAL_API_KEY"):
                providers.append({
                    "name": "智谱 GLM-4.6V",
                    "base_url": os.getenv("MULTIMODAL_BASE_URL", ""),
                    "api_key": os.getenv("MULTIMODAL_API_KEY", ""),
                    "model": os.getenv("MULTIMODAL_MODEL", ""),
                    "type": "multimodal"
                })
        result = []
        for p in providers:
            result.append({
                "name": p.get("name", ""),
                "base_url": p.get("base_url", ""),
                "api_key": p.get("api_key", ""),
                "masked": mask_key(p.get("api_key", "")),
                "model": p.get("model", ""),
                "type": p.get("type", "text"),
                "configured": bool(p.get("api_key", ""))
            })
        return jsonify({"providers": result})

    @app.route("/api/settings/providers", methods=["POST"])
    @require_auth
    def update_providers():
        data = request.get_json(silent=True) or {}
        providers = data.get("providers", [])
        env_file = config.BASE_DIR / ".env"
        if not env_file.exists():
            return jsonify({"error": ".env 文件不存在"}), 500

        # 读取当前 .env
        lines = env_file.read_text(encoding="utf-8").splitlines()

        # 新的 MODEL_PROVIDERS JSON 行
        new_providers_line = f"MODEL_PROVIDERS={_json.dumps(providers, ensure_ascii=False)}"

        # 查找并替换 MODEL_PROVIDERS 行，或追加
        found = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("MODEL_PROVIDERS="):
                lines[i] = new_providers_line
                found = True
                break

        # 同时更新旧式 env var 行以保持兼容
        updates = {}
        for p in providers:
            ptype = p.get("type", "text")
            if ptype == "text":
                updates["LLM_API_KEY"] = p.get("api_key", "")
                updates["LLM_BASE_URL"] = p.get("base_url", "")
                updates["LLM_MODEL"] = p.get("model", "")
            elif ptype == "multimodal":
                updates["MULTIMODAL_API_KEY"] = p.get("api_key", "")
                updates["MULTIMODAL_BASE_URL"] = p.get("base_url", "")
                updates["MULTIMODAL_MODEL"] = p.get("model", "")

        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                lines[i] = f"{key}={updates[key]}"
                os.environ[key] = str(updates[key])

        if not found:
            # 在 AVAILABLE_MODELS 行之前插入
            inserted = False
            for i, line in enumerate(lines):
                if line.strip().startswith("AVAILABLE_MODELS="):
                    lines.insert(i, new_providers_line)
                    inserted = True
                    break
            if not inserted:
                lines.append(new_providers_line)

        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # 更新运行时配置
        config.MODEL_PROVIDERS = providers
        config.LLM_API_KEY = updates.get("LLM_API_KEY", os.getenv("LLM_API_KEY", ""))
        config.MULTIMODAL_API_KEY = updates.get("MULTIMODAL_API_KEY", os.getenv("MULTIMODAL_API_KEY", ""))

        return jsonify({"status": "ok", "provider_count": len(providers)})

    # 错误处理
    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "接口不存在"}), 404

    @app.errorhandler(Exception)
    def server_error(e):
        log.error(f"服务器错误: {e}", exc_info=True)
        return jsonify({"error": "服务器内部错误", "detail": str(e)}), 500

    return app


app = create_app()

if __name__ == "__main__":
    log.info(f"AI Learning Assistant v2.0 启动中...")
    log.info(f"  API: http://{config.FLASK_HOST}:{config.FLASK_PORT}")
    configured = bool(config.LLM_API_KEY)
    log.info(f"  LLM configured: {'YES' if configured else 'NO'}")
    log.info(f"  Data dir: {config.DATA_DIR}")
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
        use_reloader=False
    )
