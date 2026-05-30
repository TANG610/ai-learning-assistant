"""
认证中间件 - JWT 鉴权装饰器
"""
import functools
import jwt
from flask import request, g, jsonify
import config


def _ensure_vercel_session_user(payload):
    """Recreate the JWT user row when Vercel's temporary SQLite DB is cold."""
    if not config.IS_VERCEL:
        return

    user_id = payload.get("user_id")
    if user_id is None:
        return

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return

    username = (payload.get("username") or "user").strip() or "user"
    session_username = f"{username}_{user_id}"
    session_email = f"{session_username}@vercel-session.local"

    from backend.models.database import get_db

    conn = get_db()
    try:
        row = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if row:
            return
        conn.execute(
            "INSERT OR IGNORE INTO users (id, username, email, password_hash) VALUES (?, ?, ?, ?)",
            (user_id, session_username, session_email, "vercel-session-placeholder"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO user_settings (user_id, preferences) VALUES (?, '{}')",
            (user_id,),
        )
        conn.commit()
    finally:
        conn.close()


def require_auth(f):
    """装饰器：验证 JWT token，将 user_id 注入 g 对象"""

    @functools.wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]

        if not token:
            return jsonify({"error": "未登录，请先登录"}), 401

        try:
            payload = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
            g.user_id = payload["user_id"]
            g.username = payload.get("username", "")
            _ensure_vercel_session_user(payload)
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "登录已过期，请重新登录"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "无效的令牌"}), 401

        return f(*args, **kwargs)

    return decorated


def optional_auth(f):
    """装饰器：可选认证，有 token 就解析，没有也放行"""

    @functools.wraps(f)
    def decorated(*args, **kwargs):
        g.user_id = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = jwt.decode(token, config.JWT_SECRET, algorithms=["HS256"])
                g.user_id = payload["user_id"]
                _ensure_vercel_session_user(payload)
            except jwt.InvalidTokenError:
                pass
        return f(*args, **kwargs)

    return decorated
